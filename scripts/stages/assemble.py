# -*- coding: utf-8 -*-
"""assemble：读 outline + pages → 克隆填字 → 中间稿 + diagram_jobs。

不调用外部模型。输入兼容：
  run/outline.json 或 run/S3_大纲.json
  run/pages.json   或 run/S4_页面正文.json / S5_正文_审后.json
  run/风格卡.json、manifest.json；模板来自 manifest 或 --template

    python scripts/stages/assemble.py --run <run目录> [-o 基准.pptx] [--template 模板.pptx]
    python scripts/stages/assemble.py --run <run目录> --no-diagrams
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from diagram.catalog import bind_styles
from diagram.pipeline import figure_dir, make_job
from layout_policy import TYPE_LAYOUT, check_diversity, _layouts_from_jobs
from pptkit.autofill import fill_page, fit_plan, page_capacity, slide_size
from pptkit.ooxml import clone_slide, delete_slide, find_ending_index, load_pptx, save_pptx, slide_order
from pptkit.profile import analyze
from pptkit.shapes import clear_region
from pptkit.slides import fill_toc, relayout_section_tabs, toc_entry_count

log = logging.getLogger("assemble")

MIN_DIAGRAM_TOP = 3.15  # 导语底边常见 ~2.95，保证间隙 ≥0.15″

# TYPE_LAYOUT 见 layout_policy.TYPE_LAYOUT


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _first_existing(run: Path, names: list[str]) -> Path | None:
    for n in names:
        p = run / n
        if p.exists():
            return p
    return None


def _pages_list(raw) -> list[dict]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        pages = raw.get("pages")
        if isinstance(pages, list):
            return pages
    raise SystemExit("pages JSON 须为数组，或含 pages 数组的对象")


def _short_tab(chapter: str) -> str:
    """页签名：去编号后尽量完整可读，单行平铺；禁止按固定字数硬截断。"""
    label = re.sub(r"^[一二三四五六七八九十]+、\s*", "", (chapter or "").strip())
    # 可选友好短名（完整词替换，不是截断）
    aliases = {
        "我的需求": "我的需求",
        "网上的主流做法": "主流做法",
        "pptx-compose 的做法": "本技能做法",
        "pptx-unit 的做法": "本技能做法",
        "后续优化": "后续优化",
    }
    if label in aliases:
        return aliases[label]
    # 去冗余后缀「情况」：仅当总长≥8 且去掉后仍可辨识
    if label.endswith("情况") and len(label) >= 8:
        label = label[:-2]
    return label or (chapter or "")


def _page_chrome(pic: dict, slide_w: float, slide_h: float) -> bool:
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


def content_capacity(template: Path, card: dict) -> dict[int, dict]:
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
    if not caps:
        return outline
    with_area = [i for i, c in caps.items() if c["diagram_area"]]
    for pg in outline.get("pages", []):
        src = pg.get("clone_from")
        needs_fig = bool(pg.get("diagrams"))
        if src not in caps or (needs_fig and with_area and not caps.get(src, {}).get("diagram_area")):
            pool = with_area if needs_fig and with_area else list(caps)
            if pool:
                pg["clone_from"] = pool[0]
                log.warning("页纲第 %s 页 clone_from=%s 不适合，改用第 %s 页", pg.get("page_index"), src, pool[0])
        if pg.get("clone_from") in caps:
            pg["text_plan"] = fit_plan(pg.get("text_plan"), caps[pg["clone_from"]])
    return outline


def diagram_bbox(card: dict, source: int, slide_w: float, slide_h: float) -> tuple[dict, bool]:
    slide = next((s for s in card.get("slides", []) if s["index"] == source), {})
    pics = [p for p in slide.get("pictures", []) if p["kind"] == "review" and not _page_chrome(p, slide_w, slide_h)]
    if pics:
        x0, y0 = min(p["x"] for p in pics), min(p["y"] for p in pics)
        x1, y1 = max(p["x"] + p["w"] for p in pics), max(p["y"] + p["h"] for p in pics)
        return {"x": x0, "y": y0, "w": round(x1 - x0, 2), "h": round(y1 - y0, 2)}, True
    return {"x": round(slide_w * 0.5, 2), "y": round(slide_h * 0.2, 2),
            "w": round(slide_w * 0.46, 2), "h": round(slide_h * 0.7, 2)}, False


def diagram_brief(dg: dict, data: dict | None) -> str:
    lines = [dg.get("description") or ""]
    data = data or {}
    if data.get("labels"):
        lines.append("要素：" + "、".join(str(x) for x in data["labels"]))
    for c in data.get("connections") or []:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            lines.append(f"关系：{c[0]} → {c[1]}" + (f"（{c[2]}）" if len(c) > 2 and c[2] else ""))
    if data.get("brief"):
        lines.append(str(data["brief"]))
    if dg.get("data"):
        lines.append("数据：" + json.dumps(dg["data"], ensure_ascii=False))
    return "\n".join(x for x in lines if x)


def _palette_colors(card: dict) -> list[str]:
    """风格卡 palette.title 可能是色值列表，也可能是带 dark/mid 的对象。"""
    pal = card.get("palette") or {}
    title = pal.get("title")
    out: list[str] = []
    if isinstance(title, list):
        out.extend(c for c in title if isinstance(c, str))
    elif isinstance(title, dict):
        for key in ("dark", "mid", "accent", "mute", "light"):
            c = title.get(key)
            if isinstance(c, str):
                out.append(c)
    for key in ("dark", "mid", "accent", "mute", "light"):
        c = pal.get(key)
        if isinstance(c, str):
            out.append(c)
    return [c for c in out if re.fullmatch(r"[0-9A-Fa-f]{6}", c)]


def _luminance(hex6: str) -> float:
    h = hex6.lstrip("#")
    if len(h) != 6:
        return 999.0
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _tab_highlight(card: dict) -> str:
    """顶栏当前章：取色板里偏深的实色（旧稿约 006F68），禁止用浅底当高亮。"""
    colors = _palette_colors(card)
    dark = [c for c in colors if _luminance(c) < 120]
    if dark:
        return min(dark, key=_luminance)
    mid = [c for c in colors if _luminance(c) < 160]
    if mid:
        return min(mid, key=_luminance)
    return "006F68"


def _tab_rest(card: dict) -> str:
    """未选中页签字色：中等青绿，避免与高亮同色。"""
    colors = _palette_colors(card)
    hi = _tab_highlight(card)
    cands = [c for c in colors if c.upper() != hi.upper() and 80 < _luminance(c) < 180]
    if cands:
        return sorted(cands, key=lambda c: abs(_luminance(c) - 130))[0]
    return "62A7A4"


def assemble(template: Path, card: dict, outline: dict, pages: list[dict], fig_dir: Path,
             style: str | None, with_diagrams: bool) -> tuple[dict, list[dict], dict]:
    """克隆页纲各页到致谢页前，删模板其余样例页，填字，建出图任务，重排正文页签。"""
    parts = load_pptx(template)
    slide_w, slide_h = slide_size(parts)
    total = len(slide_order(parts))
    roles = {s["index"]: s["role"] for s in card.get("slides", [])}
    insert_at = find_ending_index(parts) or total + 1

    plan = [(pg, content) for pg, content in zip(outline.get("pages", []), pages)
            if isinstance(content, dict) and not content.get("_parse_error")
            and isinstance(pg.get("clone_from"), int) and 1 <= pg["clone_from"] <= total]
    chapters = list(dict.fromkeys(pg["section"] for pg, _ in plan if pg.get("section")))
    # 优先能 fill_toc 的目录；若全为 0，仍保留 role=toc 的第一页以免整稿无目录
    toc_all = [i for i in range(1, insert_at) if roles.get(i) == "toc"]
    tocs = [i for i in toc_all if chapters and toc_entry_count(parts, i)]
    if not tocs and toc_all and chapters:
        raise SystemExit(
            "目录页 toc_entry_count 全为 0：既无 01 徽标（模式 A）也无「一、」行（模式 B），"
            f"样例页 {toc_all}。拒绝静默保留模板旧章；请换模板或扩识别后再 assemble。"
        )

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

    report: dict = {"filled": [], "kept_template_slides": sorted(keep), "tabs": []}
    missing = [name for name, ok in (("封面", any(roles.get(i) == "cover" for i in keep)),
                                     ("目录", bool(tocs))) if not ok]
    if missing:
        report["missing_pages"] = missing
        log.warning("模板里没有%s页型，本稿不生成", "、".join(missing))

    body_style = ((card.get("fonts") or {}).get("roles") or {}).get("body")
    if any(roles.get(i) == "cover" for i in keep) and outline.get("title"):
        cover = {"title": outline["title"]}
        if outline.get("subtitle"):
            cover["subtitle"] = outline["subtitle"]
        report["filled"].append(fill_page(parts, 1, cover, slide_w, slide_h, cover=True))

    toc_at: list[int] = []
    if tocs:
        toc_at = [1 + len([i for i in keep if i < tocs[0]])] + section_tocs
        filled_tocs = [fill_toc(parts, slide, chapters, current=n) for n, slide in enumerate(toc_at)]
        bad = [item for item in filled_tocs if item.get("status") != "filled"]
        if bad:
            raise SystemExit(
                "目录 fill_toc 失败，禁止交付仍带模板旧章的目录："
                + "; ".join(f"slide {b.get('slide')} status={b.get('status')}" for b in bad)
            )
        report["toc"] = filled_tocs[0]
        report["toc_all"] = filled_tocs
        if len(filled_tocs) > 1:
            report["toc"]["also"] = [item["slide"] for item in filled_tocs[1:]]

    tab_labels = [_short_tab(c) for c in chapters]
    hi, rest = _tab_highlight(card), _tab_rest(card)
    jobs: list[dict] = []
    for n, (pg, content) in enumerate(plan):
        index = content_at[n]
        dgs = pg.get("diagrams") or []
        bbox, has_old = diagram_bbox(card, pg["clone_from"], slide_w, slide_h)
        # pages 里若带 bbox 覆盖
        dd = content.get("diagram_data") if isinstance(content.get("diagram_data"), dict) else None
        if dd and isinstance(dd.get("bbox"), dict):
            b = dd["bbox"]
            if {"x", "y", "w", "h"} <= set(b) or {"l", "t", "w", "h"} <= set(b):
                bbox = {
                    "x": float(b.get("x", b.get("l", bbox["x"]))),
                    "y": float(b.get("y", b.get("t", bbox["y"]))),
                    "w": float(b["w"]),
                    "h": float(b["h"]),
                }
                has_old = True
        # 强制结构图顶边不低于 MIN_DIAGRAM_TOP，避免侵入导语
        if bbox.get("y", 0) < MIN_DIAGRAM_TOP:
            bottom = float(bbox["y"]) + float(bbox["h"])
            bbox = {**bbox, "y": MIN_DIAGRAM_TOP, "h": max(3.5, bottom - MIN_DIAGRAM_TOP)}
        report["filled"].append(fill_page(parts, index, {**content, "section": pg.get("section")},
                                          slide_w, slide_h, clear_captions=has_old, body_style=body_style))
        if has_old:
            clear_region(parts, index, "bbox", bbox, [])

        if tab_labels and pg.get("section"):
            try:
                cur = chapters.index(pg["section"])
            except ValueError:
                cur = 0
            tab_res = relayout_section_tabs(
                parts, index, tab_labels, cur,
                highlight_fill=hi, rest_text=rest, by_chars=True, gap=0.0,
            )
            report["tabs"].append(tab_res)

        if not dgs or not with_diagrams:
            continue
        dg = dgs[0]
        data = dd
        diag = {
            "name": (content.get("title") or pg.get("role") or "结构图")[:12],
            "title": (data or {}).get("title") or content.get("title", ""),
            "page_role": pg.get("role", ""),
            "brief": diagram_brief(dg, data),
            "bbox": bbox,
        }
        layout = TYPE_LAYOUT.get(dg.get("type")) or (data or {}).get("layout") or dg.get("layout")
        if layout:
            diag["layout"] = layout
        st = style or (data or {}).get("style") or dg.get("style")
        if st:
            diag["style"] = st
        jobs.append(make_job(fig_dir, index, index, diag))

    try:
        bind_styles([j["diagram"] for j in jobs])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    report["content_slides"] = content_at
    report["toc_slides"] = toc_at
    report["chapters"] = chapters
    return parts, jobs, report


def _serialize_jobs(jobs: list[dict]) -> list[dict]:
    out = []
    for j in jobs:
        out.append({
            "slide": j["slide"],
            "label": j["slide"],
            "diagram": j["diagram"],
            "svg": Path(j["svg_path"]).name,
        })
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="assemble：大纲+正文 → 中间稿 + diagram_jobs")
    ap.add_argument("--run", required=True, help="run 目录")
    ap.add_argument("-o", "--output", help="基准 pptx 路径；默认 run/中间稿.pptx（实际只写这一份中间稿）")
    ap.add_argument("--template", help="覆盖 manifest 中的模板")
    ap.add_argument("--style", help="全稿统一风格 id（可选）")
    ap.add_argument("--no-diagrams", action="store_true", help="只填字清旧图，不建出图任务")
    ap.add_argument("--skip-fit", action="store_true", help="不按样例页容量改 text_plan")
    ap.add_argument("--skip-layout-check", action="store_true", help="跳过结构图版式多样性硬检（不推荐）")
    args = ap.parse_args()

    run = Path(args.run).resolve()
    if not run.is_dir():
        raise SystemExit(f"run 目录不存在: {run}")
    task = run.parent

    man_path = run / "manifest.json"
    man = _load_json(man_path) if man_path.exists() else {}
    tpl_name = args.template or man.get("template")
    if not tpl_name:
        raise SystemExit("需要 --template 或 manifest.template")
    template = Path(tpl_name)
    if not template.is_absolute():
        template = (task / template).resolve()
    if not template.exists():
        raise SystemExit(f"找不到模板: {template}")

    outline_path = _first_existing(run, ["outline.json", "S3_大纲.json"])
    pages_path = _first_existing(run, ["pages.json", "S4_页面正文.json", "S5_正文_审后.json", "S5_页面正文.json"])
    if not outline_path or not pages_path:
        raise SystemExit(
            "缺少大纲或正文。请写入 run/outline.json（或 S3_大纲.json）与 "
            "run/pages.json（或 S4_页面正文.json）"
        )
    outline = _load_json(outline_path)
    pages = _pages_list(_load_json(pages_path))
    if len(pages) < len(outline.get("pages") or []):
        log.warning("正文页数 %s < 大纲页数 %s，只组装对齐的前若干页", len(pages), len(outline["pages"]))

    card_path = run / "风格卡.json"
    card = _load_json(card_path) if card_path.exists() else analyze(template)
    if not card_path.exists():
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if not args.skip_fit:
        outline = fit_outline(outline, content_capacity(template, card))
        # 回写拟合后的大纲，便于助手核对
        outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    dest = Path(args.output) if args.output else (run / "中间稿.pptx")
    if not dest.suffix:
        dest = dest.with_suffix(".pptx")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig_dir = run / "diagrams"
    fig_dir.mkdir(exist_ok=True)
    # make_job 用 fig_dir 命名 svg；同时保留 figure_dir 兼容
    _ = figure_dir(dest)  # noqa: F841 — 旧路径旁注；jobs 指向 run/diagrams

    parts, jobs, report = assemble(
        template, card, outline, pages, fig_dir, args.style, not args.no_diagrams,
    )
    # 统一 svg 落在 run/diagrams/
    for j in jobs:
        j["svg_path"] = fig_dir / Path(j["svg_path"]).name
        j["png_path"] = fig_dir / (Path(j["svg_path"]).stem + ".png")

    save_pptx(dest, parts)
    jobs_path = run / "diagram_jobs.json"
    ser_jobs = _serialize_jobs(jobs)
    jobs_path.write_text(json.dumps(ser_jobs, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    layout_check = {"ok": True, "errors": []}
    if jobs and not args.skip_layout_check:
        layout_check["errors"] = check_diversity(_layouts_from_jobs(ser_jobs))
        layout_check["ok"] = not layout_check["errors"]
        report["layout_policy"] = layout_check
        (run / "layout_policy_report.json").write_text(
            json.dumps(layout_check, ensure_ascii=False, indent=2), encoding="utf-8")
        if not layout_check["ok"]:
            (run / "assemble_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            for err in layout_check["errors"]:
                log.error("layout_policy: %s", err)
            raise SystemExit(
                "结构图版式多样性检查未通过（见 run/layout_policy_report.json）。"
                "请调整 outline/pages 的 layout 后重跑 assemble；紧急跳过可用 --skip-layout-check。"
            )
    (run / "assemble_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if man_path.exists():
        man = _load_json(man_path)
        man.setdefault("stages", {})["assemble"] = "done"
        man.setdefault("stages", {})["text"] = "done"
        if outline.get("title"):
            man["title"] = outline["title"]
        man["intermediate"] = str(dest)
        man["diagram_jobs"] = str(jobs_path)
        man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "中间稿": str(dest),
        "diagram_jobs": str(jobs_path),
        "job_count": len(jobs),
        "slide_count": len(slide_order(parts)),
        "content_slides": report.get("content_slides"),
        "toc": report.get("toc"),
        "missing_pages": report.get("missing_pages"),
        "svg_expected": [Path(j["svg_path"]).name for j in jobs],
    }, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
