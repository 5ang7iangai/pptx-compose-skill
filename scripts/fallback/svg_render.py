# -*- coding: utf-8 -*-
"""把 draw_diagram.Canvas 的数据画成 SVG。

不单独定义一套图形规则：形状、位置、颜色、字号、换行全部来自同一个
Canvas 对象——先跑 layout_*() 填出 canvas.shapes / canvas.links，
draw_diagram.draw() 既用它生成 PPT 形状，也可以调这个模块把同一份
数据画成 SVG。两份文件因此不会互相走样，不是手写两遍再对着改。

本模块不导入 draw_diagram，避免循环引用；side_point 的算法在两处
各存一份，是因为它只有 8 行且不会单独演化。
"""

from __future__ import annotations

PX_PER_IN = 96


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _side_point(shape: dict, idx: int) -> tuple[float, float]:
    x, y, w, h = shape["x"], shape["y"], shape["w"], shape["h"]
    if idx == 0:
        return x + w / 2, y
    if idx == 1:
        return x, y + h / 2
    if idx == 2:
        return x + w / 2, y + h
    return x + w, y + h / 2


def _shape_tag(prst: str, x: float, y: float, w: float, h: float) -> tuple[str, dict]:
    """x/y/w/h 已经是像素。返回 (标签名, 属性字典)。"""
    if prst == "ellipse":
        return "ellipse", {"cx": round(x + w / 2, 1), "cy": round(y + h / 2, 1), "rx": round(w / 2, 1), "ry": round(h / 2, 1)}
    if prst == "diamond":
        pts = f"{x + w/2:.1f},{y:.1f} {x+w:.1f},{y+h/2:.1f} {x+w/2:.1f},{y+h:.1f} {x:.1f},{y+h/2:.1f}"
        return "polygon", {"points": pts}
    if prst == "chevron":
        notch = w * 0.22
        pts = (
            f"{x:.1f},{y:.1f} {x+w-notch:.1f},{y:.1f} {x+w:.1f},{y+h/2:.1f} "
            f"{x+w-notch:.1f},{y+h:.1f} {x:.1f},{y+h:.1f} {x+notch:.1f},{y+h/2:.1f}"
        )
        return "polygon", {"points": pts}
    if prst == "roundRect":
        r = round(min(w, h) * 0.12, 1)
        return "rect", {"x": round(x, 1), "y": round(y, 1), "width": round(w, 1), "height": round(h, 1), "rx": r, "ry": r}
    return "rect", {"x": round(x, 1), "y": round(y, 1), "width": round(w, 1), "height": round(h, 1)}


def render_svg(canvas, box: dict, bg: str = "FFFFFF", pad: float = 0.15) -> str:
    """canvas 是已经跑过某个 layout_*() 的 draw_diagram.Canvas 实例。"""
    ox, oy = box["x"] - pad, box["y"] - pad
    width = box["w"] + pad * 2
    height = box["h"] + pad * 2

    def X(v: float) -> float:
        return (v - ox) * PX_PER_IN

    def Y(v: float) -> float:
        return (v - oy) * PX_PER_IN

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{round(width * PX_PER_IN)}" '
        f'height="{round(height * PX_PER_IN)}" viewBox="0 0 {round(width*PX_PER_IN)} {round(height*PX_PER_IN)}" '
        f'font-family="{_esc(canvas.font)}, Microsoft YaHei, sans-serif">',
        f'<rect x="0" y="0" width="100%" height="100%" fill="#{bg}"/>',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">'
        f'<path d="M0,0 L6,3 L0,6 Z" fill="#{canvas.line}"/></marker></defs>',
    ]

    shape_map = {s["id"]: s for s in canvas.shapes}
    for link in canvas.links:
        src = shape_map.get(link["src"])
        dst = shape_map.get(link["dst"])
        if not src or not dst:
            continue
        x1, y1 = _side_point(src, link["src_idx"])
        x2, y2 = _side_point(dst, link["dst_idx"])
        out.append(
            f'<line x1="{X(x1):.1f}" y1="{Y(y1):.1f}" x2="{X(x2):.1f}" y2="{Y(y2):.1f}" '
            f'stroke="#{canvas.line}" stroke-width="2" marker-end="url(#arrow)"/>'
        )

    for s in canvas.shapes:
        tag, attrs = _shape_tag(s["prst"], X(s["x"]), Y(s["y"]), s["w"] * PX_PER_IN, s["h"] * PX_PER_IN)
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        out.append(f'<{tag} {attr_str} fill="#{s["fill"]}" stroke="#{s["line"]}" stroke-width="1"/>')
        cx = X(s["x"] + s["w"] / 2)
        cy = Y(s["y"] + s["h"] / 2)
        n = len(s["lines"])
        line_h = s["pt"] * 1.3
        start_y = cy - (n - 1) * line_h / 2
        for i, line in enumerate(s["lines"]):
            ty = start_y + i * line_h + s["pt"] * 0.36
            out.append(
                f'<text x="{cx:.1f}" y="{ty:.1f}" text-anchor="middle" '
                f'font-size="{s["pt"]}" fill="#{s["font_color"]}">{_esc(line)}</text>'
            )

    out.append("</svg>")
    return "\n".join(out)
