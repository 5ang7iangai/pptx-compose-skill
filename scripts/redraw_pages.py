# -*- coding: utf-8 -*-
"""重做现稿里指定页的结构图：清掉图区旧形状/旧图，应用助手写好的 SVG，写出两份 pptx。

    python scripts/redraw_pages.py 原稿.pptx -o 编制.pptx --spec 重做.json [--svg-dir DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from diagram.catalog import bind_styles
from diagram.palette import palette_from
from diagram.pipeline import VARIANTS, deck_font, figure_dir, finish, make_job, prepare_svgs, resolve_diagram, variant_path
from pptkit.ooxml import delete_slide, load_pptx, require_different, slide_order
from pptkit.profile import analyze
from pptkit.shapes import clear_region, resize_shapes


def run(src: Path, dest: Path, spec: dict, svg_dir: Path | None = None) -> dict:
    parts = load_pptx(src)
    total = len(slide_order(parts))
    keep = spec.get("keep_slides") or list(range(1, total + 1))
    result: dict = {"cleared": {}}

    for s in spec["slides"]:
        diag = s.get("diagram")
        result["cleared"][s["slide"]] = clear_region(
            parts, s["slide"], s.get("clear", "bbox"), diag["bbox"] if diag else {}, s.get("keep_match") or [])
        if s.get("resize"):
            resize_shapes(parts, s["slide"], s["resize"])

    for idx in sorted(set(range(1, total + 1)) - set(keep), reverse=True):
        delete_slide(parts, idx)
    new_index = {old: i + 1 for i, old in enumerate(sorted(keep))}

    fig_dir = figure_dir(dest)
    jobs = []
    for s in spec["slides"]:
        diag = resolve_diagram(spec, s)
        if diag:
            jobs.append(make_job(fig_dir, new_index[s["slide"]], s["slide"], diag, s.get("regen", False)))

    try:
        bind_styles([j["diagram"] for j in jobs])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    card = analyze(src)
    prepare_svgs(jobs, palette_from(card), svg_dir=svg_dir)
    return finish(parts, jobs, dest, deck_font(card), result, (card.get("fonts") or {}).get("roles"))


def main() -> None:
    parser = argparse.ArgumentParser(description="重做指定页结构图；SVG 须已由助手写好")
    parser.add_argument("pptx")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--svg-dir", help="已有 SVG 目录")
    args = parser.parse_args()
    src, dest = Path(args.pptx), Path(args.output)
    for tag in VARIANTS:
        require_different(src, variant_path(dest, tag))
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    result = run(src, dest, spec, Path(args.svg_dir) if args.svg_dir else None)
    print(json.dumps(result, ensure_ascii=False, default=str, indent=1))


if __name__ == "__main__":
    main()
