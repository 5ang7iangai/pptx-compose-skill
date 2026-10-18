"""整套新编时把撰写结果填进克隆页：认出标题槽和正文槽，按原格式替换文字，备注写进备注页。

认槽规则（够用即可，填完看预览）：
    标题  标题占位符（title / ctrTitle，含位置继承自版式的）；没有时取页面上方 22% 内、
          最靠上、宽度超过页宽 10% 的文字（封面放宽到上方 60%，宽度要超过 20%）
    小节  标题下方、仍在上方 22% 内的另一行短文字（如顶栏章名下的「（一）整体思路」），本页标题写这里，章名写顶栏
    图注  正文区里没被当成槽的短文字（≤ 30 字），多是旧图的说明；清旧图时一起删
    卡片  宽度 ≥ 20% 页宽、尺寸相近（宽差 < 0.3、高差 < 0.2 英寸）的 2 个以上文字框，按先上后左排序，一条要点一张
    导语  其余宽度 ≥ 30% 页宽的文字里面积最大的那个；没有卡片时导语和全部要点都写在这里
"""

from __future__ import annotations

import math
from pathlib import Path

from lxml import etree

from .fill import replace_shape
from .fonts import style_for_slot
from .ooxml import EMU, A, P, absolute_shapes, dump, parse, q, shape_text, slide_order


def _placeholder(el) -> str:
    ph = el.find(".//" + q(P, "ph"))
    return (ph.get("type") or "body") if ph is not None else ""


def _series(shapes: list[dict], slide_w: float) -> list[dict]:
    """尺寸相近的一组宽文字框（要点卡片），取成员最多的一组。"""
    wide = [s for s in shapes if s["w"] >= slide_w * 0.2]
    best: list[dict] = []
    for s in wide:
        group = [o for o in wide if abs(o["w"] - s["w"]) < 0.3 and abs(o["h"] - s["h"]) < 0.2]
        if len(group) > len(best):
            best = group
    return sorted(best, key=lambda s: (round(s["y"], 1), s["x"])) if len(best) >= 2 else []


def find_slots(root, slide_w: float, slide_h: float, title_zone: float = 0.22, title_min_w: float = 0.1) -> dict:
    """title_min_w：非占位符标题的最小宽度（占页宽）。正文页标题如「1.1工作要求」只有 15% 宽，
    标题下方那排页签（问题及需求 / 服务思路…）约 7%，取 10% 能分开。"""
    shapes = [s for s in absolute_shapes(root) if s["text"].strip() or _placeholder(s["el"])]
    title = next((s for s in shapes if _placeholder(s["el"]) in ("title", "ctrTitle")), None)
    if title is None:  # 占位符位置继承自版式、本身没有坐标时，absolute_shapes 收不到
        el = next((e for e in root.iter(q(P, "sp")) if _placeholder(e) in ("title", "ctrTitle")), None)
        if el is not None:
            nv = el.find(".//" + q(P, "cNvPr"))
            title = {"el": el, "name": nv.get("name") if nv is not None else "", "text": shape_text(el),
                     "x": 0.0, "y": 0.0, "w": slide_w, "h": 0.0}
    if title is None:
        tops = [s for s in shapes if s["y"] < slide_h * title_zone and s["w"] > slide_w * title_min_w
                and len(s["text"]) <= 40]
        title = min(tops, key=lambda s: s["y"], default=None)
    subtitle = None
    if title is not None and title["h"] > 0:  # 顶栏章名下面还有一行本页标题，如「（一）整体思路」
        below = [s for s in shapes if s is not title and title["y"] + title["h"] * 0.5 < s["y"] < slide_h * title_zone
                 and s["w"] > slide_w * title_min_w and 0 < len(s["text"].strip()) <= 40]
        subtitle = min(below, key=lambda s: s["y"], default=None)
    rest = [s for s in shapes if s is not title and s is not subtitle]
    cards = _series(rest, slide_w)
    intro = max((s for s in rest if s not in cards and s["w"] >= slide_w * 0.3),
                key=lambda s: s["w"] * s["h"], default=None)
    captions = [s for s in rest if s not in cards and s is not intro and not _placeholder(s["el"])
                and 0 < len(s["text"].strip()) <= 30 and slide_h * title_zone < s["y"] + s["h"] / 2 < slide_h * 0.9]
    return {"title": title, "subtitle": subtitle, "intro": intro, "cards": cards, "captions": captions}


def _line_chars(slot: dict) -> int:
    """框里一行大约放几个汉字（按首个字号，左右各留 0.1 英寸边距）。"""
    sz = next((int(r.get("sz")) for r in slot["el"].iter(q(A, "rPr")) if r.get("sz")), 1800) / 100
    return max(8, int((slot["w"] - 0.2) / (sz / 72)))


def text_width(text: str) -> float:
    """按汉字宽度计：西文、数字、空格约半个字。"""
    return sum(1 if ord(c) > 0x2E80 else 0.55 for c in text)


def _lines(paras: list[str], per_line: int) -> int:
    """每段至少占一行；段尾空段不算。"""
    while paras and not paras[-1].strip():
        paras = paras[:-1]
    return sum(max(1, math.ceil(text_width(p) / per_line)) for p in paras)


COVER_MAX_W = 0.75  # 封面标题框最宽占页宽的比例；更长就按语义断成两行，不横向占满整页


def cover_title_room(parts: dict[str, bytes], slide_w: float, slide_h: float) -> int:
    """封面标题能放几个汉字宽：框宽按不超过页宽 75% 算，最多两行。认不出标题时返回 0。"""
    title = find_slots(parse(parts[slide_order(parts)[0]["part"]]), slide_w, slide_h, 0.6, 0.2)["title"]
    if title is None:
        return 0
    sz = _first_sz(title["el"])
    width = min(title["w"], slide_w * COVER_MAX_W)
    return max(8, int((width - 0.2) / (sz / 72))) * 2


def _first_sz(el, default: int = 1800) -> float:
    return next((int(r.get("sz")) for r in el.iter(q(A, "rPr")) if r.get("sz")), default) / 100


_BREAK_AFTER = "，,、：:；;"
_BREAK_BEFORE = ("及", "与", "和", "暨", "并", "——")
_NO_LINE_START = "，,、。：:；;）)》」”"
_NO_LINE_END = "（(《「“"
_PAIRS = (("“", "”"), ("《", "》"), ("（", "）"), ("(", ")"), ("「", "」"))


def split_title(text: str) -> list[str]:
    """长标题按语义断成两行：优先断在标点后、「及/与/和/暨」前，靠近中间；不拆开西文单词和数字。"""
    text = text.strip()
    n = len(text)
    if n < 6:
        return [text]
    best, best_score = n // 2, None
    for i in range(max(2, math.ceil(n * 0.3)), min(n - 1, int(n * 0.7)) + 1):
        a, b = text[i - 1], text[i]
        score = abs(i - n / 2)
        if a in _BREAK_AFTER:
            score -= 8
        if text[i:].startswith(_BREAK_BEFORE):
            score -= 6
        if a.isascii() and a.isalnum() and b.isascii() and b.isalnum():
            score += 100
        if b in _NO_LINE_START or a in _NO_LINE_END:
            score += 100
        head = text[:i]
        if any(head.count(o) > head.count(c) for o, c in _PAIRS):  # 不断在引号、书名号、括号里面
            score += 50
        if a in "”》）)」":
            score -= 4
        if b in "（(" and text.rstrip().endswith(("）", ")")):  # 末尾括号注释整体放第二行
            score -= 5
        if best_score is None or score < best_score:
            best, best_score = i, score
    first, second = text[:best].rstrip(), text[best:].lstrip()
    if first and first[-1] in "，,":
        first = first[:-1]
    return [first, second]


def fit_cover_title(slot: dict, text: str, slide_w: float, slide_h: float) -> dict:
    """封面标题框收窄到不超过页宽 75%（以原框中心居中），放不下一行就按语义断成两行，
    文字在原标题区域内上下居中。字号先保持，两行仍放不下才略缩（最多到原来的 80%）。返回实际排法。"""
    sp = slot["el"]
    xfrm = sp.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}")
    sz = _first_sz(sp)
    ins = 0.2
    body = sp.find(".//" + q(A, "bodyPr"))
    if body is not None:
        ins = (int(body.get("lIns", 91440)) + int(body.get("rIns", 91440))) / EMU
    max_w = slide_w * COVER_MAX_W
    lines = [text.strip()]
    if text_width(text) * sz / 72 + ins > max_w:
        lines = split_title(text)
    longest = max(text_width(t) for t in lines)
    need = longest * sz / 72 + ins
    if need > max_w:  # 两行仍超宽，略缩字号
        sz = max(sz * 0.8, (max_w - ins) * 72 / longest)
        sz = math.floor(sz / 2) * 2
        need = longest * sz / 72 + ins
    new_w = min(max_w, max(need + 0.3, slide_w * 0.5))
    new_w = min(new_w, max(slot["w"], need)) if slot["w"] < max_w else new_w
    line_h = sz * 1.2 / 72
    new_h = max(slot["h"], len(lines) * line_h + 0.2)
    cx, cy = slot["x"] + slot["w"] / 2, slot["y"] + slot["h"] / 2
    replace_shape(sp, None, lines)
    for el in sp.iter(q(A, "rPr"), q(A, "endParaRPr")):
        if el.get("sz"):
            el.set("sz", str(int(sz * 100)))
    for p_el in sp.iter(q(A, "p")):
        p_pr = p_el.find(q(A, "pPr"))
        if p_pr is None:
            p_pr = etree.Element(q(A, "pPr"))
            p_el.insert(0, p_pr)
        p_pr.set("algn", "ctr")
    if body is not None:
        body.set("wrap", "square")
        body.set("anchor", "ctr")
    moved = False
    if xfrm is not None and sp.getparent() is not None and sp.getparent().tag == q(P, "spTree"):
        off, ext = xfrm.find(q(A, "off")), xfrm.find(q(A, "ext"))
        if off is not None and ext is not None:
            off.set("x", str(int((cx - new_w / 2) * EMU)))
            off.set("y", str(int((cy - new_h / 2) * EMU)))
            ext.set("cx", str(int(new_w * EMU)))
            ext.set("cy", str(int(new_h * EMU)))
            moved = True
    return {"lines": lines, "sz": sz, "width_ratio": round((new_w if moved else slot["w"]) / slide_w, 2),
            "resized": moved, "fits": need <= max_w + 0.01}


def _paras(el) -> list[str]:
    return ["".join(t.text or "" for t in p.iter(q(A, "t"))) for p in el.iter(q(A, "p"))]


def page_capacity(parts: dict[str, bytes], index: int, slide_w: float, slide_h: float) -> dict:
    """样例页能装多少字：标题原文、导语框原字数和行数、每张卡片原字数。页纲规划和校正字数都用它。
    单框页的导语和要点各占一段，段尾不满也占一行，所以除了字数还要按行数卡。"""
    slots = find_slots(parse(parts[slide_order(parts)[index - 1]["part"]]), slide_w, slide_h)
    intro = slots["intro"]
    cap = {"title": slots["title"]["text"].strip()[:30] if slots["title"] else "",
           "intro_chars": len(intro["text"].strip()) if intro else 0,
           "cards": [len(c["text"].strip()) for c in slots["cards"]]}
    if intro:
        cap["line_chars"] = _line_chars(intro)
        cap["intro_lines"] = _lines(_paras(intro["el"]), cap["line_chars"])
    return cap


def fit_plan(plan: dict, cap: dict) -> dict:
    """按样例页容量改写页纲的字数要求：卡片页一张卡一条主句；单框页导语和要点合计不超过原框字数。"""
    plan = dict(plan or {})
    cards, room = cap["cards"], cap["intro_chars"]
    if cards:
        plan.update(intro_target_chars=room, bullet_count=len(cards),
                    bullet_target_chars=max(8, round(sum(cards) / len(cards))),
                    max_total_chars=room + sum(cards), sub_bullets=False)
    else:
        # 没有卡片时，正文是一段话，不拆成导语加几条要点
        plan.update(intro_target_chars=room, bullet_count=0, bullet_target_chars=0,
                    max_total_chars=room, sub_bullets=False)
    return plan


def bullet_texts(content: dict, with_subs: bool = True) -> list[str]:
    """with_subs=False 时只取要点主句（卡片装不下子要点）。"""
    out = []
    for b in content.get("bullets") or []:
        if isinstance(b, dict):
            subs = [s for s in b.get("sub_bullets") or [] if s] if with_subs else []
            out.append(b.get("text", "") + ("：" + "；".join(subs) if subs else ""))
        elif isinstance(b, str):
            out.append(b)
    return [t for t in out if t]


def _too_long(slot: dict, new: str) -> bool:
    """新字数明显超过模板原字数，多半装不下。"""
    old = len(slot["text"].strip())
    return len(new) > max(old * 1.3, old + 20)


def _notes_part(parts: dict, slide_part: str) -> str | None:
    rels = parts.get(slide_part.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels", b"").decode("utf-8")
    for chunk in rels.split("<Relationship ")[1:]:
        if "notesSlide" in chunk and 'Target="' in chunk:
            return "ppt/notesSlides/" + Path(chunk.split('Target="')[1].split('"')[0]).name
    return None


def cover_footers(root, title_el, slide_h: float) -> list[dict]:
    """封面标题以下的短文字，通常是模板留下的组织落款和日期。页面上半部的标识文字不动。"""
    found = []
    for shape in absolute_shapes(root):
        if title_el is not None and shape["el"] is title_el:
            continue
        text = shape["text"].strip()
        if not text or len(text) > 40 or _placeholder(shape["el"]):
            continue
        if shape["y"] + shape["h"] / 2 < slide_h * 0.55:
            continue
        found.append(shape)
    return found


def _one_paragraph(content: dict) -> str:
    """没有卡片时，导语和要点收成一段，去掉材料里的换行。"""
    parts: list[str] = []
    intro = (content.get("intro") or "").replace("\r", "").replace("\n", "").strip()
    if intro:
        parts.append(intro)
    for bit in bullet_texts(content):
        bit = bit.replace("\n", "").strip()
        if bit:
            parts.append(bit)
    return "".join(parts)


def fill_page(parts: dict[str, bytes], index: int, content: dict, slide_w: float, slide_h: float,
              cover: bool = False, clear_captions: bool = False, body_style: dict | None = None) -> dict:
    """cover=True 只换标题（封面标题常在页面中部）；没给 subtitle 时清掉标题下方的组织落款和日期。
    页上有两级标题时，content["section"] 进顶栏、title 进本页标题。
    clear_captions=True（样例页旧图要清掉时）连同旧图的短说明文字一起删。返回填了哪些槽，写进任务报告方便核对。"""
    part = slide_order(parts)[index - 1]["part"]
    root = parse(parts[part])
    slots = find_slots(root, slide_w, slide_h, *((0.6, 0.2) if cover else (0.22, 0.1)))
    body = not cover
    done: dict = {"slide": index}
    if slots["title"] is not None and content.get("title"):
        sub = slots["subtitle"] if body else None
        if sub is not None:
            replace_shape(sub["el"], content["title"], None)
            done["subtitle"] = sub["name"]
            if content.get("section"):
                replace_shape(slots["title"]["el"], content["section"], None)
                done["section"] = slots["title"]["name"]
        else:
            if cover:
                layout = fit_cover_title(slots["title"], content["title"], slide_w, slide_h)
                done["cover_title"] = layout
                if not layout["fits"]:
                    done["overflow"] = [slots["title"]["name"]]
            else:
                replace_shape(slots["title"]["el"], content["title"], None)
        done["title"] = slots["title"]["name"]
    if cover:
        footers = cover_footers(root, slots["title"]["el"] if slots["title"] else None, slide_h)
        line = (content.get("subtitle") or "").strip()
        if line and footers:
            replace_shape(footers[0]["el"], line, None)
            done["subtitle"] = footers[0]["name"]
            footers = footers[1:]
        if footers:
            done["subtitle_cleared"] = [s["text"].strip() for s in footers]
            for shape in footers:
                replace_shape(shape["el"], "", None)
    if body and clear_captions and slots["captions"]:
        for cap in slots["captions"]:
            cap["el"].getparent().remove(cap["el"])
        done["captions_cleared"] = [c["text"].strip() for c in slots["captions"]]
    if body:
        cards = slots["cards"]
        bullets = bullet_texts(content, with_subs=not cards)
        overflow = []
        if cards:
            for card, text in zip(cards, bullets + [""] * len(cards)):
                replace_shape(card["el"], text, None, style_for_slot(card["el"], body_style))
                if _too_long(card, text):
                    overflow.append(card["name"])
            done["cards"] = [c["name"] for c in cards]
            if len(bullets) > len(cards):
                done["bullets_dropped"] = bullets[len(cards):]
            paras = [content["intro"]] if content.get("intro") else []
        else:
            paras = [text for text in [_one_paragraph(content)] if text]
        if slots["intro"] is not None and paras:
            per_line = _line_chars(slots["intro"])
            old_lines = _lines(_paras(slots["intro"]["el"]), per_line)
            replace_shape(slots["intro"]["el"], None, paras, style_for_slot(slots["intro"]["el"], body_style))
            done["intro"] = slots["intro"]["name"]
            if _too_long(slots["intro"], "".join(paras)) or _lines(paras, per_line) > old_lines:
                overflow.append(slots["intro"]["name"])
        if overflow:
            done["overflow"] = overflow
    parts[part] = dump(root)
    notes = _notes_part(parts, part)
    if content.get("notes") and notes in parts:
        nroot = parse(parts[notes])
        slot = next((sp for sp in nroot.iter(q(P, "sp")) if _placeholder(sp) == "body"), None)
        if slot is not None:
            replace_shape(slot, content["notes"], None)
            parts[notes] = dump(nroot)
            done["notes"] = True
    return done


def slide_size(parts: dict[str, bytes]) -> tuple[float, float]:
    sz = parse(parts["ppt/presentation.xml"]).find(q(P, "sldSz"))
    return int(sz.get("cx")) / EMU, int(sz.get("cy")) / EMU
