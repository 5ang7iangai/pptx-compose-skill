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


def _toc_heading_names() -> set[str]:
    return {"目录", "CONTENTS", "目录CONTENTS", "CONTENT"}


_TOC_CHAPTER_RE = re.compile(r"^[一二三四五六七八九十百千]+、\s*.+")
_CN_ORD = "一二三四五六七八九十"


def _toc_badge_rows(shapes: list[dict]) -> list[tuple[dict, dict]]:
    """模式 A：编号徽标（01、02… / 1、2…）+ 同一行右侧最近的章节名。"""
    rows = []
    for num in (s for s in shapes if re.fullmatch(r"0?\d{1,2}", (s.get("text") or "").strip())):
        cy = num["y"] + num["h"] / 2
        same = [
            s for s in shapes
            if s is not num and s["x"] > num["x"] and abs(s["y"] + s["h"] / 2 - cy) < 0.3
            and len((s.get("text") or "").strip()) > 2
        ]
        if same:
            rows.append((num, min(same, key=lambda s: s["x"])))
    return sorted(rows, key=lambda r: r[0]["y"])


def _toc_chapter_rows(shapes: list[dict]) -> list[dict]:
    """模式 B：单行「一、章节名」条目（无独立编号徽标）。排除「目录 / CONTENTS」。"""
    heads = _toc_heading_names()
    rows = []
    for s in shapes:
        t = (s.get("text") or "").strip()
        if not t:
            continue
        if "".join(t.split()).upper() in heads:
            continue
        if _TOC_CHAPTER_RE.match(t):
            rows.append(s)
    return sorted(rows, key=lambda s: s["y"])


def _toc_rows(shapes: list[dict]) -> list[tuple[dict | None, dict]]:
    """目录条目行。优先模式 A（徽标+章名）；否则模式 B（「一、」行，num 为 None）。"""
    badge = _toc_badge_rows(shapes)
    if badge:
        return badge  # type: ignore[return-value]
    return [(None, s) for s in _toc_chapter_rows(shapes)]


def toc_mode(shapes: list[dict]) -> str:
    if _toc_badge_rows(shapes):
        return "badge"
    if _toc_chapter_rows(shapes):
        return "chapter"
    return "none"


def _shift_y(sp: etree._Element, dy_in: float) -> None:
    off = sp.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}/{q(A, 'off')}")
    if off is not None:
        off.set("y", str(int(off.get("y")) + int(dy_in * EMU)))


def toc_entry_count(parts: dict[str, bytes], index: int) -> int:
    """目录页上 fill_toc 能认出的条目行数（模式 A 或 B）；为 0 时不可静默交付旧章。"""
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


def _toc_prototypes(rows: list[tuple[dict | None, dict]]) -> tuple[tuple[dict | None, dict], tuple[dict | None, dict]]:
    """多数条目是普通样式，少数那一条是当前章样式。只有一套时两套相同。"""
    keys = []
    for num, name in rows:
        if num is None:
            keys.append(_style_key(name["el"]))
        else:
            keys.append(_style_key(num["el"]) + b"#" + _style_key(name["el"]))
    counts: dict[bytes, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    rest_key = max(counts, key=lambda k: (counts[k], -keys.index(k)))
    current_key = min(counts, key=lambda k: (counts[k], keys.index(k)))
    rest = rows[keys.index(rest_key)]
    current = rows[keys.index(current_key)]
    return rest, current


def _cn_chapter_label(chapter: str, index: int) -> str:
    """写成「一、xxx」。已有中文序则原样保留；否则按下标补前缀。"""
    t = (chapter or "").strip()
    if _TOC_CHAPTER_RE.match(t):
        return t
    body = re.sub(r"^\d+[\.、．]\s*", "", t)
    body = re.sub(r"^[一二三四五六七八九十百千]+、\s*", "", body)
    if index < 10:
        prefix = _CN_ORD[index]
    elif index == 10:
        prefix = "十一"
    elif index < 19:
        prefix = "十" + _CN_ORD[index - 10]
    else:
        prefix = str(index + 1)
    return f"{prefix}、{body}" if body else f"{prefix}、"


def _clone_shape_abs(
    root: etree._Element,
    proto: etree._Element,
    *,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    next_id: int,
    want_solid: bool,
) -> int:
    """把样板形状拷到 spTree，按幻灯片绝对英寸写 xfrm（避开组合内 chOff 缩放）。"""
    el = etree.fromstring(etree.tostring(proto))
    for tags in el.iter(q(P, "custDataLst")):
        tags.getparent().remove(tags)
    nv = el.find(".//" + q(P, "cNvPr"))
    if nv is not None:
        nv.set("id", str(next_id))
    next_id += 1
    xfrm = el.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}")
    if xfrm is None:
        sp_pr = _sp_pr(el)
        if sp_pr is not None:
            xfrm = etree.SubElement(sp_pr, q(A, "xfrm"))
    if xfrm is not None:
        off = xfrm.find(q(A, "off"))
        if off is None:
            off = etree.SubElement(xfrm, q(A, "off"))
        ext = xfrm.find(q(A, "ext"))
        if ext is None:
            ext = etree.SubElement(xfrm, q(A, "ext"))
        off.set("x", str(int(round(x * EMU))))
        off.set("y", str(int(round(y * EMU))))
        ext.set("cx", str(int(round(w * EMU))))
        ext.set("cy", str(int(round(h * EMU))))
    _replace_all_text(el, text)
    _sanitize_sp_fill(el, want_solid=want_solid)
    sp_tree = root.find(q(P, "cSld")).find(q(P, "spTree"))
    sp_tree.append(el)
    return next_id


def fill_toc(parts: dict[str, bytes], index: int, chapters: list[str], current: int = 0) -> dict:
    """整套新编：把模板目录页的条目换成这份稿的章节。

    模式 A（徽标+章名）：章名去掉「一、」前缀（编号在徽标里）。
    模式 B（「一、」行）：整行写成「一、xxx」，并从现有条目学少数派样式作当前章。
    条目可能落在组合内；填充时一律拆到 spTree 并用绝对坐标排布，避免 chOff 缩放把间距算炸。
    """
    slide_w, slide_h = _canvas(parts)
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    shapes = absolute_shapes(root)
    mode = toc_mode(shapes)
    rows = _toc_rows(shapes)
    if not rows or not chapters:
        return {"slide": index, "status": "no-entries", "mode": mode or "none"}
    rest, marked = _toc_prototypes(rows)
    num0, name0 = rest
    current = min(max(current, 0), len(chapters) - 1)
    sz = next((int(r.get("sz")) for r in name0["el"].iter(q(A, "rPr")) if r.get("sz")), 1800) / 100
    room = int((slide_w - name0["x"] - 0.3) / max(sz / 72, 0.01))
    labels, too_long = [], []
    for i, chapter in enumerate(chapters):
        if mode == "badge":
            label = re.sub(r"^[一二三四五六七八九十百千]+、\s*", "", chapter)
            label = re.sub(r"^\d+[\.、．]\s*", "", label)
        else:
            label = _cn_chapter_label(chapter, i)
        if len(label) > room:
            label = re.sub(r"[（(][^（(]*[)）]$", "", label)
        if len(label) > room:
            too_long.append(label)
        labels.append(label)

    # 锚点与行距一律用绝对英寸（absolute_shapes）
    top = rows[0][1]["y"] if rows[0][0] is None else rows[0][0]["y"]
    if len(rows) > 1:
        y1 = rows[1][1]["y"] if rows[1][0] is None else rows[1][0]["y"]
        step = y1 - top
    else:
        step = rows[0][1]["h"] * 1.8
    last = rows[-1][1]
    bottom = max(last["y"] + last["h"], slide_h * 0.85)
    if len(chapters) > 1:
        step = min(step, (bottom - top - rows[0][1]["h"]) / (len(chapters) - 1))

    # 删掉旧条目（徽标+章名或单行）
    for num, name in rows:
        for el in ((num["el"], name["el"]) if num is not None else (name["el"],)):
            if el.getparent() is not None:
                el.getparent().remove(el)

    next_id = max_shape_id(root) + 1
    if mode == "chapter":
        for i, label in enumerate(labels):
            proto_shape = marked[1] if i == current else name0
            y = top + i * step
            next_id = _clone_shape_abs(
                root, proto_shape["el"],
                text=label, x=proto_shape["x"], y=y,
                w=proto_shape["w"], h=proto_shape["h"],
                next_id=next_id,
                want_solid=(i == current) or _is_solid(proto_shape["el"]),
            )
    else:
        for i, label in enumerate(labels):
            protos = (marked[0], marked[1]) if i == current else (num0, name0)
            y = top + i * step
            for proto_shape, text in zip(protos, (f"{i + 1:02d}", label)):
                next_id = _clone_shape_abs(
                    root, proto_shape["el"],
                    text=text, x=proto_shape["x"], y=y,
                    w=proto_shape["w"], h=proto_shape["h"],
                    next_id=next_id,
                    want_solid=(i == current),
                )

    parts[part] = dump(root)
    centered = center_toc(parts, index)
    return {
        "slide": index, "status": "filled", "mode": mode, "entries": len(chapters),
        "current": current + 1, "step": round(step, 2),
        "crowded": step < rows[0][1]["h"] + 0.05, "too_long": too_long, "centered": centered,
    }



def _toc_heading_box(shapes: list[dict], left_of: float) -> tuple[float, float] | None:
    """目录页上「目录 / CONTENTS」这组字的纵向范围（只看条目左侧的）。"""
    heads = [
        s for s in shapes if s["x"] < left_of
        and "".join(s["text"].split()).upper() in _toc_heading_names()
    ]
    if not heads:
        return None
    return min(s["y"] for s in heads), max(s["y"] + s["h"] for s in heads)



def _tab_font_pt(el: etree._Element) -> float:
    for rpr in el.iter(q(A, "rPr")):
        sz = rpr.get("sz")
        if sz:
            try:
                return int(sz) / 100.0
            except ValueError:
                pass
    return 12.0


def _estimate_label_in(label: str, font_pt: float, pad: float = 0.40) -> float:
    """中文约 1.2em/字（含加粗与字体回退余量），ASCII 约 0.55em；pad 含左右内边距。单位英寸。"""
    em = font_pt / 72.0
    units = 0.0
    for ch in label or "":
        units += 0.55 if ord(ch) < 128 else 1.2
    return units * em + pad


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
    max_x1: float | None = None,
) -> dict:
    """改完页签文字后按槽位重排：相邻外框 edge-to-edge（默认 gap=0），禁止留缝与重叠。

    labels 从左到右；current 为高亮下标。未给 slot 时用量到的现有页签外包框。
    by_chars=True 时按字数加权分宽。用整数 EMU 累加，保证第 i+1 左缘 = 第 i 右缘 + gap。
    页签描边改为 noFill，避免居中描边在 gap=0 时仍显出「缝」。

    宽度须能单行放下各 label：不够时优先向右扩展（不压 logo，默认 slide_w-2.2″），
    仍不够再略缩字号（不低于原字号 85%）。不静默截断文字。
    """
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    shapes = absolute_shapes(root)
    tabs = [s for s in shapes if (s.get("text") or "").strip() in set(labels)]
    if len(tabs) < len(labels):
        # 回退：在顶栏找「同行多枚」页签带，避开单独的页题（宽标题常在另一行）
        cands = [s for s in shapes if s["y"] < 1.6 and 0.4 < s["w"] < 4.0 and s["h"] < 0.65
                 and (s.get("text") or "").strip()]
        bands: dict[float, list] = {}
        for s in cands:
            key = round(s["y"] / 0.05) * 0.05
            bands.setdefault(key, []).append(s)
        # 优先成员数 ≥ 所需页签数的最密行；否则取成员最多的一行（且 ≥2，避免单页题）
        ranked = sorted(bands.values(), key=lambda g: (-len(g), g[0]["y"]))
        band = next((g for g in ranked if len(g) >= len(labels)), None)
        if band is None:
            band = next((g for g in ranked if len(g) >= 2), ranked[0] if ranked else [])
        tabs = sorted(band, key=lambda s: s["x"])[: len(labels)]
        leftovers = sorted(band, key=lambda s: s["x"])[len(labels):]
    else:
        tabs = sorted(tabs, key=lambda s: s["x"])[: len(labels)]
        leftovers = []
    if len(tabs) != len(labels):
        return {"slide": index, "status": "tab-count", "n": len(tabs)}
    if slot_x0 is None:
        slot_x0 = tabs[0]["x"]
    orig_slot_x1 = max(s["x"] + s["w"] for s in tabs)
    if slot_x1 is None:
        slot_x1 = orig_slot_x1
    if y is None:
        y = tabs[0]["y"]
    if h is None:
        h = tabs[0]["h"]
    slide_w, _ = _canvas(parts)
    if max_x1 is None:
        max_x1 = max(orig_slot_x1, slide_w - 2.2)
    n = len(labels)
    font_pt = _tab_font_pt(tabs[0]["el"])
    orig_font_pt = font_pt
    expanded = False
    font_scaled = False
    need_confirm = False

    def _needed(pt: float) -> list[float]:
        return [_estimate_label_in(L, pt) for L in labels]

    needed = _needed(font_pt)
    min_total = sum(needed) + gap * (n - 1)
    # 1) 向右扩展槽位
    if slot_x1 - slot_x0 < min_total - 1e-6:
        new_x1 = min(slot_x0 + min_total, max_x1)
        if new_x1 > slot_x1 + 1e-6:
            slot_x1 = new_x1
            expanded = True
    span = slot_x1 - slot_x0
    usable_in = span - gap * (n - 1)
    # 2) 仍不够 → 略缩字号（≥85%）
    if usable_in + 1e-6 < sum(needed):
        for scale in (0.95, 0.90, 0.85):
            font_pt = orig_font_pt * scale
            needed = _needed(font_pt)
            if sum(needed) <= usable_in + 1e-6:
                font_scaled = True
                break
        else:
            font_pt = orig_font_pt * 0.85
            needed = _needed(font_pt)
            font_scaled = True
            # 再扩一次到 max_x1
            min_total = sum(needed) + gap * (n - 1)
            if slot_x0 + min_total <= max_x1 + 1e-6:
                slot_x1 = slot_x0 + min_total
                expanded = True
                span = slot_x1 - slot_x0
                usable_in = span - gap * (n - 1)
            if usable_in + 1e-6 < sum(needed):
                need_confirm = True

    # 3) 分配宽度：至少满足各 label 所需；剩余按字数或等分
    if by_chars:
        weights = [max(len(L), 3) for L in labels]
    else:
        weights = [1] * n
    tw = sum(weights) or n
    # 先按权重，再抬到 needed 下限
    raw = [usable_in * (wt / tw) for wt in weights]
    raw = [max(r, nd) for r, nd in zip(raw, needed)]
    if sum(raw) > usable_in + 1e-6:
        # 需要的下限之和已超过 usable：再向右扩（若还能），否则按 needed 比例压缩到 usable
        deficit = sum(raw) - usable_in
        room = max_x1 - slot_x1
        if room > 1e-6:
            grow = min(deficit, room)
            slot_x1 += grow
            expanded = True
            span = slot_x1 - slot_x0
            usable_in = span - gap * (n - 1)
            raw = [usable_in * (wt / tw) for wt in weights]
            raw = [max(r, nd) for r, nd in zip(raw, needed)]
        if sum(raw) > usable_in + 1e-6:
            # 保底：按 needed 比例占满 usable（可能略挤，已 try 缩字号）
            nt = sum(needed) or 1.0
            raw = [usable_in * (nd / nt) for nd in needed]
            need_confirm = True

    gap_emu = int(round(gap * EMU))
    span_emu = int(round(slot_x1 * EMU)) - int(round(slot_x0 * EMU))
    usable = span_emu - gap_emu * (n - 1)
    widths_emu = [max(1, int(round(usable * (w / sum(raw))))) for w in raw] if sum(raw) > 0 else [1] * n
    drift = usable - sum(widths_emu)
    widths_emu[-1] = max(1, widths_emu[-1] + drift)
    x_emu = int(round(slot_x0 * EMU))
    y_emu = int(round(y * EMU))
    h_emu = int(round(h * EMU))
    widths_out = []
    sz_hundredths = str(int(round(font_pt * 100)))
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
        # 单行平铺、垂直居中；去掉 autofit；收紧默认 inset，避免字被挤换行
        body = el.find(f"{q(P, 'txBody')}/{q(A, 'bodyPr')}")
        if body is None:
            body = el.find(f".//{q(A, 'bodyPr')}")
        if body is not None:
            body.set("wrap", "none")
            body.set("anchor", "ctr")
            body.set("lIns", str(int(0.04 * EMU)))
            body.set("rIns", str(int(0.04 * EMU)))
            body.set("tIns", str(int(0.02 * EMU)))
            body.set("bIns", str(int(0.02 * EMU)))
            for child in list(body):
                if child.tag in (q(A, "spAutoFit"), q(A, "normAutofit"), q(A, "noAutofit")):
                    body.remove(child)
            etree.SubElement(body, q(A, "noAutofit"))
        for pPr in el.iter(q(A, "pPr")):
            pPr.set("algn", "ctr")
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
            old_ln = pr.find(q(A, "ln"))
            if old_ln is not None:
                pr.remove(old_ln)
            ln = etree.Element(q(A, "ln"))
            etree.SubElement(ln, q(A, "noFill"))
            fill_el = pr.find(q(A, "solidFill"))
            if fill_el is not None:
                fill_el.addnext(ln)
            else:
                pr.append(ln)
        _sanitize_sp_fill(el, want_solid=True)
        for rpr in list(el.iter(q(A, "rPr"))) + list(el.iter(q(A, "endParaRPr"))):
            if font_scaled:
                rpr.set("sz", sz_hundredths)
            old = rpr.find(q(A, "solidFill"))
            if old is not None:
                rpr.remove(old)
            fill = etree.SubElement(rpr, q(A, "solidFill"))
            if i == current:
                sc = etree.SubElement(fill, q(A, "schemeClr")); sc.set("val", "bg1")
            else:
                c = etree.SubElement(fill, q(A, "srgbClr")); c.set("val", rest_text)
    # 模板页签多于本章数时清空多余槽，避免残留「产品特色」等旧词
    for sp in leftovers:
        el = sp["el"]
        _replace_all_text(el, "")
        pr = _sp_pr(el)
        if pr is not None:
            for child in list(pr):
                if child.tag in (q(A, "solidFill"), q(A, "noFill")):
                    pr.remove(child)
            etree.SubElement(pr, q(A, "noFill"))
            old_ln = pr.find(q(A, "ln"))
            if old_ln is not None:
                pr.remove(old_ln)
            ln = etree.Element(q(A, "ln"))
            etree.SubElement(ln, q(A, "noFill"))
            pr.append(ln)
    parts[part] = dump(root)
    return {
        "slide": index,
        "status": "ok",
        "widths": widths_out,
        "gap": gap,
        "current": current,
        "expanded": expanded,
        "font_pt": round(font_pt, 2),
        "font_scaled": font_scaled,
        "min_needed": [round(x, 4) for x in needed],
        "slot_x0": round(slot_x0, 4),
        "slot_x1": round(slot_x1, 4),
        "need_confirm": need_confirm,
    }



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
    els = [s for num, name in rows for s in ((num, name) if num is not None else (name,))]
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
