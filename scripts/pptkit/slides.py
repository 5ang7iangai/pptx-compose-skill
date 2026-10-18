# -*- coding: utf-8 -*-
"""加一页、加一章、改目录条目、删多余形状。"""

from __future__ import annotations

import re

from lxml import etree

from .ooxml import (
    A,
    P,
    absolute_shapes,
    dump,
    joined_text,
    max_shape_id,
    parse,
    q,
    shape_text,
    slide_order,
)

EMU = 914400


def _canvas(parts: dict[str, bytes]) -> tuple[float, float]:
    root = parse(parts["ppt/presentation.xml"])
    sz = root.find(q(P, "sldSz"))
    return int(sz.get("cx")) / EMU, int(sz.get("cy")) / EMU


def _overlaps(a: dict, b: dict, gap: float = 0.06) -> bool:
    return not (
        a["x"] + a["w"] + gap <= b["x"]
        or b["x"] + b["w"] + gap <= a["x"]
        or a["y"] + a["h"] + gap <= b["y"]
        or b["y"] + b["h"] + gap <= a["y"]
    )


def _fits(cand: dict, others: list[dict], slide_w: float, slide_h: float) -> bool:
    if cand["x"] < 0.25 or cand["y"] < 0.25:
        return False
    if cand["x"] + cand["w"] > slide_w - 0.25 or cand["y"] + cand["h"] > slide_h - 0.25:
        return False
    return not any(_overlaps(cand, other) for other in others)


def _series_gap(anchor: dict, others: list[dict]) -> float:
    """同一列章节条目的间距。取能放进画布的那一档，不用固定 0.15。"""
    peers = [
        sp
        for sp in others
        if "、" in sp["text"]
        and abs(sp["x"] - anchor["x"]) < 0.4
        and abs(sp["h"] - anchor["h"]) < 0.15
    ]
    peers.append(anchor)
    peers.sort(key=lambda sp: sp["y"])
    gaps = []
    above = None
    for prev, nxt in zip(peers, peers[1:]):
        gap = nxt["y"] - (prev["y"] + prev["h"])
        if gap > 0.05:
            gaps.append(gap)
            if nxt is anchor:
                above = gap
    if above is not None:
        return above
    if not gaps:
        return 0.15
    gaps.sort()
    return gaps[len(gaps) // 2]


def _place(anchor: dict, others: list[dict], slide_w: float, slide_h: float) -> tuple[float, float, bool]:
    w, h = anchor["w"], anchor["h"]
    ax, ay = anchor["x"], anchor["y"]
    gap = _series_gap(anchor, others)
    candidates = [
        (ax, ay + h + gap),
        (ax + w + 0.2, ay),
        (ax - w - 0.2, ay),
        (ax, ay - h - gap),
        (0.5, slide_h - h - 0.4),
        (slide_w - w - 0.4, slide_h - h - 0.4),
    ]
    for x, y in candidates:
        cand = {"x": x, "y": y, "w": w, "h": h}
        if _fits(cand, others, slide_w, slide_h):
            return x, y, False
    return candidates[1][0], candidates[1][1], True


def _set_off(sp: etree._Element, x_in: float, y_in: float) -> None:
    xfrm = None
    for child in sp:
        if child.tag == q(P, "spPr"):
            xfrm = child.find(q(A, "xfrm"))
            break
    if xfrm is None:
        return
    off = xfrm.find(q(A, "off"))
    if off is None:
        return
    off.set("x", str(int(x_in * EMU)))
    off.set("y", str(int(y_in * EMU)))


def _replace_all_text(sp: etree._Element, text: str) -> None:
    texts = list(sp.iter(q(A, "t")))
    if not texts:
        return
    texts[0].text = text
    for extra in texts[1:]:
        extra.text = ""


def _sp_pr(sp: etree._Element):
    for child in sp:
        if child.tag == q(P, "spPr"):
            return child
    return None



def _sanitize_sp_fill(sp: etree._Element, *, want_solid: bool | None = None) -> None:
    """去掉互相打架的 noFill / solidFill。want_solid=True 只留实心；False 只留 noFill；
    None 则：有 solidFill 就去掉 noFill（避免白字无底），否则保留现状。"""
    pr = _sp_pr(sp)
    if pr is None:
        return
    solid = pr.find(q(A, "solidFill"))
    no = pr.find(q(A, "noFill"))
    if want_solid is True:
        if no is not None:
            pr.remove(no)
        return
    if want_solid is False:
        if solid is not None:
            pr.remove(solid)
        if no is None:
            # 插在几何后
            anchor = pr.find(q(A, "prstGeom"))
            if anchor is None:
                anchor = pr.find(q(A, "xfrm"))
            el = etree.Element(q(A, "noFill"))
            if anchor is not None:
                anchor.addnext(el)
            else:
                pr.insert(0, el)
        return
    if solid is not None and no is not None:
        pr.remove(no)


def _is_solid(sp: etree._Element) -> bool:
    pr = _sp_pr(sp)
    if pr is None:
        return False
    return pr.find(q(A, "solidFill")) is not None and pr.find(q(A, "noFill")) is None


def _copy_font_color(dst_sp: etree._Element, src_sp: etree._Element) -> None:
    """色块上的白字换成普通条目的字色，避免无填充后看不见。"""
    src_tx = src_sp.find(q(P, "txBody"))
    dst_tx = dst_sp.find(q(P, "txBody"))
    if src_tx is None or dst_tx is None:
        return
    src_rpr = src_tx.find(".//" + q(A, "rPr"))
    if src_rpr is None or src_rpr.find(q(A, "solidFill")) is None:
        return
    fill = etree.tostring(src_rpr.find(q(A, "solidFill")))
    for rpr in list(dst_tx.iter(q(A, "rPr"))) + list(dst_tx.iter(q(A, "endParaRPr"))):
        old = rpr.find(q(A, "solidFill"))
        if old is not None:
            rpr.replace(old, etree.fromstring(fill))
        else:
            rpr.insert(0, etree.fromstring(fill))


def _copy_paint(dst_sp: etree._Element, src_sp: etree._Element) -> None:
    """把填充和线条换成另一个条目的，位置不动。"""
    dst = _sp_pr(dst_sp)
    src = _sp_pr(src_sp)
    if dst is None or src is None:
        return
    xfrm = dst.find(q(A, "xfrm"))
    new_pr = etree.fromstring(etree.tostring(src))
    if xfrm is not None:
        old = new_pr.find(q(A, "xfrm"))
        if old is not None:
            new_pr.replace(old, etree.fromstring(etree.tostring(xfrm)))
        else:
            new_pr.insert(0, etree.fromstring(etree.tostring(xfrm)))
    dst.getparent().replace(dst, new_pr)
    _copy_font_color(dst_sp, src_sp)
    _sanitize_sp_fill(dst_sp, want_solid=_is_solid(src_sp))


def add_toc_label(
    parts: dict[str, bytes], title: str, anchor: str, current_slide: int | None = None
) -> list[dict]:
    slide_w, slide_h = _canvas(parts)
    report = []
    for row in slide_order(parts):
        xml = parts[row["part"]]
        blob = joined_text(xml)
        compact = "".join(blob.split()).upper()
        if "目录" not in compact and "CONTENTS" not in compact:
            continue
        if title in blob:
            report.append({"slide": row["index"], "status": "already"})
            continue
        root = parse(xml)
        shapes = absolute_shapes(root)
        hits = [sp for sp in shapes if anchor in sp["text"]]
        if not hits:
            report.append({"slide": row["index"], "status": "no-anchor"})
            continue
        src = min(hits, key=lambda sp: len(sp["text"]))
        others = [sp for sp in shapes if sp is not src]
        x, y, overlap = _place(src, others, slide_w, slide_h)
        clone = etree.fromstring(etree.tostring(src["el"]))
        nv = clone.find(".//" + q(P, "cNvPr"))
        new_id = max_shape_id(root) + 1
        if nv is not None:
            nv.set("id", str(new_id))
            nv.set("name", f"章节 {new_id}")
        _set_off(clone, x, y)
        _replace_all_text(clone, title)
        if _is_solid(src["el"]):
            plain = [
                sp
                for sp in shapes
                if sp is not src and "、" in sp["text"] and not _is_solid(sp["el"])
            ]
            if plain:
                donor = max(plain, key=lambda sp: sp["y"])
                if current_slide == row["index"]:
                    _copy_paint(src["el"], donor["el"])
                else:
                    _copy_paint(clone, donor["el"])
        sp_tree = root.find(q(P, "cSld")).find(q(P, "spTree"))
        sp_tree.append(clone)
        parts[row["part"]] = dump(root)
        report.append(
            {
                "slide": row["index"],
                "status": "overlap" if overlap else "added",
                "x": round(x, 2),
                "y": round(y, 2),
            }
        )
    return report


def _toc_rows(shapes: list[dict]) -> list[tuple[dict, dict]]:
    """目录条目行：编号（01、02…）+ 同一行右侧最近的章节名。"""
    rows = []
    for num in (s for s in shapes if re.fullmatch(r"0?\d{1,2}", s["text"].strip())):
        cy = num["y"] + num["h"] / 2
        same = [s for s in shapes if s is not num and s["x"] > num["x"] and abs(s["y"] + s["h"] / 2 - cy) < 0.3
                and len(s["text"].strip()) > 2]
        if same:
            rows.append((num, min(same, key=lambda s: s["x"])))
    return sorted(rows, key=lambda r: r[0]["y"])


def _shift_y(sp: etree._Element, dy_in: float) -> None:
    off = sp.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}/{q(A, 'off')}")
    if off is not None:
        off.set("y", str(int(off.get("y")) + int(dy_in * EMU)))


def toc_entry_count(parts: dict[str, bytes], index: int) -> int:
    """目录页上 fill_toc 能认出的条目行数；为 0 时换不了条目，整套新编不保留这页。"""
    return len(_toc_rows(absolute_shapes(parse(parts[slide_order(parts)[index - 1]["part"]]))))


def _style_key(el: etree._Element) -> bytes:
    """条目的填充和字色，用来区分模板里的当前章和其余章。"""
    chunks = []
    pr = _sp_pr(el)
    if pr is not None and _is_solid(el):
        chunks.append(etree.tostring(pr.find(q(A, "solidFill"))))
    rpr = el.find(".//" + q(A, "rPr"))
    if rpr is not None and rpr.find(q(A, "solidFill")) is not None:
        chunks.append(etree.tostring(rpr.find(q(A, "solidFill"))))
    return b"|".join(chunks)


def _toc_prototypes(rows: list[tuple[dict, dict]]) -> tuple[tuple[dict, dict], tuple[dict, dict]]:
    """多数条目是普通样式，少数那一条是当前章样式。只有一套时两套相同。"""
    keys = [_style_key(num["el"]) + b"#" + _style_key(name["el"]) for num, name in rows]
    counts: dict[bytes, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    rest_key = max(counts, key=lambda k: (counts[k], -keys.index(k)))
    current_key = min(counts, key=lambda k: (counts[k], keys.index(k)))
    rest = rows[keys.index(rest_key)]
    current = rows[keys.index(current_key)]
    return rest, current


def fill_toc(parts: dict[str, bytes], index: int, chapters: list[str], current: int = 0) -> dict:
    """整套新编：把模板目录页的条目换成这份稿的章节。普通条目用模板里出现最多的那套样式，
    current 这一条用当前章样式。间距沿用原条目间距，排不下时在原条目区到页面 85% 高度内均分。"""
    slide_w, slide_h = _canvas(parts)
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    rows = _toc_rows(absolute_shapes(root))
    if not rows or not chapters:
        return {"slide": index, "status": "no-entries"}
    rest, marked = _toc_prototypes(rows)
    num0, name0 = rest
    current = min(max(current, 0), len(chapters) - 1)
    sz = next((int(r.get("sz")) for r in name0["el"].iter(q(A, "rPr")) if r.get("sz")), 1800) / 100
    room = int((slide_w - name0["x"] - 0.3) / (sz / 72))  # 一行能放的汉字数；不缩字号，放不下先去掉括号注释
    labels, too_long = [], []
    for chapter in chapters:
        label = re.sub(r"^[一二三四五六七八九十]+、\s*", "", chapter)  # 编号已在徽标里
        if len(label) > room:
            label = re.sub(r"[（(][^（(]*[)）]$", "", label)
        if len(label) > room:
            too_long.append(label)
        labels.append(label)
    top = rows[0][0]["y"]
    step = rows[1][0]["y"] - top if len(rows) > 1 else rows[0][0]["h"] * 1.8
    bottom = max(rows[-1][0]["y"] + rows[-1][0]["h"], slide_h * 0.85)
    if len(chapters) > 1:
        step = min(step, (bottom - top - rows[0][0]["h"]) / (len(chapters) - 1))
    plain = [etree.fromstring(etree.tostring(num0["el"])), etree.fromstring(etree.tostring(name0["el"]))]
    marked_pair = [etree.fromstring(etree.tostring(marked[0]["el"])), etree.fromstring(etree.tostring(marked[1]["el"]))]
    tree = num0["el"].getparent()
    for num, name in rows:
        for el in (num["el"], name["el"]):
            if el.getparent() is not None:
                el.getparent().remove(el)
    next_id = max_shape_id(root) + 1
    marked_anchor = marked[0]["y"]
    for i, label in enumerate(labels):
        protos = marked_pair if i == current else plain
        # 当前章样板原来不在第一行，要先挪回第一条的位置再按行距排
        anchor = marked_anchor if i == current else num0["y"]
        for proto, text in zip(protos, (f"{i + 1:02d}", label)):
            el = etree.fromstring(etree.tostring(proto))
            for tags in el.iter(q(P, "custDataLst")):  # 插件标签部件只能被一个形状引用，克隆后 PowerPoint 打不开
                tags.getparent().remove(tags)
            nv = el.find(".//" + q(P, "cNvPr"))
            if nv is not None:
                nv.set("id", str(next_id))
            next_id += 1
            _shift_y(el, top + i * step - anchor)
            _replace_all_text(el, text)
            _sanitize_sp_fill(el, want_solid=(i == current))
            tree.append(el)
    parts[part] = dump(root)
    centered = center_toc(parts, index)
    return {"slide": index, "status": "filled", "entries": len(chapters), "current": current + 1,
            "step": round(step, 2), "crowded": step < rows[0][0]["h"] + 0.05, "too_long": too_long,
            "centered": centered}


def _toc_heading_box(shapes: list[dict], left_of: float) -> tuple[float, float] | None:
    """目录页上「目录 / CONTENTS」这组字的纵向范围（只看条目左侧的）。"""
    heads = [s for s in shapes if s["x"] < left_of
             and "".join(s["text"].split()).upper() in ("目录", "CONTENTS", "目录CONTENTS", "CONTENT")]
    if not heads:
        return None
    return min(s["y"] for s in heads), max(s["y"] + s["h"] for s in heads)



def relayout_section_tabs(
    parts: dict[str, bytes],
    index: int,
    labels: list[str],
    current: int,
    *,
    slot_x0: float | None = None,
    slot_x1: float | None = None,
    y: float | None = None,
    h: float | None = None,
    highlight_fill: str = "006F68",
    rest_text: str = "62A7A4",
    by_chars: bool = False,
    gap: float = 0.0,
) -> dict:
    """改完页签文字后按槽位重排：相邻外框 edge-to-edge（默认 gap=0），禁止留缝与重叠。

    labels 从左到右；current 为高亮下标。未给 slot 时用量到的现有页签外包框。
    by_chars=True 时按字数加权分宽。用整数 EMU 累加，保证第 i+1 左缘 = 第 i 右缘 + gap。
    页签描边改为 noFill，避免居中描边在 gap=0 时仍显出「缝」。
    """
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    shapes = absolute_shapes(root)
    tabs = [s for s in shapes if (s.get("text") or "").strip() in set(labels)]
    if len(tabs) < len(labels):
        tabs = [s for s in shapes if s["y"] < 1.6 and 0.5 < s["w"] < 2.5 and s["h"] < 0.6
                and (s.get("text") or "").strip()]
        tabs = sorted(tabs, key=lambda s: s["x"])[: len(labels)]
    else:
        tabs = sorted(tabs, key=lambda s: s["x"])[: len(labels)]
    if len(tabs) != len(labels):
        return {"slide": index, "status": "tab-count", "n": len(tabs)}
    if slot_x0 is None:
        slot_x0 = tabs[0]["x"]
    if slot_x1 is None:
        slot_x1 = max(s["x"] + s["w"] for s in tabs)
    if y is None:
        y = tabs[0]["y"]
    if h is None:
        h = tabs[0]["h"]
    span = slot_x1 - slot_x0
    n = len(labels)
    if by_chars:
        weights = [max(len(L), 3) for L in labels]
        total_w = sum(weights)
        raw = [span * wt / total_w for wt in weights]
    else:
        raw = [span / n] * n
    # 整数 EMU：先定各宽，末块吃掉余数，再按 gap 累加左缘
    gap_emu = int(round(gap * EMU))
    span_emu = int(round(slot_x1 * EMU)) - int(round(slot_x0 * EMU))
    usable = span_emu - gap_emu * (n - 1)
    widths_emu = [max(1, int(round(usable * (w / span)))) for w in raw] if span > 0 else [1] * n
    drift = usable - sum(widths_emu)
    widths_emu[-1] = max(1, widths_emu[-1] + drift)
    x_emu = int(round(slot_x0 * EMU))
    y_emu = int(round(y * EMU))
    h_emu = int(round(h * EMU))
    widths_out = []
    for i, (sp, label) in enumerate(zip(tabs, labels)):
        w_emu = widths_emu[i]
        widths_out.append(round(w_emu / EMU, 4))
        el = sp["el"]
        xfrm = el.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}")
        if xfrm is not None:
            off, ext = xfrm.find(q(A, "off")), xfrm.find(q(A, "ext"))
            if off is not None:
                off.set("x", str(x_emu))
                off.set("y", str(y_emu))
            if ext is not None:
                ext.set("cx", str(w_emu))
                ext.set("cy", str(h_emu))
        x_emu += w_emu + gap_emu
        _replace_all_text(el, label)
        pr = _sp_pr(el)
        if pr is not None:
            for child in list(pr):
                if child.tag in (q(A, "solidFill"), q(A, "noFill")):
                    pr.remove(child)
            anchor = pr.find(q(A, "prstGeom"))
            if anchor is None:
                anchor = pr.find(q(A, "xfrm"))
            sf = etree.Element(q(A, "solidFill"))
            if i == current:
                c = etree.SubElement(sf, q(A, "srgbClr")); c.set("val", highlight_fill)
            else:
                sc = etree.SubElement(sf, q(A, "schemeClr")); sc.set("val", "bg1")
            if anchor is not None:
                anchor.addnext(sf)
            else:
                pr.insert(0, sf)
            # 描边 noFill：gap=0 时居中描边不会再画出「缝」
            old_ln = pr.find(q(A, "ln"))
            if old_ln is not None:
                pr.remove(old_ln)
            ln = etree.Element(q(A, "ln"))
            etree.SubElement(ln, q(A, "noFill"))
            # 放在 solidFill 后
            fill_el = pr.find(q(A, "solidFill"))
            if fill_el is not None:
                fill_el.addnext(ln)
            else:
                pr.append(ln)
        _sanitize_sp_fill(el, want_solid=True)
        for rpr in list(el.iter(q(A, "rPr"))) + list(el.iter(q(A, "endParaRPr"))):
            old = rpr.find(q(A, "solidFill"))
            if old is not None:
                rpr.remove(old)
            fill = etree.SubElement(rpr, q(A, "solidFill"))
            if i == current:
                sc = etree.SubElement(fill, q(A, "schemeClr")); sc.set("val", "bg1")
            else:
                c = etree.SubElement(fill, q(A, "srgbClr")); c.set("val", rest_text)
    parts[part] = dump(root)
    return {"slide": index, "status": "ok", "widths": widths_out, "gap": gap, "current": current}



def center_toc(parts: dict[str, bytes], index: int) -> dict:
    """条目数变了以后，把整组条目（编号块 + 章名，作为一个整体）上下居中：
    对齐左侧「目录 / CONTENTS」的纵向中心，认不出时对齐页面纵向中心。条目间距不变，只整体平移。"""
    slide_w, slide_h = _canvas(parts)
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    shapes = absolute_shapes(root)
    rows = _toc_rows(shapes)
    if not rows:
        return {"status": "no-entries"}
    els = [s for row in rows for s in row]
    top = min(s["y"] for s in els)
    bottom = max(s["y"] + s["h"] for s in els)
    head = _toc_heading_box(shapes, min(s["x"] for s in els))
    target = (head[0] + head[1]) / 2 if head else slide_h / 2
    new_top = target - (bottom - top) / 2
    new_top = max(slide_h * 0.06, min(new_top, slide_h * 0.92 - (bottom - top)))
    dy = new_top - top
    if abs(dy) > 0.01:
        for s in els:
            _shift_y(s["el"], dy)
        parts[part] = dump(root)
    return {"status": "centered", "anchor": "heading" if head else "page", "dy": round(dy, 2),
            "center": round(new_top + (bottom - top) / 2, 2)}


def delete_matching(parts: dict[str, bytes], index: int, match: str) -> int:
    order = slide_order(parts)
    part = order[index - 1]["part"]
    root = parse(parts[part])
    removed = 0
    for sp in list(root.iter(q(P, "sp"))):
        if match in shape_text(sp):
            parent = sp.getparent()
            if parent is not None:
                parent.remove(sp)
                removed += 1
    if removed == 0:
        raise SystemExit(f"第 {index} 页没有包含「{match}」的形状")
    parts[part] = dump(root)
    return removed


def duplicate_matching(parts: dict[str, bytes], index: int, match: str, dx: float, dy: float) -> None:
    order = slide_order(parts)
    part = order[index - 1]["part"]
    root = parse(parts[part])
    shapes = [sp for sp in root.iter(q(P, "sp")) if match in shape_text(sp)]
    if len(shapes) != 1:
        raise SystemExit(f"第 {index} 页「{match}」命中 {len(shapes)} 处，需要唯一")
    src = shapes[0]
    clone = etree.fromstring(etree.tostring(src))
    nv = clone.find(".//" + q(P, "cNvPr"))
    if nv is not None:
        nv.set("id", str(max_shape_id(root) + 1))
        nv.set("name", f"副本 {nv.get('id')}")
    xfrm = None
    for child in clone:
        if child.tag == q(P, "spPr"):
            xfrm = child.find(q(A, "xfrm"))
    if xfrm is not None:
        off = xfrm.find(q(A, "off"))
        if off is not None:
            off.set("x", str(int(off.get("x") or 0) + int(dx * EMU)))
            off.set("y", str(int(off.get("y") or 0) + int(dy * EMU)))
    src.getparent().append(clone)
    parts[part] = dump(root)


def move_matching(parts: dict[str, bytes], index: int, match: str, x: float, y: float) -> None:
    order = slide_order(parts)
    part = order[index - 1]["part"]
    root = parse(parts[part])
    shapes = [sp for sp in absolute_shapes(root) if match in sp["text"]]
    if len(shapes) != 1:
        raise SystemExit(f"第 {index} 页「{match}」命中 {len(shapes)} 处，需要唯一")
    _set_off(shapes[0]["el"], x, y)
    parts[part] = dump(root)
