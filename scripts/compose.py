# -*- coding: utf-8 -*-
"""整套新编：材料 + 模板 → 文案流水线 S1–S5 → 克隆样例页填字 → 结构图两套 → 图片版、可编辑版两份 pptx。

    python scripts/compose.py 模板.pptx 材料.docx [材料2.pdf ...] -o out/汇报/汇报.pptx --req "给集团领导汇报 AI 办公成效"
        [--resume] [--until S3] [--regen] [--fix] [--no-diagrams] [--config config.yaml]

交给用户的只有：
    <封面中文题目>-图片版.pptx / <封面中文题目>-可编辑版.pptx
    （-o 基准名用封面题目，不要用技能英文 id 或内部代号）

生成过程中会写 `-过程/` 和 `-图/`，两份 pptx 写好后删除。检查结果打在屏幕上。
`--until` 停住时保留 `-过程/`，改完 JSON 再 `--resume`。
成品页 = 模板封面 + 模板目录（条目换成本稿章节；模板在章间也有目录时，每一章前都放一页）+ 页纲里的各页（按 clone_from 克隆）+ 模板致谢页，
模板其余样例页删掉。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from diagram.catalog import bind_styles
from diagram.palette import palette_from
from diagram.pipeline import VARIANTS, deck_font, figure_dir, finish, make_job, prepare_svgs, variant_path
from pptkit.autofill import cover_title_room, fill_page, fit_plan, page_capacity, slide_size
from pptkit.ooxml import clone_slide, delete_slide, find_ending_index, load_pptx, require_different, slide_order
from pptkit.profile import analyze
from pptkit.shapes import clear_region
from pptkit.slides import fill_toc, toc_entry_count

log = logging.getLogger("compose")

STEPS = ["S1", "S2", "S3", "S4", "S5"]
# 页纲里的图形类型 → 版式库（catalog/layouts）；没有对应的交给风格自由排
TYPE_LAYOUT = {
    "architecture": "layers", "layers": "layers", "flowchart": "flow", "pipeline": "pipeline",
    "matrix": "matrix", "comparison": "compare", "tree": "tree", "radial": "hub", "timeline": "timeline",
    "cycle": "cycle", "pyramid": "pyramid", "funnel": "funnel", "pillars": "pillars",
    "dashboard": "kpi", "kpi": "kpi",
}


class Steps:
    """每步结果落到 -过程/<名>.json；resume 时已有就直接读。"""

    def __init__(self, folder: Path, resume: bool):
        self.dir = folder
        self.dir.mkdir(parents=True, exist_ok=True)
        self.resume = resume

    def path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def cached(self, name: str):
        p = self.path(name)
        if self.resume and p.exists():
            log.info("复用 %s", p.name)
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def save(self, name: str, data) -> None:
        self.path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def merge_materials(materials: list[dict]) -> dict:
    if len(materials) == 1:
        return materials[0]
    merged = {"source_type": "merged", "source_path": ", ".join(m.get("source_path", "") for m in materials),
              "title": materials[0].get("title", ""), "sections": [], "images": [], "tables": [],
              "raw_char_count": 0}
    for m in materials:
        for key in ("sections", "images", "tables"):
            merged[key].extend(m.get(key, []))
        merged["raw_char_count"] += m.get("raw_char_count", 0)
    return merged


def content_capacity(template: Path, card: dict) -> dict[int, dict]:
    """每个正文样例页的容量：原标题、导语框字数、卡片字数、有没有图区（内容图片）。"""
    parts = load_pptx(template)
    slide_w, slide_h = slide_size(parts)
    caps = {}
    for s in card.get("slides", []):
        if s.get("role") == "content":
            cap = page_capacity(parts, s["index"], slide_w, slide_h)
            cap["diagram_area"] = any(
                p["kind"] == "review" and not _page_chrome(p, slide_w, slide_h) for p in s.get("pictures", [])
            )
            caps[s["index"]] = cap
    return caps


def fit_outline(outline: dict, caps: dict[int, dict]) -> dict:
    """clone_from 不是正文样例页时换一页（要图的优先有图区）；按样例页容量重算每页字数。可重复执行。"""
    if not caps:
        return outline
    with_area = [i for i, c in caps.items() if c["diagram_area"]]
    for pg in outline.get("pages", []):
        src = pg.get("clone_from")
        needs_fig = bool(pg.get("diagrams"))
        # 要图的页如果落在没有内容图的样例上，图会压住整段正文，改到有图区的样例
        if src not in caps or (needs_fig and with_area and not caps.get(src, {}).get("diagram_area")):
            pool = with_area if needs_fig and with_area else list(caps)
            pg["clone_from"] = pool[0]
            log.warning("页纲第 %s 页 clone_from=%s 不适合，改用第 %s 页", pg.get("page_index"), src, pool[0])
        pg["text_plan"] = fit_plan(pg.get("text_plan"), caps[pg["clone_from"]])
    return outline


async def write_text(steps: Steps, template: Path, materials: list[Path], requirement: str,
                     card: dict, until: str | None, config) -> tuple[dict, list[dict]] | None:
    """S1–S5，返回（页纲, 审后正文）；until 时跑到该步返回 None。S1 与 S2 互不依赖，并行。"""
    from llm.adapter import LLMAdapter
    from text.coherence import check_coherence
    from text.material import read_material
    from text.outline import write_outline
    from text.pages import fact_table, revise_pages, write_all_pages
    from text.summarize import number_facts, summarize
    from text.visual import profile_visual

    llm = None

    def adapter():
        nonlocal llm
        llm = llm or LLMAdapter(config)
        return llm

    material = steps.cached("材料")
    if material is None:
        material = merge_materials([read_material(str(p)) for p in materials])
        steps.save("材料", material)

    async def s1():
        summary = await summarize(material, adapter(), requirement=requirement)
        steps.save("S1_摘要", summary)
        return summary

    async def s2():
        try:
            visual = await profile_visual(template, card, adapter(), max_thumbnails=4)
        except Exception as exc:  # 没配视觉模型时跳过
            log.warning("S2 视觉理解跳过：%s", exc)
            visual = {}
        steps.save("S2_视觉理解", visual or {})
        return visual or {}

    summary, visual = steps.cached("S1_摘要"), steps.cached("S2_视觉理解")
    want_s2 = until != "S1"
    summary, visual = await asyncio.gather(
        s1() if summary is None else asyncio.sleep(0, summary),
        s2() if visual is None and want_s2 else asyncio.sleep(0, visual))
    summary = number_facts(summary)
    if until in ("S1", "S2"):
        return None

    caps = content_capacity(template, card)
    outline = steps.cached("S3_大纲")
    if outline is None:
        parts = load_pptx(template)
        outline = await write_outline(summary, card, requirement, adapter(), visual_profile=visual or None,
                                      page_slots=caps, cover_title_chars=cover_title_room(parts, *slide_size(parts)))
    outline = fit_outline(outline, caps)
    steps.save("S3_大纲", outline)
    if until == "S3":
        return None

    pages = steps.cached("S4_页面正文")
    if pages is None:
        pages = await write_all_pages(outline, summary, adapter())
        steps.save("S4_页面正文", pages)
    if until == "S4":
        return None

    final = steps.cached("S5_正文_审后")
    if final is None:
        limits = [(p.get("text_plan") or {}).get("max_total_chars", 0) for p in outline.get("pages", [])]
        final, report = await check_coherence(pages, outline.get("narrative") or {}, adapter(),
                                              facts=fact_table(summary), limits=limits)
        notes = {int(k): v for k, v in report.get("revise_notes", {}).items()}
        if notes:
            final = await revise_pages(outline, summary, final, notes, adapter())
        report["revised_pages"] = sorted(notes)
        steps.save("S5_正文_审后", final)
        steps.save("S5_审查报告", report)
    return outline, final


def _page_chrome(pic: dict, slide_w: float, slide_h: float) -> bool:
    """顶栏标志、通栏页脚、铺满整页的底图、中心落到页外的装饰，都不是内容图。"""
    x, y, w, h = pic.get("x", 0), pic.get("y", 0), pic.get("w", 0), pic.get("h", 0)
    cx, cy = x + w / 2, y + h / 2
    if cx < 0 or cy < 0 or cx > slide_w or cy > slide_h:
        return True
    if cy < slide_h * 0.22 and h < slide_h * 0.2:
        return True
    if w >= slide_w * 0.85 and h <= slide_h * 0.15 and y >= slide_h * 0.8:
        return True
    if w >= slide_w * 0.9 and h >= slide_h * 0.9:
        return True
    return False


def diagram_bbox(card: dict, source: int, slide_w: float, slide_h: float) -> tuple[dict, bool]:
    """图区：样例页上内容示意图的外接框，这些旧图要清掉。顶栏和页脚不算进去，否则会盖住上方文字。
    没有内容图就用正文区右半边。返回（bbox, 是否要清旧图）。"""
    slide = next((s for s in card.get("slides", []) if s["index"] == source), {})
    pics = [p for p in slide.get("pictures", []) if p["kind"] == "review" and not _page_chrome(p, slide_w, slide_h)]
    if pics:
        x0, y0 = min(p["x"] for p in pics), min(p["y"] for p in pics)
        x1, y1 = max(p["x"] + p["w"] for p in pics), max(p["y"] + p["h"] for p in pics)
        return {"x": x0, "y": y0, "w": round(x1 - x0, 2), "h": round(y1 - y0, 2)}, True
    return {"x": round(slide_w * 0.5, 2), "y": round(slide_h * 0.2, 2),
            "w": round(slide_w * 0.46, 2), "h": round(slide_h * 0.7, 2)}, False


def diagram_brief(dg: dict, data: dict | None) -> str:
    """页纲的图形描述 + 撰写阶段给出的要素和关系，拼成出图的图意。"""
    lines = [dg.get("description") or ""]
    data = data or {}
    if data.get("labels"):
        lines.append("要素：" + "、".join(str(x) for x in data["labels"]))
    for c in data.get("connections") or []:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            lines.append(f"关系：{c[0]} → {c[1]}" + (f"（{c[2]}）" if len(c) > 2 and c[2] else ""))
    if dg.get("data"):
        lines.append("数据：" + json.dumps(dg["data"], ensure_ascii=False))
    return "\n".join(x for x in lines if x)


def assemble(template: Path, card: dict, outline: dict, pages: list[dict], fig_dir: Path, style: str,
             with_diagrams: bool) -> tuple[dict, list[dict], dict]:
    """克隆页纲各页到致谢页前，删掉模板其余样例页，填字，并为有图的页建出图任务。"""
    parts = load_pptx(template)
    slide_w, slide_h = slide_size(parts)
    total = len(slide_order(parts))
    roles = {s["index"]: s["role"] for s in card.get("slides", [])}
    insert_at = find_ending_index(parts) or total + 1

    plan = [(pg, content) for pg, content in zip(outline.get("pages", []), pages)
            if isinstance(content, dict) and not content.get("_parse_error")
            and isinstance(pg.get("clone_from"), int) and 1 <= pg["clone_from"] <= total]
    chapters = list(dict.fromkeys(pg["section"] for pg, _ in plan if pg.get("section")))
    tocs = [i for i in range(1, insert_at) if roles.get(i) == "toc" and chapters and toc_entry_count(parts, i)]
    # 模板在章与章之间重复放目录时，每一章正文前都克隆一页；封面后那份由原页保留
    seq: list[tuple[str, int]] = []
    prev_section = None
    for n, (pg, _) in enumerate(plan):
        section = pg.get("section")
        if len(tocs) > 1 and prev_section and section and section != prev_section:
            seq.append(("toc", n))
        seq.append(("page", n))
        prev_section = section
    for k, (kind, n) in enumerate(seq):
        src = tocs[0] if kind == "toc" else plan[n][0]["clone_from"]
        clone_slide(parts, src if src < insert_at else src + k, insert_at + k)

    keep = {i for i in range(1, total + 1) if roles.get(i) in ("cover", "ending")} | set(tocs[:1])
    for i in sorted(set(range(1, total + 1)) - keep, reverse=True):
        delete_slide(parts, i if i < insert_at else i + len(seq))
    first = 1 + len([i for i in keep if i < insert_at])
    content_at: list[int] = []
    section_tocs: list[int] = []
    pos = first
    for kind, _n in seq:
        if kind == "toc":
            section_tocs.append(pos)
        else:
            content_at.append(pos)
        pos += 1

    report: dict = {"filled": [], "kept_template_slides": sorted(keep)}
    # 封面和目录默认必有；模板里没有对应页型就不生成，交付说明里要告诉用户
    missing = [name for name, ok in (("封面", any(roles.get(i) == "cover" for i in keep)), ("目录", bool(tocs))) if not ok]
    if missing:
        report["missing_pages"] = missing
        log.warning("模板里没有%s页型，本稿不生成，交付时告诉用户", "、".join(missing))
    body_style = ((card.get("fonts") or {}).get("roles") or {}).get("body")
    if any(roles.get(i) == "cover" for i in keep) and outline.get("title"):
        cover = {"title": outline["title"]}
        if outline.get("subtitle"):  # 材料里没有组织落款和日期时不写，避免留下模板原有落款
            cover["subtitle"] = outline["subtitle"]
        report["filled"].append(fill_page(parts, 1, cover, slide_w, slide_h, cover=True))
    if tocs:  # 封面后的目录，加上章与章之间克隆的目录，条目都换成本稿章节
        toc_at = [1 + len([i for i in keep if i < tocs[0]])] + section_tocs
        filled_tocs = [fill_toc(parts, slide, chapters, current=n) for n, slide in enumerate(toc_at)]
        report["toc"] = filled_tocs[0]
        if len(filled_tocs) > 1:
            report["toc"]["also"] = [item["slide"] for item in filled_tocs[1:]]
    jobs = []
    for n, (pg, content) in enumerate(plan):
        index = content_at[n]
        dgs = pg.get("diagrams") or []
        bbox, has_old = diagram_bbox(card, pg["clone_from"], slide_w, slide_h)
        report["filled"].append(fill_page(parts, index, {**content, "section": pg.get("section")},
                                          slide_w, slide_h, clear_captions=has_old, body_style=body_style))
        if has_old:  # 样例页上的旧示意图内容不对，不出图也要清掉
            clear_region(parts, index, "bbox", bbox, [])
        if not dgs:
            continue
        if not with_diagrams:
            continue
        dg = dgs[0]
        data = content.get("diagram_data") if isinstance(content.get("diagram_data"), dict) else None
        diag = {
            "name": (content.get("title") or pg.get("role") or "结构图")[:12],
            "title": (data or {}).get("title") or content.get("title", ""),
            "page_role": pg.get("role", ""),
            "brief": diagram_brief(dg, data),
            "bbox": bbox,
        }
        if TYPE_LAYOUT.get(dg.get("type")):
            diag["layout"] = TYPE_LAYOUT[dg["type"]]
        if style:
            diag["style"] = style
        jobs.append(make_job(fig_dir, index, index, diag))
    try:
        bind_styles([j["diagram"] for j in jobs])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return parts, jobs, report


def run(template: Path, materials: list[Path], dest: Path, requirement: str, style: str | None = None,
        config=None, resume: bool = False, until: str | None = None, regen: bool = False, fix: bool = False,
        with_diagrams: bool = True) -> dict | None:
    steps = Steps(dest.with_name(f"{dest.stem}-过程"), resume)
    card = steps.cached("风格卡") or analyze(template)
    steps.save("风格卡", card)
    got = asyncio.run(write_text(steps, template, materials, requirement, card, until, config))
    if got is None:
        log.info("已停在 %s，结果在 %s", until, steps.dir)
        return None
    outline, pages = got

    fig_dir = figure_dir(dest)
    parts, jobs, result = assemble(template, card, outline, pages, fig_dir, style, with_diagrams)
    steps.save("出图任务", [{k: v for k, v in j.items() if k != "svg"} for j in jobs])
    prepare_svgs(jobs, palette_from(card), config, regen, fix)
    result["process"] = str(steps.dir)
    return finish(parts, jobs, dest, deck_font(card), result, (card.get("fonts") or {}).get("roles"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="材料 + 模板 → 整套新编（图片版、可编辑版）")
    parser.add_argument("template")
    parser.add_argument("materials", nargs="+", help="docx / pdf / pptx / md / txt")
    parser.add_argument("-o", "--output", required=True, help="基准文件名，如 out/汇报/汇报.pptx")
    parser.add_argument("--req", default="请根据材料制作一份汇报PPT", help="用户要求：对象、场合、篇幅、侧重")
    parser.add_argument("--style", help="整稿想用的风格。不写则每种版式用预置；写了必须是该版式支持的，否则停下")
    parser.add_argument("--config", help="大模型配置；缺省按 common/paths.py 的顺序查找")
    parser.add_argument("--resume", action="store_true", help="复用 -过程/ 里已有的步骤结果")
    parser.add_argument("--until", choices=STEPS, help="跑到这一步就停")
    parser.add_argument("--regen", action="store_true", help="结构图忽略已有 SVG 重画")
    parser.add_argument("--fix", action="store_true", help="结构图没过检查时在原图上修补")
    parser.add_argument("--no-diagrams", action="store_true", help="只出文字，不出结构图")
    args = parser.parse_args()

    template, dest = Path(args.template), Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for tag in VARIANTS:
        require_different(template, variant_path(dest, tag))
    result = run(template, [Path(m) for m in args.materials], dest, args.req, args.style, args.config,
                 args.resume, args.until, args.regen, args.fix, not args.no_diagrams)
    if result:
        print(json.dumps(result, ensure_ascii=False, default=str, indent=1))


if __name__ == "__main__":
    main()
