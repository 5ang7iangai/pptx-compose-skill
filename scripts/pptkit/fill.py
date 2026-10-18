# -*- coding: utf-8 -*-
"""按文字槽替换形状里的文字，保留首段的字体和颜色。"""

from __future__ import annotations


from lxml import etree

from .ooxml import A, P, dump, parse, q, shape_text, slide_order

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _set_run_text(t_el: etree._Element, text: str) -> None:
    t_el.text = text
    if text[:1].isspace() or text[-1:].isspace():
        t_el.set(XML_SPACE, "preserve")


def _fill_paragraph(p_el: etree._Element, text: str) -> None:
    runs = [t for t in p_el.iter(q(A, "t"))]
    if not runs:
        r = etree.SubElement(p_el, q(A, "r"))
        t_el = etree.SubElement(r, q(A, "t"))
        _set_run_text(t_el, text)
        return
    _set_run_text(runs[0], text)
    for extra in runs[1:]:
        extra.text = ""


def _has_bullet(p_el: etree._Element) -> bool:
    p_pr = p_el.find(q(A, "pPr"))
    if p_pr is None:
        return False
    return any(child.tag in {q(A, "buChar"), q(A, "buAutoNum"), q(A, "buBlip")} for child in p_pr)


def _fill_with_breaks(p_el: etree._Element, lines: list[str]) -> None:
    """同一条项目符号里换行，避免每行都长出一个新符号。"""
    _fill_paragraph(p_el, lines[0])
    first = p_el.find(q(A, "r"))
    end = p_el.find(q(A, "endParaRPr"))
    for line in lines[1:]:
        br = etree.Element(q(A, "br"))
        if first is not None and first.find(q(A, "rPr")) is not None:
            br.append(etree.fromstring(etree.tostring(first.find(q(A, "rPr")))))
        clone = etree.fromstring(etree.tostring(first)) if first is not None else etree.Element(q(A, "r"))
        t_el = clone.find(q(A, "t"))
        if t_el is None:
            t_el = etree.SubElement(clone, q(A, "t"))
        _set_run_text(t_el, line)
        if end is not None:
            end.addprevious(br)
            end.addprevious(clone)
        else:
            p_el.append(br)
            p_el.append(clone)


def replace_shape(sp: etree._Element, text: str | None, paragraphs: list[str] | None,
                  style: dict | None = None) -> None:
    tx = sp.find(q(P, "txBody"))
    if tx is None:
        return
    paras = tx.findall(q(A, "p"))
    if not paras:
        return
    if paragraphs is None and text is not None and "\n" in text and _has_bullet(paras[0]):
        _fill_with_breaks(paras[0], text.split("\n"))
        for extra in paras[1:]:
            for t_el in extra.iter(q(A, "t")):
                t_el.text = ""
        return
    if paragraphs is None:
        paragraphs = text.split("\n") if text is not None else [""]
    for i, line in enumerate(paragraphs):
        if i < len(paras):
            _fill_paragraph(paras[i], line)
        else:
            clone = etree.fromstring(etree.tostring(paras[0]))
            _fill_paragraph(clone, line)
            tx.append(clone)
    for extra in paras[len(paragraphs) :]:
        for t_el in extra.iter(q(A, "t")):
            t_el.text = ""
    if style:
        from .fonts import unify_shape
        unify_shape(sp, style)



def emphasize_keywords(sp: etree._Element, text: str, keywords: list[str], *,
                       color: str = "006F68", bold: bool = True) -> None:
    """将整段写入导语框，并对 keywords 中的词加粗+主色（其余保持原 run 样式）。"""
    tx = sp.find(q(P, "txBody"))
    if tx is None or not text:
        return
    paras = tx.findall(q(A, "p"))
    if not paras:
        return
    p0 = paras[0]
    # 取首个 run 作样式模板
    runs = list(p0.iter(q(A, "r")))
    if not runs:
        _fill_paragraph(p0, text)
        return
    proto = etree.fromstring(etree.tostring(runs[0]))
    # 清空段落内 run，保留 pPr / endParaRPr
    for child in list(p0):
        if child.tag == q(A, "r"):
            p0.remove(child)
    # 按关键词切分
    parts: list[tuple[str, bool]] = [(text, False)]
    for kw in sorted(set(keywords), key=len, reverse=True):
        if not kw:
            continue
        nxt: list[tuple[str, bool]] = []
        for seg, on in parts:
            if on or kw not in seg:
                nxt.append((seg, on))
                continue
            i = 0
            while True:
                j = seg.find(kw, i)
                if j < 0:
                    if i < len(seg):
                        nxt.append((seg[i:], False))
                    break
                if j > i:
                    nxt.append((seg[i:j], False))
                nxt.append((kw, True))
                i = j + len(kw)
        parts = nxt
    end = p0.find(q(A, "endParaRPr"))
    for seg, on in parts:
        if not seg:
            continue
        r = etree.fromstring(etree.tostring(proto))
        t_el = r.find(q(A, "t"))
        if t_el is not None:
            t_el.text = seg
        rPr = r.find(q(A, "rPr"))
        if rPr is None:
            rPr = etree.Element(q(A, "rPr"))
            r.insert(0, rPr)
        if on:
            if bold:
                rPr.set("b", "1")
            # 字色
            old = rPr.find(q(A, "solidFill"))
            if old is not None:
                rPr.remove(old)
            sf = etree.SubElement(rPr, q(A, "solidFill"))
            c = etree.SubElement(sf, q(A, "srgbClr"))
            c.set("val", color)
        if end is not None:
            end.addprevious(r)
        else:
            p0.append(r)
    for extra in paras[1:]:
        for t_el in extra.iter(q(A, "t")):
            t_el.text = ""


def apply_map(parts: dict[str, bytes], mapping: dict) -> list[str]:
    notes = []
    order = slide_order(parts)
    for block in mapping["slides"]:
        index = int(block["slide"])
        if index < 1 or index > len(order):
            raise SystemExit(f"没有第 {index} 页")
        part = order[index - 1]["part"]
        root = parse(parts[part])
        shapes = [sp for sp in root.iter(q(P, "sp"))]
        for rep in block["replacements"]:
            needle = rep["match"]
            hits = [sp for sp in shapes if needle in shape_text(sp)]
            if not hits:
                raise SystemExit(f"第 {index} 页找不到包含「{needle}」的文字槽")
            if len(hits) > 1 and not rep.get("all"):
                preview = [shape_text(sp)[:40] for sp in hits]
                raise SystemExit(f"第 {index} 页「{needle}」命中 {len(hits)} 处：{preview}。若要全部替换，加 \"all\": true")
            for sp in hits:
                replace_shape(sp, rep.get("text"), rep.get("paragraphs"))
            notes.append(f"slide {index}: {needle} -> {len(hits)}")
        parts[part] = dump(root)
    return notes
