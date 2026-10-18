# -*- coding: utf-8 -*-
"""单张结构图的调试入口：出图、检查、导 PNG、列风格版式。实现在 diagram/ 包里。

    python scripts/svg_diagram.py gen   --brief 图意.json -o 图.svg [--style report] [--layout tiers] [--style-card 模板.pptx]
    python scripts/svg_diagram.py fix   图.svg --brief 图意.json -o 新图.svg     # 在已有图上按检查结果和 feedback 修补
    python scripts/svg_diagram.py check 图.svg [--brief 图意.json] [--style report]
    python scripts/svg_diagram.py png   图.svg -o 图.png
    python scripts/svg_diagram.py prompt --brief 图意.json                       # 打印拼好的提示词，不调大模型
    python scripts/svg_diagram.py list
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from diagram import catalog
from diagram.checks import check_diagram
from diagram.generate import generate_svg
from diagram.palette import palette_from
from diagram.prompt import build_prompt
from diagram.render import render_png
from diagram.sizing import canvas_for
from diagram.svg_parse import svg_to_items


def _load_diag(path: str | None) -> dict:
    """图意 JSON；也可以是纯文本文件，整段当 brief。"""
    if not path:
        return {}
    raw = Path(path).read_text(encoding="utf-8")
    try:
        diag = json.loads(raw)
    except json.JSONDecodeError:
        return {"brief": raw}
    return diag if isinstance(diag, dict) else {"brief": raw}


def _palette(args, diag: dict) -> dict:
    card = None
    if args.style_card:
        sc = Path(args.style_card)
        if sc.suffix.lower() == ".pptx":
            from pptkit.profile import analyze

            card = analyze(sc)
        else:
            card = json.loads(sc.read_text(encoding="utf-8"))
    return palette_from(card, diag.get("palette"))


def main() -> None:
    styles, layouts = catalog.style_ids(), catalog.layout_ids()
    parser = argparse.ArgumentParser(description="大模型出 SVG → 高清 PNG → 可编辑形状")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def diag_args(p, brief_required=True):
        p.add_argument("--brief", required=brief_required, help="图意 JSON：name、title、brief、bbox、page_role、fonts…")
        p.add_argument("--style", choices=styles, help="覆盖图意里的 style")
        p.add_argument("--layout", choices=layouts, help="覆盖图意里的 layout")
        p.add_argument("--style-card", help="风格卡 JSON 或模板 pptx，用来推色板")

    g = sub.add_parser("gen")
    diag_args(g)
    g.add_argument("-o", required=True)
    g.add_argument("--config")
    f = sub.add_parser("fix")
    f.add_argument("svg")
    diag_args(f)
    f.add_argument("-o", required=True)
    f.add_argument("--config")
    pr = sub.add_parser("prompt")
    diag_args(pr)
    c = sub.add_parser("check")
    c.add_argument("svg")
    c.add_argument("--style", choices=styles, help="同时检查该风格的硬性要求")
    c.add_argument("--brief", help="图意 JSON 或纯文本文件，用来判断画重、字号")
    p = sub.add_parser("png")
    p.add_argument("svg")
    p.add_argument("-o", required=True)
    p.add_argument("--scale", type=int, default=4)
    sub.add_parser("list")
    args = parser.parse_args()

    if args.cmd == "list":
        print(json.dumps(catalog.describe(), ensure_ascii=False, indent=1))
        return
    if args.cmd == "png":
        render_png(Path(args.svg).read_text(encoding="utf-8"), Path(args.o), args.scale)
        print(json.dumps({"png": args.o}, ensure_ascii=False))
        return

    diag = _load_diag(args.brief)
    for key in ("style", "layout"):
        if getattr(args, key, None):
            diag[key] = getattr(args, key)
    if args.cmd != "check":
        try:
            catalog.bind_styles([diag])
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if args.cmd == "check":
        svg = Path(args.svg).read_text(encoding="utf-8")
        print(json.dumps({"problems": check_diagram(svg, diag), "items": len(svg_to_items(svg))},
                         ensure_ascii=False, indent=1))
        return
    palette = _palette(args, diag)
    if args.cmd == "prompt":
        print(build_prompt(diag, *canvas_for(diag["bbox"], diag.get("canvas_width", 1200)), palette))
        return

    from llm.adapter import LLMAdapter

    start = Path(args.svg).read_text(encoding="utf-8") if args.cmd == "fix" else None
    svg = asyncio.run(generate_svg(LLMAdapter(args.config), diag, palette, start=start))
    Path(args.o).write_text(svg, encoding="utf-8")
    print(json.dumps({"svg": args.o, "problems": check_diagram(svg, diag)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
