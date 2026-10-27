# -*- coding: utf-8 -*-
"""结构图版式策略：模板版式清单、防单调检查、新版式脚手架。

    python scripts/layout_policy.py inventory --style-card 风格卡.json -o 模板版式清单.json
    python scripts/layout_policy.py check-diversity --jobs diagram_jobs.json [--strict]
    python scripts/layout_policy.py check-run --run <run目录> [--strict]
    python scripts/layout_policy.py scaffold --id my_layout --name "中文名" --when "什么时候用"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# 页纲 type → catalog layout id（单一来源）
TYPE_LAYOUT = {
    "architecture": "layers",
    "layers": "layers",
    "flowchart": "flow",
    "flow": "flow",
    "pipeline": "pipeline",
    "matrix": "matrix",
    "comparison": "compare",
    "compare": "compare",
    "tree": "tree",
    "radial": "hub",
    "hub": "hub",
    "timeline": "timeline",
    "cycle": "cycle",
    "pyramid": "pyramid",
    "funnel": "funnel",
    "pillars": "pillars",
    "dashboard": "kpi",
    "kpi": "kpi",
    "tiers": "tiers",
    "cards": "matrix",
    "wireframe": "matrix",
}

# 文案关键词 → 猜测 layout（弱启发，须人工核对）
_KEYWORD_LAYOUT = [
    (re.compile(r"漏斗|转化|筛"), "funnel"),
    (re.compile(r"金字塔|上窄下宽"), "pyramid"),
    (re.compile(r"循环|闭环|回到"), "cycle"),
    (re.compile(r"时间轴|里程碑|演进"), "timeline"),
    (re.compile(r"中心|辐射|枢纽|平台.*服务"), "hub"),
    (re.compile(r"树|拆成|总分|分支"), "tree"),
    (re.compile(r"分层|层级|上下层|色带"), "layers"),
    (re.compile(r"分级部署|底座.*能力|自下而上"), "tiers"),
    (re.compile(r"支柱|三驾马车|共同撑"), "pillars"),
    (re.compile(r"对照|对比|改前|改后|左右"), "compare"),
    (re.compile(r"流程|步骤|先后|怎么走"), "flow"),
    (re.compile(r"类型.*用途|方案.*做法.*特点|一览"), "pipeline"),
    (re.compile(r"KPI|大数字|指标卡"), "kpi"),
    (re.compile(r"并列|能力|特色|矩阵|卡片"), "matrix"),
]


def resolve_layout(type_or_layout: str | None) -> str | None:
    if not type_or_layout:
        return None
    key = str(type_or_layout).strip()
    if key in TYPE_LAYOUT:
        return TYPE_LAYOUT[key]
    # already a catalog id
    from diagram.catalog import layout_ids

    if key in layout_ids():
        return key
    return key  # unknown; caller may flag


def _slide_plain(slide: dict) -> str:
    parts = []
    for slot in slide.get("text_slots") or []:
        t = slot.get("text") or slot.get("全文") or ""
        if t:
            parts.append(t)
    return "\n".join(parts)


def guess_layout(plain: str, has_shape: bool) -> tuple[str | None, str]:
    """返回 (layout_id_or_None, note)。"""
    for pat, lid in _KEYWORD_LAYOUT:
        if pat.search(plain):
            return lid, f"关键词命中→{lid}（须核对）"
    if has_shape:
        return None, "有形状结构图，待助手对照样例定 layout"
    return None, "未自动识别，待助手看图归类"


def build_inventory(style_card: dict) -> dict:
    slides = style_card.get("slides") or []
    entries = []
    for s in slides:
        role = s.get("role") or ""
        if role in ("cover", "toc", "ending"):
            continue
        pics = s.get("pictures") or []
        dig_pics = [
            p
            for p in pics
            if (p.get("kind") in ("diagram", "review") or (p.get("hint") or "") == "diagram")
        ]
        has_shape = bool(s.get("has_shape_diagram"))
        if not dig_pics and not has_shape:
            continue
        plain = _slide_plain(s)
        title = ""
        for slot in s.get("text_slots") or []:
            t = (slot.get("text") or "").strip().split("\n")[0]
            if t and len(t) <= 40:
                title = t
                break
        layout, note = guess_layout(plain, has_shape)
        mapped = None
        pending = False
        if layout:
            from diagram.catalog import layout_ids

            if layout in layout_ids():
                mapped = layout
            else:
                pending = True
        else:
            pending = True
        entries.append(
            {
                "slide_index": s.get("index"),
                "role": role,
                "title_hint": title,
                "has_shape_diagram": has_shape,
                "diagram_picture_count": len(dig_pics),
                "guessed_layout": layout,
                "mapped_layout": mapped,
                "pending_preset": pending and not mapped,
                "note": note,
                "source": "template",
            }
        )
    layouts_seen = sorted({e["mapped_layout"] for e in entries if e.get("mapped_layout")})
    return {
        "source": style_card.get("source"),
        "candidate_count": len(entries),
        "mapped_layouts": layouts_seen,
        "pending_count": sum(1 for e in entries if e.get("pending_preset")),
        "entries": entries,
        "policy": {
            "priority": ["template", "catalog", "scaffold_then_use"],
            "diversity": {
                "no_consecutive_same_layout": True,
                "min_layouts_when_ge_4": 3,
                "max_share_matrix_or_flow_cards": 0.5,
            },
        },
    }


def _layouts_from_jobs(jobs: list) -> list[tuple[int | None, str | None]]:
    rows = []
    for j in jobs:
        slide = j.get("slide") or j.get("label")
        diag = j.get("diagram") or j
        layout = diag.get("layout") if isinstance(diag, dict) else None
        if not layout and isinstance(diag, dict):
            layout = resolve_layout(diag.get("type"))
        rows.append((slide, layout))
    return rows


def _layouts_from_outline(outline: dict | list) -> list[tuple[int | None, str | None]]:
    pages = outline if isinstance(outline, list) else (outline.get("pages") or [])
    rows = []
    for i, page in enumerate(pages):
        diags = page.get("diagrams") or []
        if not diags and page.get("diagram"):
            diags = [page["diagram"]]
        for dg in diags:
            if not isinstance(dg, dict):
                continue
            layout = resolve_layout(dg.get("layout") or dg.get("type"))
            rows.append((page.get("page_index", i), layout))
    return rows


def check_diversity(layout_rows: list[tuple[int | None, str | None]]) -> list[str]:
    """返回问题列表；空=通过。"""
    issues: list[str] = []
    usable = [(s, lay) for s, lay in layout_rows if lay]
    if not usable:
        return issues

    # consecutive same
    prev = None
    prev_slide = None
    for slide, lay in usable:
        if prev is not None and lay == prev:
            issues.append(
                f"相邻结构图版式重复：slide {prev_slide} 与 {slide} 均为「{lay}」（防单调）"
            )
        prev, prev_slide = lay, slide

    n = len(usable)
    kinds = Counter(lay for _, lay in usable)
    distinct = len(kinds)
    if n >= 4 and distinct < 3:
        issues.append(
            f"整稿有 {n} 张结构图，但只有 {distinct} 种 layout（{dict(kinds)}），至少需要 3 种"
        )

    # matrix + flow(竖卡横排类) 合计不得超过一半
    monoish = kinds.get("matrix", 0) + kinds.get("flow", 0)
    if n >= 4 and monoish > n * 0.5:
        issues.append(
            f"matrix+flow 共 {monoish}/{n} 张，超过一半，版式过于单一（应多用 hub/tree/tiers/pipeline/layers 等）"
        )

    # unknown layouts
    try:
        from diagram.catalog import layout_ids

        known = set(layout_ids())
        for slide, lay in usable:
            if lay not in known:
                issues.append(
                    f"slide {slide} 的 layout「{lay}」不在 catalog/layouts，须先 scaffold 入库"
                )
    except Exception as exc:  # noqa: BLE001
        issues.append(f"无法读取 catalog：{exc}")

    return issues


def check_run(run: Path, strict: bool = True) -> dict:
    run = Path(run)
    report: dict = {"run": str(run), "ok": True, "errors": [], "warnings": [], "files": {}}

    inv_path = run / "模板版式清单.json"
    if inv_path.exists():
        report["files"]["inventory"] = str(inv_path)
    else:
        style = run / "风格卡.json"
        if style.exists():
            inv = build_inventory(json.loads(style.read_text(encoding="utf-8")))
            inv_path.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
            report["files"]["inventory"] = str(inv_path)
            report["warnings"].append("缺少模板版式清单，已据风格卡自动生成")
        else:
            report["warnings"].append("无风格卡、无模板版式清单，跳过模板侧检查")

    jobs_path = run / "diagram_jobs.json"
    outline_path = None
    for name in ("outline.json", "S3_大纲.json"):
        if (run / name).exists():
            outline_path = run / name
            break

    rows: list[tuple[int | None, str | None]] = []
    if jobs_path.exists():
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        if isinstance(jobs, list):
            rows = _layouts_from_jobs(jobs)
            report["files"]["jobs"] = str(jobs_path)
    elif outline_path:
        outline = json.loads(outline_path.read_text(encoding="utf-8"))
        rows = _layouts_from_outline(outline)
        report["files"]["outline"] = str(outline_path)
        report["warnings"].append("尚无 diagram_jobs，多样性检查基于 outline")

    if rows:
        report["layouts"] = [{"slide": s, "layout": lay} for s, lay in rows]
        issues = check_diversity(rows)
        if strict:
            report["errors"].extend(issues)
        else:
            report["warnings"].extend(issues)
    else:
        report["warnings"].append("未找到可检查的结构图 layout 序列")

    # pending presets in inventory
    if inv_path.exists():
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
        pending = [e for e in inv.get("entries") or [] if e.get("pending_preset")]
        if pending and not rows:
            report["warnings"].append(
                f"模板版式清单有 {len(pending)} 条待归类/待补预置，写页纲前请助手补全"
            )

    report["ok"] = not report["errors"]
    return report


def scaffold_layout(layout_id: str, name: str, when: str, default_style: str = "consult") -> list[str]:
    """创建 layouts/<id>.md 并写入 pairing；返回操作说明。"""
    from diagram.catalog import layout_ids, pairing, style_ids

    actions = []
    lid = layout_id.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,32}", lid):
        raise SystemExit("layout id 须为小写字母开头的 [a-z0-9_]，长度 2–33")

    lay_path = ROOT / "catalog" / "layouts" / f"{lid}.md"
    if not lay_path.exists():
        lay_path.write_text(
            f"版式：{name}（{when}）\n\n"
            f"- 按信息结构画出可区分的几何骨架，禁止缩成一排相同圆角方块。\n"
            f"- 每块须有标题 + ≥1 行说明；色相跟当次模板，不跟范例样品色。\n"
            f"- （脚手架：请宿主助手补全具体分区、比例与连线规则后再出正式图。）\n",
            encoding="utf-8",
        )
        actions.append(f"已写 {lay_path.relative_to(ROOT)}")
    else:
        actions.append(f"已存在 {lay_path.relative_to(ROOT)}，未覆盖")

    pair_path = ROOT / "catalog" / "pairing.yaml"
    import yaml  # type: ignore

    data = pairing()
    table = data.setdefault("layouts", {})
    styles = list(style_ids())
    if default_style not in styles:
        default_style = styles[0] if styles else "consult"
    if lid not in table:
        table[lid] = {"default": default_style, "styles": [default_style, "rounded", "report"]}
        # filter to existing
        table[lid]["styles"] = [s for s in table[lid]["styles"] if s in styles] or [default_style]
        pair_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        actions.append(f"已写入 pairing.yaml layouts.{lid}")
    else:
        actions.append(f"pairing.yaml 已有 {lid}，未改")

    actions.append("请补全 layouts 规则，更新 prompts/text/outline_pages.md，再运行：")
    actions.append("  python scripts/check_presets.py")
    actions.append("  （暂无图库重建脚本）手改 catalog/图库.html，或跳过图库同步")
    return actions


def main() -> None:
    ap = argparse.ArgumentParser(description="pptx-unit 版式策略")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_inv = sub.add_parser("inventory", help="从风格卡导出模板版式清单")
    p_inv.add_argument("--style-card", required=True)
    p_inv.add_argument("-o", "--out", required=True)

    p_div = sub.add_parser("check-diversity", help="检查 diagram_jobs / 显式 layout 列表")
    p_div.add_argument("--jobs", help="diagram_jobs.json")
    p_div.add_argument("--outline", help="outline.json")
    p_div.add_argument("--strict", action="store_true", default=True)
    p_div.add_argument("--no-strict", action="store_true")

    p_run = sub.add_parser("check-run", help="对 run 目录做版式策略终检")
    p_run.add_argument("--run", required=True)
    p_run.add_argument("--strict", action="store_true", default=True)
    p_run.add_argument("--no-strict", action="store_true")

    p_sc = sub.add_parser("scaffold", help="新版式入库脚手架")
    p_sc.add_argument("--id", required=True)
    p_sc.add_argument("--name", required=True)
    p_sc.add_argument("--when", required=True)
    p_sc.add_argument("--style", default="consult")

    args = ap.parse_args()

    if args.cmd == "inventory":
        card = json.loads(Path(args.style_card).read_text(encoding="utf-8"))
        inv = build_inventory(card)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "out": str(out), "candidate_count": inv["candidate_count"],
                          "mapped_layouts": inv["mapped_layouts"], "pending_count": inv["pending_count"]},
                         ensure_ascii=False, indent=2))
        return

    if args.cmd == "check-diversity":
        strict = not args.no_strict
        rows: list[tuple[int | None, str | None]] = []
        if args.jobs:
            jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
            rows = _layouts_from_jobs(jobs)
        elif args.outline:
            outline = json.loads(Path(args.outline).read_text(encoding="utf-8"))
            rows = _layouts_from_outline(outline)
        else:
            raise SystemExit("需要 --jobs 或 --outline")
        issues = check_diversity(rows)
        report = {"ok": not issues if strict else True, "errors": issues if strict else [],
                  "warnings": [] if strict else issues,
                  "layouts": [{"slide": s, "layout": lay} for s, lay in rows]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if strict and issues:
            raise SystemExit(1)
        return

    if args.cmd == "check-run":
        strict = not args.no_strict
        report = check_run(Path(args.run), strict=strict)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            raise SystemExit(1)
        return

    if args.cmd == "scaffold":
        for line in scaffold_layout(args.id, args.name, args.when, args.style):
            print(line)


if __name__ == "__main__":
    main()
