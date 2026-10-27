# -*- coding: utf-8 -*-
"""加一章：克隆 → 目录 → 填字 → 删旧图 → 应用已有 SVG → 出两份 pptx。

    python scripts/add_chapter.py 模板.pptx -o 编制.pptx --spec 章节.json [--svg-dir DIR]

交给用户的只有两份 pptx。SVG 须由助手预先写好（见 prompts/diagram/）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from diagram.catalog import bind_styles
from diagram.palette import palette_from
from diagram.pipeline import VARIANTS, deck_font, figure_dir, finish, make_job, prepare_svgs, resolve_diagram, variant_path
from pptkit.fill import apply_map
from pptkit.ooxml import clone_slide, find_ending_index, load_pptx, require_different
from pptkit.profile import analyze
from pptkit.shapes import remove_content_pics
from pptkit.slides import add_toc_label


def run(src: Path, dest: Path, spec: dict, svg_dir: Path | None = None) -> dict:
    parts = load_pptx(src)
    result: dict = {}

    sources = ([spec["divider"]] if spec.get("divider") else []) + list(spec["pages"])
    created = [{"from": s, "index": clone_slide(parts, s, find_ending_index(parts))} for s in sources]
    result["created"] = created
    divider_index = created[0]["index"] if spec.get("divider") else None
    result["toc"] = add_toc_label(parts, spec["title"], spec["anchor"], divider_index)

    content_pages = [c["index"] for c in created[1 if spec.get("divider") else 0:]]
    fig_dir = figure_dir(dest)
    fill_slides, jobs, removed = [], [], 0
    for page_idx, page in zip(content_pages, spec.get("slides") or []):
        if page.get("replacements"):
            fill_slides.append({"slide": page_idx, "replacements": page["replacements"]})
        if page.get("remove_pics"):
            removed += remove_content_pics(parts, page_idx)
        diag = resolve_diagram(spec, page)
        if diag:
            jobs.append(make_job(fig_dir, page_idx, page_idx, diag, page.get("regen", False)))
    if fill_slides:
        result["fill_notes"] = apply_map(parts, {"slides": fill_slides})
    result["pics_removed"] = removed

    try:
        bind_styles([j["diagram"] for j in jobs])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    card = analyze(src)
    prepare_svgs(jobs, palette_from(card), svg_dir=svg_dir)
    return finish(parts, jobs, dest, deck_font(card), result, (card.get("fonts") or {}).get("roles"))


def main() -> None:
    parser = argparse.ArgumentParser(description="加一章；结构图 SVG 须已由助手写好")
    parser.add_argument("pptx")
    parser.add_argument("-o", "--output", required=True, help="基准文件名，实际写出 -图片版 / -可编辑版 两份")
    parser.add_argument("--spec", required=True, help="章节规格 JSON")
    parser.add_argument("--svg-dir", help="已有 SVG 目录；缺省用 <output>-图/")
    args = parser.parse_args()

    src, dest = Path(args.pptx), Path(args.output)
    for tag in VARIANTS:
        require_different(src, variant_path(dest, tag))
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    result = run(src, dest, spec, Path(args.svg_dir) if args.svg_dir else None)
    print(json.dumps(result, ensure_ascii=False, default=str, indent=1))


if __name__ == "__main__":
    main()
