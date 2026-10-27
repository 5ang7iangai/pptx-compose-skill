# -*- coding: utf-8 -*-
"""单张结构图调试：检查、导 PNG、拼提示词、列风格版式。

pptx-unit 不调外部模型。gen/fix 会打印提示词并 exit 2，请助手写好 SVG 后用 check/png。

    python scripts/svg_diagram.py check 图.svg [--brief 图意.json] [--style report]
    python scripts/svg_diagram.py png   图.svg -o 图.png
    python scripts/svg_diagram.py prompt --brief 图意.json
    python scripts/svg_diagram.py list
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from diagram import catalog
from diagram.checks import check_diagram
from diagram.palette import palette_from
from diagram.prompt import build_prompt
from diagram.render import render_png
from diagram.sizing import canvas_for
from diagram.svg_parse import svg_to_items


def _load_diag(path: str | None) -> dict:
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
    parser = argparse.ArgumentParser(description="SVG 检查 / PNG / 提示词（不调外部模型）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def diag_args(p, brief_required=True):
        p.add_argument("--brief", required=brief_required, help="图意 JSON")
        p.add_argument("--style", choices=styles, help="覆盖图意里的 style")
        p.add_argument("--layout", choices=layouts, help="覆盖图意里的 layout")
        p.add_argument("--style-card", help="风格卡 JSON 或模板 pptx")

    g = sub.add_parser("gen", help="不调模型：打印提示词并 exit 2")
    diag_args(g)
    g.add_argument("-o", required=True, help="期望写出的 SVG 路径（请助手写入）")
    f = sub.add_parser("fix", help="不调模型：打印修补提示并 exit 2")
    f.add_argument("svg")
    diag_args(f)
    f.add_argument("-o", required=True)
    pr = sub.add_parser("prompt")
    diag_args(pr)
    c = sub.add_parser("check")
    c.add_argument("svg")
    c.add_argument("--style", choices=styles)
    c.add_argument("--brief")
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

    diag = _load_diag(getattr(args, "brief", None))
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
    prompt = build_prompt(diag, *canvas_for(diag["bbox"], diag.get("canvas_width", 1200)), palette)
    if args.cmd == "prompt":
        print(prompt)
        return
    # gen / fix
    print("pptx-unit 不调用外部模型。请助手按下列提示词写 SVG 到:", args.o)
    if args.cmd == "fix":
        print("\n── 上一版 SVG 路径 ──\n", args.svg)
        print("\n── 当前 problems ──")
        old = Path(args.svg).read_text(encoding="utf-8")
        print(json.dumps(check_diagram(old, diag), ensure_ascii=False, indent=1))
        print("\n参考 prompts/diagram/fix_svg.md\n")
    else:
        print("\n参考 prompts/diagram/generate_svg.md\n")
    print(prompt)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
