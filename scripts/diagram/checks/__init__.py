"""结构图检查：返回问题列表（中文、可直接发回大模型修补），空表示通过。

    structure  SVG 本身：viewBox、允许的元素、不用 class、文字够多
    style      风格硬性要求（catalog/styles/<id>/style.yaml）
    text       字号、行距、出画布、画重、互压
    layout     圆内文字、粗线、空白带、图标、卡片与分区
"""

from __future__ import annotations

import re

from lxml import etree

from ..sizing import font_px
from ..svg_parse import ALLOWED, _local, svg_to_items
from . import layout, text
from .scene import build_scene
from .style import style_problems

LIMIT = 12


def layout_problems(items: list[dict], vw: float, vh: float, limit: int = LIMIT, brief: str | None = None,
                    fonts: dict | None = None) -> list[str]:
    sc = build_scene(items, vw, vh)
    para = text.paragraph_lines(sc.texts)
    out = [
        *text.font_size(sc, para, fonts),
        *layout.stacked_categories(sc),
        *text.paragraph_spacing(sc, para),
        *layout.circles(sc),
        *layout.thick_lines(sc),
        *layout.vertical_gap(sc),
        *text.out_of_canvas(sc),
        *text.duplicates(sc, brief),
        *text.pairs(sc),
        *layout.icons_on_text(sc),
        *layout.text_in_cards(sc),
        *layout.cards_in_zones(sc),
        *layout.icon_overlap(sc),
        *layout.icons_in_cards(sc),
        *layout.peer_equal_widths(sc),
        *layout.card_title_body(sc),
        *layout.contrast_hierarchy(sc),
    ]
    return list(dict.fromkeys(out))[:limit]


def structure_problems(root, width: int | None, height: int | None) -> tuple[list[str], list[float]]:
    problems = []
    vb = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if v]
    if len(vb) != 4:
        problems.append("缺少 viewBox")
    else:
        if vb[0] != 0 or vb[1] != 0:
            problems.append(f"viewBox 必须从 0 0 起，现在是 {vb[0]} {vb[1]}")
        if width and abs(vb[2] - width) > 1 or height and abs(vb[3] - height) > 1:
            problems.append(f"viewBox 应为 0 0 {width} {height}")
    bad = sorted({_local(el.tag) for el in root.iter() if _local(el.tag) and _local(el.tag) not in ALLOWED})
    if bad:
        problems.append("用了不允许的元素：" + "、".join(bad))
    if root.xpath("//*[@class]"):
        problems.append("不要用 class，样式写成属性")
    texts = [el for el in root.iter() if _local(el.tag) == "text"]
    if len(texts) < 6:
        problems.append(f"文字太少（{len(texts)} 行），信息不够")
    return problems, vb


def check_svg(svg: str, width: int | None = None, height: int | None = None, style: str | None = None,
              brief: str | None = None, fonts: dict | None = None) -> list[str]:
    """style 给出时另查该风格的硬性要求；brief 用来判断文字是否画重了；fonts（font_px 的结果）给出时查字号下限。"""
    try:
        root = etree.fromstring(svg.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        return [f"SVG 不是合法 XML：{exc}"]
    problems, vb = structure_problems(root, width, height)
    if len(vb) == 4:
        items = svg_to_items(svg)
        if style:
            problems.extend(style_problems(root, items, style, vb[2], vb[3]))
        problems.extend(layout_problems(items, vb[2], vb[3], brief=brief, fonts=fonts))
    return problems


def check_diagram(svg: str, diag: dict) -> list[str]:
    """按 diagram 的风格、图意和字号要求检查。"""
    fonts = font_px(diag) if diag.get("bbox") else None
    return check_svg(svg, style=diag.get("style"), brief=diag.get("brief"), fonts=fonts)
