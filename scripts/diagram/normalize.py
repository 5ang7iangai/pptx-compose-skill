"""从大模型返回里取出 SVG 并规整：箭头统一成标准三角、补白底。"""

from __future__ import annotations

import re

from lxml import etree

from .svg_parse import SVG_NS, _local, _num


def drop_comments(svg: str) -> str:
    """模型常在注释里写命令行参数（--until），XML 注释不许含 --，解析会失败；注释对出图没用，一律删。"""
    return re.sub(r"<!--.*?-->", "", svg, flags=re.S)


def extract_svg(raw: str) -> str:
    m = re.search(r"```(?:svg|xml|html)?\s*\n(.*?)```", raw, re.S)
    body = drop_comments(m.group(1) if m else raw)
    start = body.find("<svg")
    end = body.rfind("</svg>")
    if start < 0 or end < 0:
        raise ValueError("返回里没有完整的 <svg>")
    return normalize_svg(body[start:end + 6])


def normalize_svg(svg: str) -> str:
    """箭头一律换成朝右的标准三角，由 orient=auto 转向，与可编辑版的 PPT 三角箭头一致；
    没有铺满画布的底色时补一块白底，否则图片版是白底、可编辑版透出母版底纹。"""
    try:
        root = etree.fromstring(svg.encode("utf-8"))
    except etree.XMLSyntaxError:
        return svg
    vb = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if v]
    if len(vb) == 4:
        covered = any(
            _num(r.get("width")) >= vb[2] * 0.95 and _num(r.get("height")) >= vb[3] * 0.95
            and (r.get("fill") or "#000000").lower() not in ("none", "transparent")
            for r in root.xpath("//*[local-name()='rect']")
        )
        if not covered:
            bg = etree.Element(f"{{{SVG_NS}}}rect", x=str(vb[0]), y=str(vb[1]),
                               width=str(vb[2]), height=str(vb[3]), fill="#FFFFFF")
            defs = [i for i, ch in enumerate(root) if _local(ch.tag) == "defs"]
            root.insert(defs[-1] + 1 if defs else 0, bg)
    for mk in root.xpath("//*[local-name()='marker']"):
        color = "#000000"
        for ch in mk.iter():
            fill = ch.get("fill") or ch.get("stroke")
            if fill and fill.startswith("#"):
                color = fill
                break
        for ch in list(mk):
            mk.remove(ch)
        for k in list(mk.attrib):
            if k not in ("id",):
                del mk.attrib[k]
        # 箭头头部随线宽放大，粗线（≥2）时封顶到约 2.6 倍线宽，否则 8 粗的线会顶出 48 的大三角
        ref = f"url(#{mk.get('id')})"
        widths = [_num(el.get("stroke-width"), 1) for el in root.iter()
                  if ref in (el.get("marker-end") or "", el.get("marker-start") or "")]
        sw = max(widths, default=1)
        size = 6 if sw <= 1.75 else max(10.5, 2.6 * sw) / sw
        mk.attrib.update({"viewBox": "0 0 10 10", "refX": "9", "refY": "5", "markerWidth": f"{size:.2f}",
                          "markerHeight": f"{size:.2f}", "orient": "auto-start-reverse", "markerUnits": "strokeWidth"})
        etree.SubElement(mk, f"{{{SVG_NS}}}path", d="M 0 0 L 10 5 L 0 10 z", fill=color)
    return etree.tostring(root, encoding="unicode")
