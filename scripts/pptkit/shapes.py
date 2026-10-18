"""页内形状操作：清掉图区旧形状、删正文区图片、按文字定位改尺寸。坐标一律英寸。"""

from __future__ import annotations

from .ooxml import A, EMU, P, _box_of, _local, _own_xfrm, dump, parse, q, shape_text, slide_order

SHAPE_TAGS = ("sp", "grpSp", "cxnSp", "pic", "graphicFrame")


def _tree(parts: dict, index: int):
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    return part, root, root.find(q(P, "cSld")).find(q(P, "spTree"))


def top_box(el) -> tuple | None:
    x = el.find(q(P, "xfrm")) if _local(el.tag) == "graphicFrame" else _own_xfrm(el)
    b = _box_of(x)
    return tuple(v / EMU for v in b) if b else None


def remove_content_pics(parts: dict[str, bytes], slide_index: int, y_threshold: float = 2.0) -> int:
    """删除指定页正文区（上沿低于 y_threshold 英寸）的图片，页眉标识不动。"""
    part, root, _ = _tree(parts, slide_index)
    removed = 0
    for pic in list(root.iter(q(P, "pic"))):
        off = pic.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}/{q(A, 'off')}")
        if off is not None and int(off.get("y", 0)) / EMU > y_threshold:
            pic.getparent().remove(pic)
            removed += 1
    parts[part] = dump(root)
    return removed


def _content_panel(el, slide_w: float, slide_h: float) -> bool:
    """没字、几乎通栏、从标题下铺到页脚上的大底框，是正文背景，不是旧图。"""
    if _local(el.tag) != "sp" or shape_text(el).strip():
        return False
    b = top_box(el)
    if not b:
        return False
    _x, y, w, h = b
    return w >= slide_w * 0.7 and h >= slide_h * 0.45 and y <= slide_h * 0.35


def clear_region(parts: dict, index: int, mode: str, bbox: dict, keep_match: list[str]) -> int:
    """mode="all" 清掉页上所有带位置的顶层形状；"bbox" 只清中心落在 bbox 里的。标题占位符、含 keep_match 文字的、正文大底框不动。"""
    part, root, tree = _tree(parts, index)
    sz = parse(parts["ppt/presentation.xml"]).find(q(P, "sldSz"))
    slide_w, slide_h = int(sz.get("cx")) / EMU, int(sz.get("cy")) / EMU
    removed = 0
    for el in list(tree):
        if _local(el.tag) not in SHAPE_TAGS:
            continue
        if el.find(f".//{q(P, 'ph')}") is not None and _local(el.tag) == "sp":
            continue  # 标题等占位符
        text = shape_text(el)
        if any(k in text for k in keep_match):
            continue
        if mode == "bbox" and _content_panel(el, slide_w, slide_h):
            continue
        b = top_box(el)
        if b is None:
            continue
        if mode == "bbox":
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            if not (bbox["x"] <= cx <= bbox["x"] + bbox["w"] and bbox["y"] <= cy <= bbox["y"] + bbox["h"]):
                continue
        tree.remove(el)
        removed += 1
    parts[part] = dump(root)
    return removed


def resize_shapes(parts: dict, index: int, rules: list[dict]) -> None:
    """rules: [{"match": 文字, "x"/"y"/"w"/"h": 英寸}]，每条改第一个含该文字的顶层形状。"""
    part, root, tree = _tree(parts, index)
    for rule in rules:
        for el in tree:
            if rule["match"] in shape_text(el):
                xfrm = _own_xfrm(el)
                off, ext = xfrm.find(q(A, "off")), xfrm.find(q(A, "ext"))
                for key, node, attr in (("x", off, "x"), ("y", off, "y"), ("w", ext, "cx"), ("h", ext, "cy")):
                    if key in rule:
                        node.set(attr, str(int(rule[key] * EMU)))
                break
    parts[part] = dump(root)
