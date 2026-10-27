# -*- coding: utf-8 -*-
"""核对版式、风格、配对，以及页纲提示和图库是否都认这些预置。

    python scripts/check_presets.py

有输出就先补预置，再出图。技能包暂无图库重建脚本；改 catalog 后请手改 catalog/图库.html，或跳过图库同步。
"""

from __future__ import annotations

import sys
from pathlib import Path

from layout_policy import TYPE_LAYOUT
from diagram.catalog import layout_ids, pairing, preset_gaps, style_ids

ROOT = Path(__file__).resolve().parents[1]


def gaps() -> list[str]:
    issues = list(preset_gaps())
    layouts = set(layout_ids())
    for key, lid in TYPE_LAYOUT.items():
        if lid not in layouts:
            issues.append(f"TYPE_LAYOUT 的 {key} 指向不存在的版式 {lid}")
    outline = (ROOT / "prompts" / "text" / "outline_pages.md").read_text(encoding="utf-8")
    covered = {lid for key, lid in TYPE_LAYOUT.items() if key in outline}
    missing = [lid for lid in dict.fromkeys(TYPE_LAYOUT.values()) if lid not in covered]
    if missing:
        issues.append("outline_pages.md 没写到这些版式对应的图形类型：" + "、".join(missing))
    gallery = ROOT / "catalog" / "图库.html"
    if gallery.exists():
        text = gallery.read_text(encoding="utf-8")
        absent = [sid for sid in style_ids() if sid not in text] + [lid for lid in layout_ids() if lid not in text]
        if absent:
            issues.append("图库.html 还没有：" + "、".join(absent) + "。请手改 catalog/图库.html（暂无 build_gallery 脚本）")
        paired = [lid for lid in pairing()["layouts"] if lid not in text]
        if paired:
            issues.append("图库的配对表还没有这些版式：" + "、".join(paired))
    else:
        issues.append("没有 catalog/图库.html。请新建或从现有风格/版式手写对照页（暂无 build_gallery 脚本）")
    return issues


def main() -> None:
    found = gaps()
    if not found:
        print("预置对齐：版式、风格、配对、页纲提示、图库")
        return
    for item in found:
        print(item)
    sys.exit(1)


if __name__ == "__main__":
    main()
