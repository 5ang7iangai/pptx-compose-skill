"""图元 → PPT 原生形状（p:grpSp），用于可编辑版。"""

from __future__ import annotations

import math
import re

from lxml import etree

from pptkit.ooxml import A, P, q

from .svg_parse import svg_to_items


EMU = 914400


class _Mapper:
    def __init__(self, vb_w: float, vb_h: float, bbox: dict):
        bw, bh = bbox["w"] * EMU, bbox["h"] * EMU
        self.s = min(bw / vb_w, bh / vb_h)
        self.ox = bbox["x"] * EMU + (bw - vb_w * self.s) / 2
        self.oy = bbox["y"] * EMU + (bh - vb_h * self.s) / 2

    def x(self, v):
        return int(round(self.ox + v * self.s))

    def y(self, v):
        return int(round(self.oy + v * self.s))

    def d(self, v):
        return max(int(round(v * self.s)), 0)


def _sub(parent, ns, tag, **attrs):
    el = etree.SubElement(parent, q(ns, tag))
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def _solid(parent, color: str, alpha: float = 1.0):
    fill = _sub(parent, A, "solidFill")
    clr = _sub(fill, A, "srgbClr", val=color)
    if alpha < 0.999:
        _sub(clr, A, "alpha", val=int(alpha * 100000))
    return fill


def _nv(sp, tag_nv: str, tag_c: str, sid: int, name: str):
    nv = _sub(sp, P, tag_nv)
    _sub(nv, P, "cNvPr", id=sid, name=name)
    _sub(nv, P, tag_c)
    _sub(nv, P, "nvPr")
    return nv


def _xfrm(sp_pr, x, y, w, h, flip_h=False, flip_v=False):
    xf = _sub(sp_pr, A, "xfrm")
    if flip_h:
        xf.set("flipH", "1")
    if flip_v:
        xf.set("flipV", "1")
    _sub(xf, A, "off", x=x, y=y)
    _sub(xf, A, "ext", cx=max(w, 1), cy=max(h, 1))


def _line_props(sp_pr, it: dict, mp: _Mapper):
    if not it.get("stroke"):
        _sub(sp_pr, A, "ln").append(etree.Element(q(A, "noFill")))
        return
    ln = _sub(sp_pr, A, "ln", w=max(mp.d(it["stroke_width"]), 3175))
    if it.get("round_cap"):
        ln.set("cap", "rnd")
    _solid(ln, it["stroke"], it.get("stroke_alpha", 1.0))
    if it.get("dash"):
        _sub(ln, A, "prstDash", val="dash")
    if it.get("head"):
        _sub(ln, A, "headEnd", type="triangle", w="med", len="med")
    if it.get("tail"):
        _sub(ln, A, "tailEnd", type="triangle", w="med", len="med")


def _effects(sp_pr, it: dict, mp: _Mapper):
    sh = it.get("shadow")
    if not sh:
        return
    eff = _sub(sp_pr, A, "effectLst")
    dist = math.hypot(sh["dx"], sh["dy"])
    ang = int((math.degrees(math.atan2(sh["dy"], sh["dx"])) % 360) * 60000)
    o = _sub(eff, A, "outerShdw", blurRad=mp.d(sh["blur"] * 2), dist=mp.d(dist), dir=ang, algn="t", rotWithShape="0")
    clr = _sub(o, A, "srgbClr", val=sh["color"] or "000000")
    _sub(clr, A, "alpha", val=int(max(min(sh["alpha"], 1), 0) * 100000))


def _empty_text(sp):
    tx = _sub(sp, P, "txBody")
    _sub(tx, A, "bodyPr")
    _sub(tx, A, "lstStyle")
    _sub(tx, A, "p")


def _make_rect(it, sid, mp):
    sp = etree.Element(q(P, "sp"))
    _nv(sp, "nvSpPr", "cNvSpPr", sid, f"图元 {sid}")
    sp_pr = _sub(sp, P, "spPr")
    x, y, w, h = mp.x(it["x"]), mp.y(it["y"]), mp.d(it["w"]), mp.d(it["h"])
    _xfrm(sp_pr, x, y, w, h)
    rx = it.get("rx", 0)
    if rx > 0.5:
        geom = _sub(sp_pr, A, "prstGeom", prst="roundRect")
        av = _sub(geom, A, "avLst")
        adj = min(int(100000 * rx / max(min(it["w"], it["h"]), 1e-6)), 50000)
        _sub(av, A, "gd", name="adj", fmla=f"val {adj}")
    else:
        _sub(_sub(sp_pr, A, "prstGeom", prst="rect"), A, "avLst")
    if it.get("fill"):
        _solid(sp_pr, it["fill"], it.get("fill_alpha", 1.0))
    else:
        sp_pr.append(etree.Element(q(A, "noFill")))
    _line_props(sp_pr, it, mp)
    _effects(sp_pr, it, mp)
    _empty_text(sp)
    return sp


def _make_ellipse(it, sid, mp):
    sp = _make_rect({**it, "rx": 0}, sid, mp)
    geom = sp.find(".//" + q(A, "prstGeom"))
    geom.set("prst", "ellipse")
    return sp


def _make_line(it, sid, mp):
    (x1, y1), (x2, y2) = it["p1"], it["p2"]
    X1, Y1, X2, Y2 = mp.x(x1), mp.y(y1), mp.x(x2), mp.y(y2)
    cxn = etree.Element(q(P, "cxnSp"))
    _nv(cxn, "nvCxnSpPr", "cNvCxnSpPr", sid, f"连接符 {sid}")
    sp_pr = _sub(cxn, P, "spPr")
    _xfrm(sp_pr, min(X1, X2), min(Y1, Y2), abs(X2 - X1), abs(Y2 - Y1), X1 > X2, Y1 > Y2)
    _sub(_sub(sp_pr, A, "prstGeom", prst="straightConnector1"), A, "avLst")
    if not it.get("stroke"):
        it = {**it, "stroke": it.get("fill") or "000000", "stroke_width": it.get("stroke_width") or 1}
    _line_props(sp_pr, it, mp)
    return cxn


def _make_path(it, sid, mp):
    pts = []
    for s in it["segs"]:
        if s[0] != "Z":
            pts.extend((mp.x(s[i]), mp.y(s[i + 1])) for i in range(1, len(s), 2))
    if not pts:
        return None
    min_x, min_y = min(p[0] for p in pts), min(p[1] for p in pts)
    max_x, max_y = max(p[0] for p in pts), max(p[1] for p in pts)
    w, h = max(max_x - min_x, 1), max(max_y - min_y, 1)
    sp = etree.Element(q(P, "sp"))
    _nv(sp, "nvSpPr", "cNvSpPr", sid, f"图元 {sid}")
    sp_pr = _sub(sp, P, "spPr")
    _xfrm(sp_pr, min_x, min_y, w, h)
    geom = _sub(sp_pr, A, "custGeom")
    for tag in ("avLst", "gdLst", "ahLst", "cxnLst"):
        _sub(geom, A, tag)
    _sub(geom, A, "rect", l="l", t="t", r="r", b="b")
    plst = _sub(geom, A, "pathLst")
    path = _sub(plst, A, "path", w=w, h=h)
    if not it.get("fill"):
        path.set("fill", "none")

    def pt_el(parent, i, s):
        _sub(parent, A, "pt", x=mp.x(s[i]) - min_x, y=mp.y(s[i + 1]) - min_y)

    for s in it["segs"]:
        if s[0] == "M":
            pt_el(_sub(path, A, "moveTo"), 1, s)
        elif s[0] == "L":
            pt_el(_sub(path, A, "lnTo"), 1, s)
        elif s[0] == "C":
            cb = _sub(path, A, "cubicBezTo")
            for i in (1, 3, 5):
                pt_el(cb, i, s)
        elif s[0] == "Z":
            _sub(path, A, "close")
    if it.get("fill"):
        _solid(sp_pr, it["fill"], it.get("fill_alpha", 1.0))
    else:
        sp_pr.append(etree.Element(q(A, "noFill")))
    _line_props(sp_pr, it, mp)
    _effects(sp_pr, it, mp)
    _empty_text(sp)
    return sp


def _make_text(it, sid, mp, font: str):
    sp = etree.Element(q(P, "sp"))
    nv = _sub(sp, P, "nvSpPr")
    _sub(nv, P, "cNvPr", id=sid, name=f"文字 {sid}")
    _sub(nv, P, "cNvSpPr", txBox="1")
    _sub(nv, P, "nvPr")
    sp_pr = _sub(sp, P, "spPr")
    pad = it["size"] * 0.3
    w = it["w"] + 2 * pad
    if it["anchor"] == "middle":
        left = it["x"] - w / 2
    elif it["anchor"] == "end":
        left = it["x"] - w + pad
    else:
        left = it["x"] - pad
    _xfrm(sp_pr, mp.x(left), mp.y(it["y"]), mp.d(w), mp.d(it["h"]))
    _sub(_sub(sp_pr, A, "prstGeom", prst="rect"), A, "avLst")
    sp_pr.append(etree.Element(q(A, "noFill")))
    tx = _sub(sp, P, "txBody")
    _sub(tx, A, "bodyPr", wrap="none", lIns=mp.d(pad), tIns=0, rIns=mp.d(pad), bIns=0, anchor="t", rtlCol="0")
    _sub(tx, A, "lstStyle")
    p = _sub(tx, A, "p")
    ppr = _sub(p, A, "pPr", algn={"middle": "ctr", "end": "r"}.get(it["anchor"], "l"))
    _sub(_sub(ppr, A, "lnSpc"), A, "spcPct", val=100000)
    for run in it["runs"]:
        r = _sub(p, A, "r")
        pt = run["size"] * mp.s / 12700
        rpr = _sub(r, A, "rPr", lang="zh-CN", sz=max(int(round(pt * 2)) * 50, 600), b=1 if run["bold"] else 0, dirty="0")
        _solid(rpr, run["color"])
        _sub(rpr, A, "latin", typeface=font)
        _sub(rpr, A, "ea", typeface=font)
        _sub(r, A, "t").text = run["text"]
    return sp


def svg_to_group(svg: str, bbox: dict, start_id: int, font: str = "微软雅黑", name: str = "结构图") -> etree._Element:
    root = etree.fromstring(svg.encode("utf-8"))
    vb = [float(v) for v in re.split(r"[\s,]+", root.get("viewBox").strip())]
    mp = _Mapper(vb[2], vb[3], bbox)
    sid = start_id
    children = []
    for it in svg_to_items(svg):
        sid += 1
        kind = it["kind"]
        if kind == "rect":
            el = _make_rect(it, sid, mp)
        elif kind == "ellipse":
            el = _make_ellipse(it, sid, mp)
        elif kind == "line":
            el = _make_line(it, sid, mp)
        elif kind == "path":
            el = _make_path(it, sid, mp)
        else:
            el = _make_text(it, sid, mp, font)
        if el is not None:
            children.append(el)
    grp = etree.Element(q(P, "grpSp"))
    nv = _sub(grp, P, "nvGrpSpPr")
    _sub(nv, P, "cNvPr", id=sid + 1, name=name)
    _sub(nv, P, "cNvGrpSpPr")
    _sub(nv, P, "nvPr")
    gp = _sub(grp, P, "grpSpPr")
    xf = _sub(gp, A, "xfrm")
    x, y, w, h = int(bbox["x"] * EMU), int(bbox["y"] * EMU), int(bbox["w"] * EMU), int(bbox["h"] * EMU)
    _sub(xf, A, "off", x=x, y=y)
    _sub(xf, A, "ext", cx=w, cy=h)
    _sub(xf, A, "chOff", x=x, y=y)
    _sub(xf, A, "chExt", cx=w, cy=h)
    for el in children:
        grp.append(el)
    return grp
