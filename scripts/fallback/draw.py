# -*- coding: utf-8 -*-
"""在已有页上画七种可编辑结构图，并编成一组。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lxml import etree

from pptkit.ooxml import A, P, R, dump, load_pptx, max_shape_id, parse, q, require_different, save_pptx, slide_order
from pptkit.profile import analyze
from .svg_render import render_svg

# 这是本文件唯一要记住的一句话：
# layout_*() 把 spec 排成 canvas.shapes / canvas.links 这一份数据，
# make_shape()/make_connector() 把它变成 PPT 形状，svg_render.render_svg()
# 把它变成 SVG。两种输出读的是同一份数据，不是分别写了两套画图逻辑。

EMU = 914400


def emu(inches: float) -> int:
    return int(round(inches * EMU))


def luminance(hex6: str) -> float:
    r = int(hex6[0:2], 16)
    g = int(hex6[2:4], 16)
    b = int(hex6[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def font_on(fill: str, dark: str, light: str = "FFFFFF") -> str:
    return light if luminance(fill) < 160 else dark


def wrap_lines(text: str, width_in: float, pt: int) -> list[str]:
    max_w = max(width_in * 0.78, 0.2)
    lines = []
    for para in (text or "").split("\n"):
        cur = ""
        width = 0.0
        for ch in para:
            ch_w = (pt / 72) * (1.0 if ord(ch) > 127 else 0.55)
            if cur and width + ch_w > max_w:
                lines.append(cur)
                cur = ch
                width = ch_w
            else:
                cur += ch
                width += ch_w
        lines.append(cur)
    return lines or [""]


def fit_pt(text: str, width_in: float, height_in: float, max_pt: int = 14, min_pt: int = 9) -> tuple[int, list[str]]:
    """在放得下的字号里，优先少行，并避免只剩一个字的末行。"""
    best: tuple[tuple, int, list[str]] | None = None
    for pt in range(max_pt, min_pt - 1, -1):
        lines = wrap_lines(text, width_in, pt)
        if len(lines) * (pt * 1.25 / 72) > height_in * 0.86:
            continue
        orphan = any(len(line.strip()) <= 1 for line in lines)
        rank = (len(lines), 1 if orphan else 0, -pt)
        if best is None or rank < best[0]:
            best = (rank, pt, lines)
    if best is not None:
        return best[1], best[2]
    return min_pt, wrap_lines(text, width_in, min_pt)


class Canvas:
    def __init__(self, font: str, dark: str, line: str):
        self.font = font
        self.dark = dark
        self.line = line
        self.shapes: list[dict] = []
        self.links: list[dict] = []
        self._n = 1

    def box(self, prst, x, y, w, h, text, fill, max_pt=14) -> int:
        w = max(w, 0.3)
        h = max(h, 0.28)
        pt, lines = fit_pt(text, w, h, max_pt=max_pt)
        self._n += 1
        sid = self._n
        self.shapes.append(
            {
                "id": sid,
                "prst": prst,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "lines": lines,
                "pt": pt,
                "fill": fill,
                "font_color": font_on(fill, self.dark),
                "line": self.line if luminance(fill) > 180 else fill,
            }
        )
        return sid

    def connect(self, src: int, dst: int, src_idx: int, dst_idx: int) -> None:
        self.links.append({"src": src, "dst": dst, "src_idx": src_idx, "dst_idx": dst_idx})


def _by_id(shapes):
    return {s["id"]: s for s in shapes}


def side_point(shape: dict, idx: int) -> tuple[float, float]:
    x, y, w, h = shape["x"], shape["y"], shape["w"], shape["h"]
    if idx == 0:
        return x + w / 2, y
    if idx == 1:
        return x, y + h / 2
    if idx == 2:
        return x + w / 2, y + h
    return x + w, y + h / 2


def layout_pipeline(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    nodes = spec.get("nodes") or []
    if not nodes:
        raise SystemExit("pipeline 需要 nodes")
    mode = spec.get("mode") or "row"
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    gap = 0.12
    ids = {}
    if mode == "hub":
        left = [n for n in nodes if n.get("place") == "left"]
        right = [n for n in nodes if n.get("place") == "right"]
        center = [n for n in nodes if n.get("place") == "center"] or [nodes[0]]
        col_w = (w - 2 * gap) / 3
        c = center[0]
        ids[c.get("id") or "center"] = canvas.box(
            "roundRect", x + col_w + gap, y + h * 0.25, col_w - gap, h * 0.5, c.get("text") or "", colors["dominant"], 16
        )

        def stack(items, left_x):
            if not items:
                return
            bh = min(0.7, (h - gap * (len(items) + 1)) / len(items))
            total = len(items) * bh + (len(items) - 1) * gap
            top = y + (h - total) / 2
            for i, node in enumerate(items):
                ids[node.get("id") or f"n{i}"] = canvas.box(
                    "roundRect", left_x, top + i * (bh + gap), col_w - gap, bh, node.get("text") or "", colors["light"], 12
                )

        stack(left, x)
        stack(right, x + 2 * (col_w + gap))
        cid = ids[c.get("id") or "center"]
        for node in left:
            canvas.connect(ids[node.get("id")], cid, 3, 1)
        for node in right:
            canvas.connect(cid, ids[node.get("id")], 3, 1)
        return
    n = len(nodes)
    bw = (w - gap * (n + 1)) / n
    bh = min(h * 0.55, 1.1)
    top = y + (h - bh) / 2
    prev = None
    for i, node in enumerate(nodes):
        sid = canvas.box(
            "roundRect",
            x + gap + i * (bw + gap),
            top,
            bw,
            bh,
            node.get("text") or "",
            colors["dominant"] if i % 2 == 0 else colors["accent"],
            14,
        )
        ids[node.get("id") or f"n{i}"] = sid
        if prev is not None:
            canvas.connect(prev, sid, 3, 1)
        prev = sid
    for edge in spec.get("edges") or []:
        if edge.get("from") in ids and edge.get("to") in ids and edge.get("from") != edge.get("to"):
            # 顺序连线已经画过，额外连线仍保留
            if abs(list(ids).index(edge["from"]) - list(ids).index(edge["to"])) != 1:
                canvas.connect(ids[edge["from"]], ids[edge["to"]], 3, 1)


def layout_cards_steps(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    cards = spec.get("cards") or []
    steps = spec.get("steps") or []
    results = spec.get("results") or []
    bands = [name for name, items in (("cards", cards), ("steps", steps), ("results", results)) if items]
    if not bands:
        raise SystemExit("cards-steps 至少要有一类内容")
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    gap = 0.1
    band_h = (h - gap * (len(bands) + 1)) / len(bands)
    top = y + gap
    if cards:
        bw = (w - gap * (len(cards) + 1)) / len(cards)
        for i, card in enumerate(cards):
            title = card.get("title") or ""
            body = card.get("body") or ""
            text = title + ("\n" + body if body else "")
            canvas.box("roundRect", x + gap + i * (bw + gap), top, bw, band_h, text, colors["light"], 12)
        top += band_h + gap
    if steps:
        bw = (w - gap * (len(steps) + 1)) / len(steps)
        prev = None
        for i, step in enumerate(steps):
            label = step if isinstance(step, str) else step.get("text") or ""
            sid = canvas.box(
                "roundRect", x + gap + i * (bw + gap), top, bw, band_h, f"{i + 1} {label}", colors["dominant"], 12
            )
            if prev is not None:
                canvas.connect(prev, sid, 3, 1)
            prev = sid
        top += band_h + gap
    if results:
        bw = (w - gap * (len(results) + 1)) / len(results)
        for i, item in enumerate(results):
            label = item if isinstance(item, str) else item.get("text") or ""
            canvas.box("roundRect", x + gap + i * (bw + gap), top, bw, band_h, label, colors["accent"], 12)


def layout_layers(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    layers = spec.get("layers") or []
    if not layers:
        raise SystemExit("layers 需要 layers")
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    gap = 0.08
    rail = min(1.6, w * 0.18)
    band_h = (h - gap * (len(layers) + 1)) / len(layers)
    for i, layer in enumerate(layers):
        top = y + gap + i * (band_h + gap)
        canvas.box("roundRect", x, top, rail, band_h, layer.get("name") or "", colors["dominant"], 12)
        items = layer.get("items") or []
        if not items:
            continue
        inner_x = x + rail + gap
        inner_w = w - rail - gap
        cols = min(len(items), 4 if inner_w > 8 else 3)
        rows = (len(items) + cols - 1) // cols
        cell_h = (band_h - gap * (rows + 1)) / rows
        cell_w = (inner_w - gap * (cols + 1)) / cols
        for j, item in enumerate(items):
            rr, cc = divmod(j, cols)
            canvas.box(
                "roundRect",
                inner_x + gap + cc * (cell_w + gap),
                top + gap + rr * (cell_h + gap),
                cell_w,
                cell_h,
                item if isinstance(item, str) else item.get("text") or "",
                colors["surface"],
                11,
            )


def layout_flowchart(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    nodes = spec.get("nodes") or []
    if not nodes:
        raise SystemExit("flowchart 需要 nodes")
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    for i, node in enumerate(nodes):
        node.setdefault("row", i)
        node.setdefault("col", 0)
    max_row = max(n["row"] for n in nodes) + 1
    max_col = max(n["col"] for n in nodes) + 1
    gap = 0.12
    cell_w = (w - gap * (max_col + 1)) / max_col
    raw_h = (h - gap * (max_row + 1)) / max_row
    cell_h = min(raw_h, 0.95)
    used_h = max_row * cell_h + gap * (max_row + 1)
    top = y + max((h - used_h) / 2, 0)
    ids = {}
    prst = {"start": "roundRect", "end": "roundRect", "decision": "diamond", "process": "rect"}
    for node in nodes:
        kind = node.get("kind") or "process"
        pad = 0.06
        sid = canvas.box(
            prst.get(kind, "rect"),
            x + gap + node["col"] * (cell_w + gap) + pad,
            top + gap + node["row"] * (cell_h + gap) + pad,
            cell_w - pad * 2,
            max(cell_h - pad * 2, 0.36),
            node.get("text") or "",
            colors["dominant"] if kind in ("start", "end") else colors["light"],
            12,
        )
        ids[node.get("id")] = sid
    for edge in spec.get("edges") or []:
        if edge.get("from") in ids and edge.get("to") in ids:
            src = _by_id(canvas.shapes)[ids[edge["from"]]]
            dst = _by_id(canvas.shapes)[ids[edge["to"]]]
            if dst["x"] > src["x"] + src["w"] * 0.5:
                canvas.connect(ids[edge["from"]], ids[edge["to"]], 3, 1)
            else:
                canvas.connect(ids[edge["from"]], ids[edge["to"]], 2, 0)


def layout_tree(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    root = spec.get("root") or {}
    children = spec.get("children") or []
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    levels = 1 + (1 if children else 0)
    if any(ch.get("children") for ch in children):
        levels = 3
    gap = 0.1
    band_h = (h - gap * (levels + 1)) / levels
    root_w = min(3.2, w * 0.4)
    root_id = canvas.box(
        "roundRect", x + (w - root_w) / 2, y + gap, root_w, band_h * 0.8, root.get("text") or "", colors["dominant"], 14
    )
    if not children:
        return
    cw = (w - gap * (len(children) + 1)) / len(children)
    child_ids = []
    for i, child in enumerate(children):
        sid = canvas.box(
            "roundRect",
            x + gap + i * (cw + gap),
            y + gap * 2 + band_h,
            cw,
            band_h * 0.75,
            child.get("text") or "",
            colors["accent"],
            12,
        )
        child_ids.append(sid)
        canvas.connect(root_id, sid, 2, 0)
        grand = child.get("children") or []
        if not grand:
            continue
        gw = (cw - gap * (len(grand) - 1)) / len(grand) if len(grand) else cw
        # 孙节点放在该子节点正下方，宽度不够时缩小
        base_x = x + gap + i * (cw + gap)
        for j, g in enumerate(grand):
            gid = canvas.box(
                "roundRect",
                base_x + j * (gw + gap),
                y + gap * 3 + band_h * 2,
                max(gw, 0.4),
                band_h * 0.7,
                g.get("text") if isinstance(g, dict) else str(g),
                colors["light"],
                10,
            )
            canvas.connect(sid, gid, 2, 0)


def layout_chevron(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    phases = spec.get("phases") or []
    columns = spec.get("columns") or []
    if not phases:
        raise SystemExit("chevron-matrix 需要 phases")
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    n = len(phases)
    gap = 0.08
    chev_h = min(0.55, h * 0.22)
    bw = (w - gap * (n - 1)) / n
    ids = []
    for i, phase in enumerate(phases):
        sid = canvas.box("chevron", x + i * (bw + gap), y, bw, chev_h, phase, colors["dominant"], 12)
        ids.append(sid)
        if i:
            canvas.connect(ids[i - 1], sid, 3, 1)
    rows = max((len(col) for col in columns), default=0)
    if not rows:
        return
    body_top = y + chev_h + gap
    body_h = h - chev_h - gap
    cell_h = (body_h - gap * (rows - 1)) / rows
    for c, col in enumerate(columns):
        for r, text in enumerate(col):
            canvas.box(
                "rect",
                x + c * (bw + gap),
                body_top + r * (cell_h + gap),
                bw,
                cell_h,
                text if isinstance(text, str) else text.get("text") or "",
                colors["light"],
                11,
            )


def layout_bands(spec: dict, box: dict, canvas: Canvas, colors: dict) -> None:
    """样式甲：左侧层标签，右侧标题加一行说明。emphasis 为真的层用深色条。"""
    layers = spec.get("layers") or []
    if not layers:
        raise SystemExit("bands 需要 layers")
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    gap = 0.08
    rail = min(1.45, w * 0.16)
    band_h = (h - gap * (len(layers) + 1)) / len(layers)
    for i, layer in enumerate(layers):
        top = y + gap + i * (band_h + gap)
        canvas.box("roundRect", x, top, rail, band_h, layer.get("name") or "", colors["accent"], 12)
        items = layer.get("items") or []
        if not items:
            continue
        inner_x = x + rail + gap
        inner_w = w - rail - gap
        cols = len(items)
        cell_w = (inner_w - gap * (cols + 1)) / cols
        cell_h = max(band_h - 0.1, 0.36)
        fill = colors["accent"] if layer.get("emphasis") else "FFFFFF"
        for j, item in enumerate(items):
            if isinstance(item, str):
                text = item
            else:
                title = item.get("title") or ""
                sub = item.get("sub") or ""
                text = title + ("\n" + sub if sub else "")
            canvas.box(
                "roundRect",
                inner_x + gap + j * (cell_w + gap),
                top + (band_h - cell_h) / 2,
                cell_w,
                cell_h,
                text,
                fill,
                12,
            )


LAYOUTS = {
    "pipeline": layout_pipeline,
    "cards-steps": layout_cards_steps,
    "layers": layout_layers,
    "bands": layout_bands,
    "flowchart": layout_flowchart,
    "tree": layout_tree,
    "chevron-matrix": layout_chevron,
}


def make_shape(rec: dict, font: str) -> etree._Element:
    sp = etree.Element(q(P, "sp"))
    nv = etree.SubElement(sp, q(P, "nvSpPr"))
    cnv = etree.SubElement(nv, q(P, "cNvPr"))
    cnv.set("id", str(rec["id"]))
    cnv.set("name", f"图元 {rec['id']}")
    etree.SubElement(nv, q(P, "cNvSpPr"))
    etree.SubElement(nv, q(P, "nvPr"))
    sp_pr = etree.SubElement(sp, q(P, "spPr"))
    xfrm = etree.SubElement(sp_pr, q(A, "xfrm"))
    off = etree.SubElement(xfrm, q(A, "off"))
    off.set("x", str(emu(rec["x"])))
    off.set("y", str(emu(rec["y"])))
    ext = etree.SubElement(xfrm, q(A, "ext"))
    ext.set("cx", str(max(emu(rec["w"]), 1)))
    ext.set("cy", str(max(emu(rec["h"]), 1)))
    geom = etree.SubElement(sp_pr, q(A, "prstGeom"))
    geom.set("prst", rec["prst"])
    etree.SubElement(geom, q(A, "avLst"))
    solid = etree.SubElement(sp_pr, q(A, "solidFill"))
    etree.SubElement(solid, q(A, "srgbClr")).set("val", rec["fill"])
    ln = etree.SubElement(sp_pr, q(A, "ln"))
    ln.set("w", "12700")
    lsolid = etree.SubElement(ln, q(A, "solidFill"))
    etree.SubElement(lsolid, q(A, "srgbClr")).set("val", rec["line"])
    tx = etree.SubElement(sp, q(P, "txBody"))
    body = etree.SubElement(tx, q(A, "bodyPr"))
    body.set("wrap", "square")
    body.set("anchor", "ctr")
    for key in ("lIns", "tIns", "rIns", "bIns"):
        body.set(key, "36000")
    etree.SubElement(tx, q(A, "lstStyle"))
    for line in rec["lines"]:
        p = etree.SubElement(tx, q(A, "p"))
        ppr = etree.SubElement(p, q(A, "pPr"))
        ppr.set("algn", "ctr")
        r = etree.SubElement(p, q(A, "r"))
        rpr = etree.SubElement(r, q(A, "rPr"))
        rpr.set("lang", "zh-CN")
        rpr.set("sz", str(rec["pt"] * 100))
        rfill = etree.SubElement(rpr, q(A, "solidFill"))
        etree.SubElement(rfill, q(A, "srgbClr")).set("val", rec["font_color"])
        latin = etree.SubElement(rpr, q(A, "latin"))
        latin.set("typeface", font)
        ea = etree.SubElement(rpr, q(A, "ea"))
        ea.set("typeface", font)
        t = etree.SubElement(r, q(A, "t"))
        t.text = line
    return sp


def make_connector(link: dict, shapes: dict, color: str, cid: int) -> etree._Element:
    src = shapes[link["src"]]
    dst = shapes[link["dst"]]
    x1, y1 = side_point(src, link["src_idx"])
    x2, y2 = side_point(dst, link["dst_idx"])
    cxn = etree.Element(q(P, "cxnSp"))
    nv = etree.SubElement(cxn, q(P, "nvCxnSpPr"))
    cnv = etree.SubElement(nv, q(P, "cNvPr"))
    cnv.set("id", str(cid))
    cnv.set("name", f"连接符 {cid}")
    cnv_cxn = etree.SubElement(nv, q(P, "cNvCxnSpPr"))
    st = etree.SubElement(cnv_cxn, q(A, "stCxn"))
    st.set("id", str(link["src"]))
    st.set("idx", str(link["src_idx"]))
    en = etree.SubElement(cnv_cxn, q(A, "endCxn"))
    en.set("id", str(link["dst"]))
    en.set("idx", str(link["dst_idx"]))
    etree.SubElement(nv, q(P, "nvPr"))
    sp_pr = etree.SubElement(cxn, q(P, "spPr"))
    xfrm = etree.SubElement(sp_pr, q(A, "xfrm"))
    if x1 > x2:
        xfrm.set("flipH", "1")
    if y1 > y2:
        xfrm.set("flipV", "1")
    off = etree.SubElement(xfrm, q(A, "off"))
    off.set("x", str(emu(min(x1, x2))))
    off.set("y", str(emu(min(y1, y2))))
    ext = etree.SubElement(xfrm, q(A, "ext"))
    ext.set("cx", str(max(emu(abs(x2 - x1)), 0)))
    ext.set("cy", str(max(emu(abs(y2 - y1)), 0)))
    geom = etree.SubElement(sp_pr, q(A, "prstGeom"))
    geom.set("prst", "straightConnector1")
    etree.SubElement(geom, q(A, "avLst"))
    ln = etree.SubElement(sp_pr, q(A, "ln"))
    ln.set("w", "12700")
    solid = etree.SubElement(ln, q(A, "solidFill"))
    etree.SubElement(solid, q(A, "srgbClr")).set("val", color)
    tail = etree.SubElement(ln, q(A, "tailEnd"))
    tail.set("type", "triangle")
    return cxn


def group_of(elements: list[etree._Element], gid: int) -> etree._Element:
    boxes = []
    for el in elements:
        xfrm = el.find(".//" + q(A, "xfrm"))
        off = xfrm.find(q(A, "off"))
        ext = xfrm.find(q(A, "ext"))
        boxes.append(
            (
                int(off.get("x")),
                int(off.get("y")),
                int(off.get("x")) + int(ext.get("cx")),
                int(off.get("y")) + int(ext.get("cy")),
            )
        )
    min_x = min(b[0] for b in boxes)
    min_y = min(b[1] for b in boxes)
    max_x = max(b[2] for b in boxes)
    max_y = max(b[3] for b in boxes)
    grp = etree.Element(q(P, "grpSp"))
    nv = etree.SubElement(grp, q(P, "nvGrpSpPr"))
    cnv = etree.SubElement(nv, q(P, "cNvPr"))
    cnv.set("id", str(gid))
    cnv.set("name", "结构图")
    etree.SubElement(nv, q(P, "cNvGrpSpPr"))
    etree.SubElement(nv, q(P, "nvPr"))
    gp = etree.SubElement(grp, q(P, "grpSpPr"))
    xfrm = etree.SubElement(gp, q(A, "xfrm"))
    off = etree.SubElement(xfrm, q(A, "off"))
    off.set("x", str(min_x))
    off.set("y", str(min_y))
    ext = etree.SubElement(xfrm, q(A, "ext"))
    ext.set("cx", str(max(max_x - min_x, 1)))
    ext.set("cy", str(max(max_y - min_y, 1)))
    ch_off = etree.SubElement(xfrm, q(A, "chOff"))
    ch_off.set("x", str(min_x))
    ch_off.set("y", str(min_y))
    ch_ext = etree.SubElement(xfrm, q(A, "chExt"))
    ch_ext.set("cx", str(max(max_x - min_x, 1)))
    ch_ext.set("cy", str(max(max_y - min_y, 1)))
    for el in elements:
        grp.append(el)
    return grp


def picture_box(root: etree._Element, index: int) -> tuple[dict, str]:
    pics = list(root.iter(q(P, "pic")))
    if index < 1 or index > len(pics):
        raise SystemExit(f"该页没有第 {index} 张图片")
    pic = pics[index - 1]
    xfrm = pic.find(".//" + q(A, "xfrm"))
    off = xfrm.find(q(A, "off"))
    ext = xfrm.find(q(A, "ext"))
    box = {
        "x": int(off.get("x")) / EMU,
        "y": int(off.get("y")) / EMU,
        "w": int(ext.get("cx")) / EMU,
        "h": int(ext.get("cy")) / EMU,
    }
    blip = pic.find(".//" + q(A, "blip"))
    rid = blip.get(q(R, "embed")) if blip is not None else ""
    pic.getparent().remove(pic)
    return box, rid


def drop_rel_if_unused(parts: dict[str, bytes], slide_part: str, root: etree._Element, rid: str) -> None:
    if not rid:
        return
    if any(blip.get(q(R, "embed")) == rid for blip in root.iter(q(A, "blip"))):
        return
    rels_part = slide_part.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    if rels_part not in parts:
        return
    rels = parse(parts[rels_part])
    target = ""
    for rel in list(rels):
        if rel.get("Id") == rid:
            target = Path(rel.get("Target") or "").name
            rel.getparent().remove(rel)
    parts[rels_part] = dump(rels)
    if not target:
        return
    used = False
    for name, blob in parts.items():
        if name.endswith(".rels") and target in blob.decode("utf-8", errors="ignore"):
            used = True
            break
    media = f"ppt/media/{target}"
    if not used and media in parts:
        del parts[media]


def colors_from(spec: dict, style_path: str | None, pptx: Path) -> tuple[dict, str]:
    if spec.get("colors") and spec.get("font"):
        return spec["colors"], spec["font"]
    palette = {}
    font = ""
    if style_path:
        card = json.loads(Path(style_path).read_text(encoding="utf-8"))
    else:
        card = analyze(pptx)
    palette = card.get("palette") or {}
    font = (card.get("fonts") or {}).get("ea") or "微软雅黑"
    from diagram.palette import pick_dominant
    dominant = pick_dominant(palette)
    colors = {
        "dominant": dominant,
        "accent": palette.get("accent") or dominant,
        "light": palette.get("light") or "E7F3F2",
        "surface": palette.get("surface") or "F7F7F7",
        "text": palette.get("text") or "000000",
        "line": dominant,
    }
    colors.update(spec.get("colors") or {})
    return colors, spec.get("font") or font


def draw(
    parts: dict[str, bytes],
    slide_index: int,
    spec: dict,
    style_path: str | None,
    pic: int | None,
    pptx: Path,
    svg_path: str | Path | None = None,
) -> dict:
    order = slide_order(parts)
    if slide_index < 1 or slide_index > len(order):
        raise SystemExit(f"没有第 {slide_index} 页")
    part = order[slide_index - 1]["part"]
    root = parse(parts[part])
    if pic:
        box, rid = picture_box(root, pic)
    else:
        box = spec.get("bbox")
        rid = ""
        if not box:
            raise SystemExit("需要 --pic 或 spec.bbox")
    layout = spec.get("layout")
    if layout not in LAYOUTS:
        raise SystemExit(f"未知版式 {layout}。可用：{', '.join(LAYOUTS)}")
    colors, font = colors_from(spec, style_path, pptx)
    canvas = Canvas(font, colors["text"], colors["line"])
    canvas._n = max_shape_id(root)
    LAYOUTS[layout](spec, box, canvas, colors)
    if svg_path:
        svg = render_svg(canvas, box, bg=colors.get("surface") or "FFFFFF")
        Path(svg_path).parent.mkdir(parents=True, exist_ok=True)
        Path(svg_path).write_text(svg, encoding="utf-8")
    elements = [make_shape(rec, font) for rec in canvas.shapes]
    shape_map = {rec["id"]: rec for rec in canvas.shapes}
    next_id = max([rec["id"] for rec in canvas.shapes], default=canvas._n) + 1
    for link in canvas.links:
        elements.append(make_connector(link, shape_map, colors["line"], next_id))
        next_id += 1
    if not elements:
        raise SystemExit("没有画出任何图元")
    grp = group_of(elements, next_id)
    sp_tree = root.find(q(P, "cSld")).find(q(P, "spTree"))
    sp_tree.append(grp)
    if rid:
        drop_rel_if_unused(parts, part, root, rid)
    parts[part] = dump(root)
    texts = [line for rec in canvas.shapes for line in rec["lines"]]
    return {
        "slide": slide_index,
        "layout": layout,
        "shapes": len(canvas.shapes),
        "connectors": len(canvas.links),
        "texts": texts,
        "svg": str(svg_path) if svg_path else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="在幻灯片上绘制结构图")
    parser.add_argument("pptx")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--slide", type=int, required=True)
    parser.add_argument("--spec", required=True, help="版式 JSON")
    parser.add_argument("--style", help="风格卡 JSON；缺省时从 pptx 现抽")
    parser.add_argument("--pic", type=int, help="用该页第几张图片的外框，并删掉这张图片")
    parser.add_argument("--svg", help="同时写出这张图的 SVG 预览；和形状来自同一份数据，不会和形状版不一致")
    args = parser.parse_args()
    src = Path(args.pptx)
    dest = Path(args.output)
    require_different(src, dest)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    parts = load_pptx(src)
    info = draw(parts, args.slide, spec, args.style, args.pic, src, args.svg)
    save_pptx(dest, parts)
    print(json.dumps({"output": str(dest), **info}, ensure_ascii=False))


if __name__ == "__main__":
    main()
