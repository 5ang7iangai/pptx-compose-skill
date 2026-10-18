# -*- coding: utf-8 -*-
"""页与形状的小改动，一个命令一种操作，都不覆盖原件。

    python scripts/slides.py clone          稿.pptx -o 新.pptx --clone 5 [--clone 6] [--before 9]
    python scripts/slides.py delete         稿.pptx -o 新.pptx --slide 7
    python scripts/slides.py move           稿.pptx -o 新.pptx --slide 7 --before 3
    python scripts/slides.py add-page       稿.pptx -o 新.pptx --clone 5
    python scripts/slides.py add-chapter    稿.pptx -o 新.pptx --title "四、材料编制" --anchor "三、" --divider 3 --pages 5,6
    python scripts/slides.py add-toc-label  稿.pptx -o 新.pptx --title "四、材料编制" --anchor "三、"
    python scripts/slides.py fill           稿.pptx -o 新.pptx --map 替换.json
    python scripts/slides.py delete-shapes  稿.pptx -o 新.pptx --slide 4 --match 旧图注
    python scripts/slides.py duplicate-shape 稿.pptx -o 新.pptx --slide 4 --match 要点 --dy 0.4
    python scripts/slides.py move-shape     稿.pptx -o 新.pptx --slide 4 --match 要点 --x 1 --y 2
    python scripts/slides.py pack           解包目录或稿.pptx -o 新.pptx

克隆时 --before 缺省：有致谢页插在致谢页前，否则末尾。页码一律按当前稿。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pptkit.fill import apply_map
from pptkit.ooxml import clone_slide, delete_slide, find_ending_index, load_pptx, move_slide, require_different, save_pptx, slide_order
from pptkit.slides import add_toc_label, delete_matching, duplicate_matching, move_matching


def _parts_from_dir(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _clone_many(parts, sources: list[int], before: int | None = None) -> list[dict]:
    created = []
    for source in sources:
        at = before if before is not None else find_ending_index(parts)
        created.append({"from": source, "index": clone_slide(parts, source, at)})
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="复制/删除/移动页，加页加章，填字，改形状，打包")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def cmd(name, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("pptx", help="稿件 pptx（pack 时也可以是解包目录）")
        p.add_argument("-o", "--output", required=True)
        return p

    p = cmd("clone", "复制页")
    p.add_argument("--clone", type=int, action="append", required=True, help="按当前序号复制，可重复")
    p.add_argument("--before", type=int, help="插入到该序号之前")
    p = cmd("delete", "删页")
    p.add_argument("--slide", type=int, required=True)
    p = cmd("move", "移页")
    p.add_argument("--slide", type=int, required=True)
    p.add_argument("--before", type=int, required=True)
    p = cmd("add-page", "按样例页加一页（插在致谢页前）")
    p.add_argument("--clone", type=int, required=True)
    p = cmd("add-chapter", "加一章：扉页 + 正文页 + 目录条目（只克隆，不填字不出图；要出图用 add_chapter.py）")
    p.add_argument("--title", required=True)
    p.add_argument("--anchor", required=True, help="目录上已有的章节文字，用来复制样式")
    p.add_argument("--divider", type=int, help="章节扉页样例序号")
    p.add_argument("--pages", required=True, help="正文样例序号，逗号分隔，按此顺序克隆")
    p = cmd("add-toc-label", "目录加一条")
    p.add_argument("--title", required=True)
    p.add_argument("--anchor", required=True)
    p = cmd("fill", "按文字槽替换文字，保留首段字体颜色")
    p.add_argument("--map", required=True, help='替换 JSON：{"slides": [{"slide": 3, "replacements": [...]}]}')
    p = cmd("delete-shapes", "删掉含某段文字的形状")
    p.add_argument("--slide", type=int, required=True)
    p.add_argument("--match", required=True)
    p = cmd("duplicate-shape", "复制含某段文字的形状并平移")
    p.add_argument("--slide", type=int, required=True)
    p.add_argument("--match", required=True)
    p.add_argument("--dx", type=float, default=0)
    p.add_argument("--dy", type=float, default=0.4)
    p = cmd("move-shape", "把含某段文字的形状移到指定位置（英寸）")
    p.add_argument("--slide", type=int, required=True)
    p.add_argument("--match", required=True)
    p.add_argument("--x", type=float, required=True)
    p.add_argument("--y", type=float, required=True)
    cmd("pack", "把解包目录或 pptx 重新打包")
    args = parser.parse_args()

    src, dest = Path(args.pptx), Path(args.output)
    if args.cmd == "pack" and src.is_dir():
        parts = _parts_from_dir(src)
    else:
        require_different(src, dest)
        parts = load_pptx(src)
    result: dict = {"output": str(dest)}
    if args.cmd == "clone":
        result["created"] = _clone_many(parts, args.clone, args.before)
    elif args.cmd == "delete":
        delete_slide(parts, args.slide)
    elif args.cmd == "move":
        move_slide(parts, args.slide, args.before)
    elif args.cmd == "add-page":
        result["created"] = _clone_many(parts, [args.clone])
    elif args.cmd == "add-chapter":
        sources = ([args.divider] if args.divider else []) + [int(n) for n in args.pages.split(",") if n.strip()]
        created = _clone_many(parts, sources)
        result["created"] = created
        result["toc"] = add_toc_label(parts, args.title, args.anchor, created[0]["index"] if args.divider else None)
    elif args.cmd == "add-toc-label":
        result["toc"] = add_toc_label(parts, args.title, args.anchor)
    elif args.cmd == "fill":
        result["notes"] = apply_map(parts, json.loads(Path(args.map).read_text(encoding="utf-8")))
    elif args.cmd == "delete-shapes":
        result["removed"] = delete_matching(parts, args.slide, args.match)
    elif args.cmd == "duplicate-shape":
        duplicate_matching(parts, args.slide, args.match, args.dx, args.dy)
    elif args.cmd == "move-shape":
        move_matching(parts, args.slide, args.match, args.x, args.y)
    if "[Content_Types].xml" not in parts:
        raise SystemExit("缺少 [Content_Types].xml")
    save_pptx(dest, parts)
    result["slide_count"] = len(slide_order(parts))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
