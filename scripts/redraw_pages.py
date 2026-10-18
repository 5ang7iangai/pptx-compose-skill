# -*- coding: utf-8 -*-
"""重做现稿里指定页的结构图：清掉图区里的旧形状/旧图，由大模型出 SVG，写出图片版、可编辑版两份 pptx。

    python scripts/redraw_pages.py 原稿.pptx -o 编制.pptx --spec 重做.json [--regen] [--fix]

spec 字段见 docs/spec.md「重做原稿」一节，按当次原稿填写。
页码一律写原稿页码。交给用户的只有两版 pptx；`-图/` 在写完后删除。
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


def run(src: Path, dest: Path, spec: dict, config: Path | None = None,
        regen: bool = False, fix: bool = False) -> dict:
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
    prepare_svgs(jobs, palette_from(card), config, regen, fix)
    return finish(parts, jobs, dest, deck_font(card), result, (card.get("fonts") or {}).get("roles"))


def main() -> None:
    parser = argparse.ArgumentParser(description="重做指定页的结构图，出图片版、可编辑版两份 pptx")
    parser.add_argument("pptx")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--config", help="大模型配置；缺省按 common/paths.py 的顺序查找")
    parser.add_argument("--regen", action="store_true", help="忽略已有 SVG，重新调用大模型")
    parser.add_argument("--fix", action="store_true", help="已有 SVG 有审阅意见或没过检查时，交给大模型在原图上修补")
    args = parser.parse_args()
    src, dest = Path(args.pptx), Path(args.output)
    for tag in VARIANTS:
        require_different(src, variant_path(dest, tag))
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    result = run(src, dest, spec, args.config, args.regen, args.fix)
    print(json.dumps(result, ensure_ascii=False, default=str, indent=1))


if __name__ == "__main__":
    main()
