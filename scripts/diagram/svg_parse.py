"""把 SVG 展开成按绘制顺序排列的图元：矩形、椭圆、直线、路径、文字（坐标仍是 SVG 画布单位）。

检查（checks）和转 PPT 形状（to_ooxml）都基于这里的图元，两边看到的是同一份数据。
"""

from __future__ import annotations

import math
import re

from lxml import etree

from pptkit.ooxml import q


SVG_NS = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"


ALLOWED = {
    "svg", "g", "defs", "rect", "circle", "ellipse", "line", "path", "polygon", "polyline",
    "text", "tspan", "use", "marker", "filter", "feDropShadow", "title", "desc",
}
INHERIT = ("fill", "stroke", "stroke-width", "font-size", "font-weight", "text-anchor",
           "opacity", "fill-opacity", "stroke-opacity", "stroke-linecap", "stroke-dasharray", "dominant-baseline",
           "font-family", "filter")


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


def _mul(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _parse_transform(text: str | None) -> Matrix:
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        nums = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args)]
        if name == "translate":
            m = _mul(m, (1, 0, 0, 1, nums[0], nums[1] if len(nums) > 1 else 0))
        elif name == "scale":
            sx = nums[0]
            m = _mul(m, (sx, 0, 0, nums[1] if len(nums) > 1 else sx, 0, 0))
        elif name == "matrix" and len(nums) == 6:
            m = _mul(m, tuple(nums))
    return m


def _num(val, default: float = 0.0) -> float:
    if val is None:
        return default
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)", str(val))
    return float(m.group(1)) if m else default


def _color(val: str | None) -> tuple[str | None, float]:
    """返回 (RRGGBB 或 None 表示无, alpha)。"""
    if val is None:
        return None, 1.0
    val = val.strip()
    if val in ("none", "transparent", ""):
        return None, 1.0
    if val.startswith("#"):
        h = val[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return h[:6].upper(), 1.0
    m = re.match(r"rgba?\(([^)]*)\)", val)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        r, g, b = (int(float(p)) for p in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return f"{r:02X}{g:02X}{b:02X}", alpha
    named = {"white": "FFFFFF", "black": "000000", "red": "FF0000", "gray": "808080", "grey": "808080"}
    return named.get(val.lower(), "000000"), 1.0


def _style_attrs(el) -> dict:
    out = {k: v for k, v in el.attrib.items()}
    for decl in (el.get("style") or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip()] = v.strip()
    return out


_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _arc_to_cubic(x1, y1, rx, ry, phi, fa, fs, x2, y2):
    if rx == 0 or ry == 0:
        return [("L", x2, y2)]
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    co = math.sqrt(max(num / den, 0)) if den else 0
    if fa == fs:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dt > 0:
        dt -= 2 * math.pi
    elif fs and dt < 0:
        dt += 2 * math.pi
    segs = max(1, int(math.ceil(abs(dt) / (math.pi / 2))))
    delta = dt / segs
    k = 4 / 3 * math.tan(delta / 4)
    out = []
    for i in range(segs):
        a1 = t1 + i * delta
        a2 = a1 + delta

        def pt(a):
            x, y = rx * math.cos(a), ry * math.sin(a)
            return cp * x - sp * y + cx, sp * x + cp * y + cy

        def dpt(a):
            x, y = -rx * math.sin(a), ry * math.cos(a)
            return cp * x - sp * y, sp * x + cp * y

        p1, p2 = pt(a1), pt(a2)
        d1, d2 = dpt(a1), dpt(a2)
        out.append(("C", p1[0] + k * d1[0], p1[1] + k * d1[1], p2[0] - k * d2[0], p2[1] - k * d2[1], p2[0], p2[1]))
    return out


def parse_path(d: str) -> list[tuple]:
    """转成绝对坐标的 M / L / C / Z 序列。"""
    toks = _TOKEN.findall(d or "")
    out: list[tuple] = []
    i, cmd = 0, None
    x = y = sx = sy = 0.0
    last_c = None

    def nxt():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                out.append(("Z",))
                x, y = sx, sy
                last_c = None
                continue
        if cmd is None:
            break
        rel = cmd.islower()
        c = cmd.upper()
        try:
            if c == "M":
                nx, ny = nxt(), nxt()
                x, y = (x + nx, y + ny) if rel else (nx, ny)
                sx, sy = x, y
                out.append(("M", x, y))
                cmd = "l" if rel else "L"
                last_c = None
            elif c == "L":
                nx, ny = nxt(), nxt()
                x, y = (x + nx, y + ny) if rel else (nx, ny)
                out.append(("L", x, y))
                last_c = None
            elif c == "H":
                nx = nxt()
                x = x + nx if rel else nx
                out.append(("L", x, y))
                last_c = None
            elif c == "V":
                ny = nxt()
                y = y + ny if rel else ny
                out.append(("L", x, y))
                last_c = None
            elif c == "C":
                v = [nxt() for _ in range(6)]
                if rel:
                    v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y, v[4] + x, v[5] + y]
                out.append(("C", *v))
                last_c = (v[2], v[3])
                x, y = v[4], v[5]
            elif c == "S":
                v = [nxt() for _ in range(4)]
                if rel:
                    v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
                c1 = (2 * x - last_c[0], 2 * y - last_c[1]) if last_c else (x, y)
                out.append(("C", c1[0], c1[1], *v))
                last_c = (v[0], v[1])
                x, y = v[2], v[3]
            elif c in "QT":
                if c == "Q":
                    v = [nxt() for _ in range(4)]
                    if rel:
                        v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
                    qx, qy, ex, ey = v
                else:
                    ex, ey = nxt(), nxt()
                    if rel:
                        ex, ey = ex + x, ey + y
                    qx, qy = (2 * x - last_c[0], 2 * y - last_c[1]) if last_c else (x, y)
                out.append(("C", x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                            ex + 2 / 3 * (qx - ex), ey + 2 / 3 * (qy - ey), ex, ey))
                last_c = (qx, qy)
                x, y = ex, ey
            elif c == "A":
                rx, ry, phi, fa, fs, ex, ey = (nxt() for _ in range(7))
                if rel:
                    ex, ey = ex + x, ey + y
                out.extend(_arc_to_cubic(x, y, rx, ry, phi, int(fa), int(fs), ex, ey))
                x, y = ex, ey
                last_c = None
            else:
                i += 1
        except (IndexError, ValueError):
            break
    return out


def _text_width(text: str, size: float, bold: bool = False) -> float:
    """按微软雅黑在浏览器里的实测字宽估算（单位：字号）。"""
    upper, lower, digit = (0.79, 0.59, 0.62) if bold else (0.75, 0.555, 0.59)
    w = 0.0
    for ch in text:
        if ord(ch) > 0x2E80:
            w += size
        elif ch == " ":
            w += size * 0.3
        elif ch.isupper():
            w += size * upper
        elif ch.isdigit():
            w += size * digit
        else:
            w += size * lower
    return w


def _is_bold(st: dict) -> bool:
    return str(st.get("font-weight", "")) in ("bold", "600", "700", "800", "900")


def svg_to_items(svg: str) -> list[dict]:
    """把 SVG 展开成按绘制顺序排列的图元（坐标仍是 SVG 画布单位）。"""
    root = etree.fromstring(svg.encode("utf-8"))
    ids = {el.get("id"): el for el in root.iter() if isinstance(el.tag, str) and el.get("id")}
    items: list[dict] = []
    icon_stack: list[int] = []
    icon_seq = [0]

    def marker_of(ref: str | None) -> bool:
        if not ref:
            return False
        m = re.search(r"#([^)\s]+)", ref)
        return bool(m and m.group(1) in ids)

    def shadow_of(ref: str | None):
        m = re.search(r"#([^)\s]+)", ref or "")
        flt = ids.get(m.group(1)) if m else None
        if flt is None:
            return None
        for ch in flt:
            if _local(ch.tag) == "feDropShadow":
                color, alpha = _color(ch.get("flood-color") or "#000000")
                alpha *= _num(ch.get("flood-opacity"), 1.0)
                return {"dx": _num(ch.get("dx")), "dy": _num(ch.get("dy"), 2),
                        "blur": _num(ch.get("stdDeviation"), 3), "color": color, "alpha": alpha}
        return None

    def paint(st: dict):
        fill, fa = _color(st.get("fill", "#000000"))
        stroke, sa = _color(st.get("stroke"))
        op = _num(st.get("opacity"), 1.0)
        return {
            "fill": fill, "fill_alpha": fa * _num(st.get("fill-opacity"), 1.0) * op,
            "stroke": stroke, "stroke_alpha": sa * _num(st.get("stroke-opacity"), 1.0) * op,
            "stroke_width": _num(st.get("stroke-width"), 1.0) if stroke else 0,
            "round_cap": st.get("stroke-linecap") == "round",
            "dash": (st.get("stroke-dasharray") or "none").strip() != "none",
            "shadow": shadow_of(st.get("filter")),
        }

    def emit_text(el, m: Matrix, st: dict):
        base_x, base_y = _num(el.get("x")), _num(el.get("y")) + _num(el.get("dy"))
        runs = []
        lines = []
        if el.text and el.text.strip():
            runs.append((el.text, st))
        for ch in el:
            if _local(ch.tag) != "tspan":
                continue
            cst = {**st, **{k: v for k, v in _style_attrs(ch).items() if k in INHERIT}}
            if ch.get("x") is not None or ch.get("y") is not None or ch.get("dy") is not None:
                if runs:
                    lines.append((base_x, base_y, runs))
                    runs = []
                base_x = _num(ch.get("x"), base_x)
                base_y = _num(ch.get("y"), base_y) + _num(ch.get("dy"))
            if ch.text:
                runs.append((ch.text, cst))
            if ch.tail and ch.tail.strip():
                runs.append((ch.tail, st))
        if runs:
            lines.append((base_x, base_y, runs))
        # 按 SVG 默认空白规则：换行/制表当空格、连续空格合并、行首尾空格去掉，否则 PPT 里会多出空行
        for k, (lx, ly, rs) in enumerate(lines):
            rs = [(re.sub(r" {2,}", " ", re.sub(r"[\r\n\t]", " ", t)), s) for t, s in rs]
            rs[0] = (rs[0][0].lstrip(), rs[0][1])
            rs[-1] = (rs[-1][0].rstrip(), rs[-1][1])
            lines[k] = (lx, ly, [(t, s) for t, s in rs if t])
        for lx, ly, rs in lines:
            if not rs:
                continue
            text = "".join(t for t, _ in rs)
            if not text.strip():
                continue
            size = _num(st.get("font-size"), 16) * abs(m[0])
            anchor = st.get("text-anchor", "start")
            px, py = _apply(m, lx, ly)
            width = sum(_text_width(t, _num(s.get("font-size"), 16) * abs(m[0]), _is_bold(s)) for t, s in rs)
            if anchor == "middle":
                x0 = px - width / 2
            elif anchor == "end":
                x0 = px - width
            else:
                x0 = px
            baseline = st.get("dominant-baseline", "")
            if baseline in ("middle", "central"):
                top = py - size * 0.66
            elif baseline in ("hanging", "text-before-edge"):
                top = py - size * 0.2
            else:
                top = py - size * 1.06
            items.append({
                "kind": "text", "text": text, "anchor": anchor, "x": px, "y": top,
                "w": width, "h": size * 1.32, "size": size,
                "runs": [{"text": t, "size": _num(s.get("font-size"), 16) * abs(m[0]),
                          "color": _color(s.get("fill", "#000000"))[0] or "000000",
                          "bold": _is_bold(s)}
                         for t, s in rs],
                "box_px": (x0, top, x0 + width, top + size * 1.32),
            })

    def walk(el, m: Matrix, st: dict):
        tag = _local(el.tag)
        if not tag or tag in ("defs", "marker", "filter", "title", "desc", "style"):
            return
        attrs = _style_attrs(el)
        st = {**st, **{k: v for k, v in attrs.items() if k in INHERIT}}
        if tag != "use":
            m = _mul(m, _parse_transform(el.get("transform")))
        if tag in ("svg", "g"):
            for ch in el:
                walk(ch, m, st)
            return
        if tag == "use":
            href = el.get("href") or el.get(q(XLINK, "href")) or ""
            target = ids.get(href.lstrip("#"))
            if target is None:
                return
            mm = _mul(m, _parse_transform(el.get("transform")))
            mm = _mul(mm, (1, 0, 0, 1, _num(el.get("x")), _num(el.get("y"))))
            icon_seq[0] += 1
            icon_stack.append(icon_seq[0])
            start = len(items)
            walk(target, mm, st)
            icon_stack.pop()
            for it in items[start:]:
                it.setdefault("icon", icon_seq[0])
            return
        pt = paint(st)
        if tag == "text":
            emit_text(el, m, st)
            return
        if tag == "rect":
            x, y = _num(el.get("x")), _num(el.get("y"))
            w, h = _num(el.get("width")), _num(el.get("height"))
            if w <= 0 or h <= 0:
                return
            rx = _num(el.get("rx"), _num(el.get("ry")))
            x0, y0 = _apply(m, x, y)
            items.append({"kind": "rect", "x": x0, "y": y0, "w": w * abs(m[0]), "h": h * abs(m[3]),
                          "rx": rx * abs(m[0]), **pt})
            return
        if tag in ("circle", "ellipse"):
            cx, cy = _num(el.get("cx")), _num(el.get("cy"))
            rx = _num(el.get("r")) if tag == "circle" else _num(el.get("rx"))
            ry = _num(el.get("r")) if tag == "circle" else _num(el.get("ry"))
            px, py = _apply(m, cx - rx, cy - ry)
            items.append({"kind": "ellipse", "x": px, "y": py, "w": 2 * rx * abs(m[0]), "h": 2 * ry * abs(m[3]), **pt})
            return
        has_end = marker_of(st.get("marker-end") or attrs.get("marker-end"))
        has_start = marker_of(attrs.get("marker-start"))
        if tag == "line":
            p1 = _apply(m, _num(el.get("x1")), _num(el.get("y1")))
            p2 = _apply(m, _num(el.get("x2")), _num(el.get("y2")))
            items.append({"kind": "line", "p1": p1, "p2": p2, "head": has_start, "tail": has_end, **pt})
            return
        if tag in ("polygon", "polyline"):
            nums = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", el.get("points") or "")]
            pts = list(zip(nums[0::2], nums[1::2]))
            if len(pts) < 2:
                return
            segs = [("M", *pts[0])] + [("L", *p) for p in pts[1:]]
            if tag == "polygon":
                segs.append(("Z",))
            d_segs = segs
        elif tag == "path":
            d_segs = parse_path(el.get("d") or "")
        else:
            return
        if not d_segs:
            return
        abs_segs = []
        for s in d_segs:
            if s[0] == "Z":
                abs_segs.append(s)
                continue
            pts = [_apply(m, s[i], s[i + 1]) for i in range(1, len(s), 2)]
            abs_segs.append((s[0], *[c for p in pts for c in p]))
        moves = [s for s in abs_segs if s[0] != "Z"]
        closed = any(s[0] == "Z" for s in abs_segs)
        if len(moves) == 2 and moves[0][0] == "M" and moves[1][0] == "L" and not closed and pt["fill"] is None:
            items.append({"kind": "line", "p1": moves[0][1:3], "p2": moves[1][1:3],
                          "head": has_start, "tail": has_end, **pt})
            return
        if not closed and tag != "polygon" and st.get("fill") is None:
            pt["fill"] = None
        items.append({"kind": "path", "segs": abs_segs, "head": has_start, "tail": has_end, **pt})

    vb = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "0 0 1 1").strip())]
    base = (1, 0, 0, 1, -vb[0], -vb[1])
    walk(root, base, {"fill": "#000000"})
    return items
