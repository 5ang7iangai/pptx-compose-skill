# -*- coding: utf-8 -*-
"""从模板抽出正文、强调、表格、图表各一套字体，填字时套用，最后再核对。"""

from __future__ import annotations

from collections import Counter

from lxml import etree

from .ooxml import A, P, EMU, absolute_shapes, parse, q, slide_order


def style_of(rpr: etree._Element | None) -> dict | None:
    """一个 run 的字体：东亚/西文字体、字号（百分之一磅）、是否加粗、字色。"""
    if rpr is None:
        return None
    latin = rpr.find(q(A, "latin"))
    ea = rpr.find(q(A, "ea"))
    solid = rpr.find(q(A, "srgbClr"))
    scheme = rpr.find(q(A, "schemeClr"))
    if solid is not None and solid.get("val"):
        color = solid.get("val").upper()
    elif scheme is not None and scheme.get("val"):
        color = "scheme:" + scheme.get("val")
    else:
        color = ""
    return {
        "ea": (ea.get("typeface") if ea is not None else "") or "",
        "latin": (latin.get("typeface") if latin is not None else "") or "",
        "sz": int(rpr.get("sz") or 0),
        "bold": rpr.get("b") in ("1", "true"),
        "color": color,
    }


def _key(style: dict) -> tuple:
    return (style["ea"], style["latin"], style["sz"], style["bold"], style["color"])


def _slide_size(parts: dict[str, bytes]) -> tuple[int, int]:
    sz = parse(parts["ppt/presentation.xml"]).find(q(P, "sldSz"))
    return int(sz.get("cx")), int(sz.get("cy"))


def _visible_runs(sp: etree._Element) -> list[tuple[dict, str]]:
    found = []
    tx = sp.find(q(P, "txBody"))
    if tx is None:
        return found
    for para in tx.findall(q(A, "p")):
        for run in para.findall(q(A, "r")):
            node = run.find(q(A, "t"))
            text = (node.text or "") if node is not None else ""
            if not text.strip():
                continue
            style = style_of(run.find(q(A, "rPr")))
            if style:
                found.append((style, text))
    return found


def _majority(styles: list[dict]) -> dict | None:
    if not styles:
        return None
    winner = Counter(_key(s) for s in styles).most_common(1)[0][0]
    return dict(zip(("ea", "latin", "sz", "bold", "color"), winner))


def dominant_style(sp: etree._Element) -> dict | None:
    return _majority([style for style, _text in _visible_runs(sp)])


def style_for_slot(sp: etree._Element, body: dict | None) -> dict | None:
    """导语套模板正文那一套。字号差超过 2 磅的卡片保持自己的字号，只在框内统一。"""
    own = dominant_style(sp)
    if not body:
        return own
    if own and own.get("sz") and body.get("sz") and abs(int(own["sz"]) - int(body["sz"])) > 200:
        return own
    return body


def _content(index: int, text: str) -> bool:
    from .profile import role_of
    return role_of(index, text) == "content"


def _body_shapes(root, slide_w: float, slide_h: float) -> list[dict]:
    """正文框：页面中部、宽度超过页宽 35% 的文字。顶栏标题和页脚不算。"""
    found = []
    for shape in absolute_shapes(root):
        if not shape["text"].strip():
            continue
        cy = shape["y"] + shape["h"] / 2
        if cy < slide_h * 0.22 or cy > slide_h * 0.88:
            continue
        if shape["w"] < slide_w * 0.35:
            continue
        found.append(shape)
    return found


def _table_runs(root) -> list[dict]:
    styles = []
    for cell in root.iter(q(A, "tc")):
        for run in cell.iter(q(A, "r")):
            node = run.find(q(A, "t"))
            if node is None or not (node.text or "").strip():
                continue
            style = style_of(run.find(q(A, "rPr")))
            if style:
                styles.append(style)
    return styles


def _chart_styles(parts: dict[str, bytes]) -> list[dict]:
    styles = []
    for name, blob in parts.items():
        if not (name.startswith("ppt/charts/chart") and name.endswith(".xml")):
            continue
        root = parse(blob)
        for rpr in list(root.iter(q(A, "defRPr"))) + list(root.iter(q(A, "rPr"))):
            style = style_of(rpr)
            if style and (style["ea"] or style["latin"] or style["sz"]):
                styles.append(style)
    return styles


def learn_font_roles(parts: dict[str, bytes]) -> dict:
    """正文取宽文字框里最常见的一套；强调取其中加粗或另着色的那一套；表格、图表各自取最常见的一套。"""
    cx, cy = _slide_size(parts)
    slide_w, slide_h = cx / EMU, cy / EMU
    body_runs: list[dict] = []
    for row in slide_order(parts):
        root = parse(parts[row["part"]])
        text = "".join(t.text or "" for t in root.iter(q(A, "t")))
        if not _content(row["index"], text):
            continue
        for shape in _body_shapes(root, slide_w, slide_h):
            body_runs.extend(style for style, _text in _visible_runs(shape["el"]))
    body = _majority(body_runs)
    emphasis = None
    if body:
        other = [s for s in body_runs if s["bold"] != body["bold"] or (s["color"] and s["color"] != body["color"])]
        emphasis = _majority(other)
    table = _majority([s for row in slide_order(parts) for s in _table_runs(parse(parts[row["part"]]))])
    chart_runs = _chart_styles(parts)
    chart = _majority(chart_runs)
    if chart is None and body:
        chart = {"ea": body["ea"], "latin": body["latin"], "sz": 0, "bold": False, "color": "", "from": "body"}
    elif chart is not None:
        chart = {**chart, "from": "chart"}
    return {"body": body, "emphasis": emphasis, "table": table, "chart": chart}


def paint_rpr(rpr: etree._Element, style: dict) -> None:
    """把一个 run 改成指定的那一套，字色空着就去掉显式颜色，沿用主题默认色。"""
    if not style:
        return
    if style.get("sz"):
        rpr.set("sz", str(int(style["sz"])))
    if style.get("bold"):
        rpr.set("b", "1")
    else:
        rpr.attrib.pop("b", None)
    for tag, key in (("latin", "latin"), ("ea", "ea")):
        face = style.get(key) or ""
        if not face:
            continue
        el = rpr.find(q(A, tag))
        if el is None:
            el = etree.SubElement(rpr, q(A, tag))
        el.set("typeface", face)
    for child in list(rpr):
        if child.tag == q(A, "solidFill"):
            rpr.remove(child)
    color = style.get("color") or ""
    if not color:
        return
    solid = etree.Element(q(A, "solidFill"))
    if color.startswith("scheme:"):
        etree.SubElement(solid, q(A, "schemeClr"), val=color.split(":", 1)[1])
    else:
        etree.SubElement(solid, q(A, "srgbClr"), val=color)
    latin = rpr.find(q(A, "latin"))
    if latin is not None:
        latin.addprevious(solid)
    else:
        rpr.append(solid)


def unify_shape(sp: etree._Element, style: dict) -> None:
    """这个文字框里每一段都改成同一套，并去掉多余的旧 run，避免留下模板里另一套字。"""
    tx = sp.find(q(P, "txBody"))
    if tx is None or not style:
        return
    for para in tx.findall(q(A, "p")):
        runs = para.findall(q(A, "r"))
        if not runs:
            continue
        first = runs[0]
        rpr = first.find(q(A, "rPr"))
        if rpr is None:
            rpr = etree.Element(q(A, "rPr"))
            first.insert(0, rpr)
        paint_rpr(rpr, style)
        for extra in runs[1:]:
            para.remove(extra)
        end = para.find(q(A, "endParaRPr"))
        if end is not None:
            paint_rpr(end, style)


def _match(style: dict, role: dict | None) -> bool:
    if not role:
        return False
    if role.get("ea") and style["ea"] and style["ea"] != role["ea"]:
        return False
    if role.get("latin") and style["latin"] and style["latin"] != role["latin"]:
        return False
    if role.get("sz") and style["sz"] and style["sz"] != int(role["sz"]):
        return False
    if bool(style["bold"]) != bool(role.get("bold")):
        return False
    want = role.get("color") or ""
    got = style["color"] or ""
    return got == want


def _split_sentences(shapes: list[dict]) -> list[str]:
    """正文框里连续几段都以句号收尾，就是把一段话拆成了几行。"""
    issues = []
    for shape in shapes:
        tx = shape["el"].find(q(P, "txBody"))
        if tx is None:
            continue
        lines = []
        for para in tx.findall(q(A, "p")):
            text = "".join(t.text or "" for t in para.iter(q(A, "t"))).strip()
            if text:
                lines.append(text)
        if len(lines) >= 2 and all(line.endswith(("。", "！", "？")) for line in lines):
            issues.append(shape["name"] or "正文")
    return issues


def check_font_roles(parts: dict[str, bytes], roles: dict | None) -> list[str]:
    """正文、表格、图表各自只应出现模板里学到的那一套。强调色只允许强调那一套。"""
    roles = roles or {}
    body, emphasis, table, chart = roles.get("body"), roles.get("emphasis"), roles.get("table"), roles.get("chart")
    cx, cy = _slide_size(parts)
    slide_w, slide_h = cx / EMU, cy / EMU
    issues = []
    for row in slide_order(parts):
        root = parse(parts[row["part"]])
        text = "".join(t.text or "" for t in root.iter(q(A, "t")))
        if not _content(row["index"], text):
            continue
        page = row["index"]
        shapes = _body_shapes(root, slide_w, slide_h)
        for shape in shapes:
            runs = _visible_runs(shape["el"])
            if body:
                bad = [sample for style, sample in runs if not _match(style, body) and not _match(style, emphasis)]
                if bad:
                    issues.append(f"第 {page} 页正文「{bad[0][:14]}」和模板正文不是同一套字体")
            elif len({_key(style) for style, _sample in runs}) > 2:
                issues.append(f"第 {page} 页正文出现超过两套字体")
        for name in _split_sentences(shapes):
            issues.append(f"第 {page} 页「{name}」把正文拆成了多句分行，应合成一段")
        if table:
            for style, _sample in ((s, "") for s in _table_runs(root)):
                if not _match(style, table):
                    issues.append(f"第 {page} 页表格字体和模板表格不是同一套")
                    break
        faces = []
        for grp in root.iter(q(P, "grpSp")):
            nv = grp.find(q(P, "nvGrpSpPr"))
            label = nv.find(q(P, "cNvPr")).get("name") if nv is not None and nv.find(q(P, "cNvPr")) is not None else ""
            if label != "结构图":
                continue
            for style, _sample in _visible_runs_in(grp):
                faces.append(style["ea"] or style["latin"])
        if len(set(faces)) > 1:
            issues.append(f"第 {page} 页图表用了多种字体：{'、'.join(sorted(set(faces)))}")
        elif faces and chart and chart.get("ea") and faces[0] and faces[0] != chart["ea"]:
            issues.append(f"第 {page} 页图表字体是「{faces[0]}」，模板图表是「{chart['ea']}」")
    return issues


def _visible_runs_in(el: etree._Element) -> list[tuple[dict, str]]:
    found = []
    for run in el.iter(q(A, "r")):
        node = run.find(q(A, "t"))
        text = (node.text or "") if node is not None else ""
        if not text.strip():
            continue
        style = style_of(run.find(q(A, "rPr")))
        if style:
            found.append((style, text))
    return found
