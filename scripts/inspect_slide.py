# -*- coding: utf-8 -*-
"""列出页上顶层形状的类型、位置（英寸）和文字，写重做 spec 的 bbox / keep_match / resize 时用。

    python scripts/inspect_slide.py 稿.pptx 4 5 13
"""

import argparse
from pathlib import Path

from pptkit.ooxml import P, _local, load_pptx, parse, q, shape_text, slide_order
from pptkit.shapes import top_box


def main() -> None:
    ap = argparse.ArgumentParser(description="列出页上顶层形状")
    ap.add_argument("pptx")
    ap.add_argument("pages", nargs="+", type=int)
    args = ap.parse_args()
    parts = load_pptx(Path(args.pptx))
    order = slide_order(parts)
    for n in args.pages:
        root = parse(parts[order[n - 1]["part"]])
        print(f"== 第 {n} 页")
        for el in root.find(q(P, "cSld")).find(q(P, "spTree")):
            tag = _local(el.tag)
            if tag in ("nvGrpSpPr", "grpSpPr"):
                continue
            box = top_box(el)
            box = tuple(round(v, 2) for v in box) if box else None
            ph = " ph" if el.find(f".//{q(P, 'ph')}") is not None else ""
            print(f"  {tag:12}{ph} {box} {shape_text(el)[:30]!r}")


if __name__ == "__main__":
    main()
