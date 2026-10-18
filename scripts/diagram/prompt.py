"""拼出图提示词：prompts/diagram/generate_svg.md + 风格规则 + 版式规则 + 风格范例，再填字号、色板等占位符。"""

from __future__ import annotations

import math

from common.paths import PROMPTS

from . import catalog
from .sizing import font_px

TEMPLATE = PROMPTS / "diagram" / "generate_svg.md"


def build_prompt(diag: dict, width: int, height: int, palette: dict, with_example: bool = True) -> str:
    """with_example=False 用于修补轮：上一版 SVG 已体现风格，不再附风格范例。"""
    width_in = diag["bbox"]["w"]
    fp = font_px(diag, width)
    pt_per_px = fp["pt_per_px"]
    style = diag.get("style") or catalog.DEFAULT_STYLE
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("{style_rules}", catalog.style_rules(style))
    layout = diag.get("layout")
    layout_text = (
        "- **这张图的版式**（结构按下面执行，颜色和线条仍按上面的风格）：\n\n"
        + catalog.layout_rules(layout) + "\n"
        if layout else ""
    )
    text = text.replace("{layout_rules}", layout_text)
    ex = catalog.style_example(style) if with_example else ""
    example = (
        "═══ 范例（同一风格，只学元素用法和气质，不抄内容和尺寸，颜色以上面色板为准） ═══\n\n```svg\n"
        + ex + "\n```"
        if ex else ""
    )
    values = {
        "page_role": diag.get("page_role", ""),
        "title": diag.get("title") or diag.get("name", ""),
        "brief": diag["brief"],
        "width": str(width),
        "height": str(height),
        "width_in": f"{width_in:.1f}",
        "pt_per_px": f"{pt_per_px:.2f}",
        "body_font": str(math.ceil(fp["body"])),
        "body_pt": f"{fp['pt']['body']:g}",
        "title_font": str(math.ceil(fp["title"])),
        "label_font": str(math.ceil(fp["label"])),
        "note_font": str(math.ceil(fp["note"])),
        "line_gap": str(math.ceil(fp["body"] * 1.5)),
        "example": example,
        **{k: "#" + v for k, v in palette.items()},
    }
    for key, val in values.items():
        text = text.replace("{" + key + "}", val)
    return text
