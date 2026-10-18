"""导语/正文与结构图不得重叠：交付前全稿扫描。"""

from __future__ import annotations

from .autofill import _line_chars, _lines, find_slots, slide_size
from .ooxml import A, EMU, P, parse, q, slide_order

# 新贴图时图顶边相对导语有效底边的最小间隙（英寸）
GAP = 0.15
# 几何上允许的贴齐误差（模板常见图顶≈导语框底）
FLUSH_TOL = 0.02


def _box(el) -> dict | None:
    xfrm = el.find(f"{q(P, 'spPr')}/{q(A, 'xfrm')}")
    if xfrm is None:
        xfrm = el.find(f"{q(P, 'grpSpPr')}/{q(A, 'xfrm')}")
    if xfrm is None:
        return None
    off, ext = xfrm.find(q(A, "off")), xfrm.find(q(A, "ext"))
    if off is None or ext is None:
        return None
    return {
        "x": int(off.get("x", 0)) / EMU,
        "y": int(off.get("y", 0)) / EMU,
        "w": int(ext.get("cx", 0)) / EMU,
        "h": int(ext.get("cy", 0)) / EMU,
    }


def _is_chrome(box: dict, slide_w: float, slide_h: float) -> bool:
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    cx, cy = x + w / 2, y + h / 2
    if cx < 0 or cy < 0 or cx > slide_w or cy > slide_h:
        return True
    if cy < slide_h * 0.22 and h < slide_h * 0.2:
        return True
    if w >= slide_w * 0.85 and h <= slide_h * 0.15 and y >= slide_h * 0.8:
        return True
    if w >= slide_w * 0.9 and h >= slide_h * 0.9:
        return True
    return False


def _content_diagrams(root, slide_w: float, slide_h: float) -> list[dict]:
    found = []
    for el in root.iter(q(P, "pic"), q(P, "grpSp")):
        nv = el.find(".//" + q(P, "cNvPr"))
        name = nv.get("name") if nv is not None else ""
        box = _box(el)
        if not box or box["h"] < 0.4:
            continue
        if name == "结构图":
            found.append({**box, "name": name})
            continue
        if _is_chrome(box, slide_w, slide_h):
            continue
        if box["y"] > slide_h * 0.28 and box["w"] >= slide_w * 0.35 and box["h"] >= slide_h * 0.25:
            found.append({**box, "name": name or "内容图"})
    return found


def _intro_metrics(intro: dict) -> tuple[float, float, int, int]:
    """返回 (框底边, 文字有效底边, 需要行数, 框内可放行数)。"""
    text = (intro.get("text") or "").strip()
    per = _line_chars(intro)
    need = _lines([text], per) if text else 0
    sz = next((int(r.get("sz")) for r in intro["el"].iter(q(A, "rPr")) if r.get("sz")), 1600) / 100
    line_h = max(sz * 1.35 / 72, 0.22)
    fit = max(1, int((intro["h"] - 0.08) / line_h))
    box_bottom = intro["y"] + intro["h"]
    eff = intro["y"] + need * line_h + 0.05 if need > fit else box_bottom
    return box_bottom, eff, need, fit


def assert_bbox_clears_intro(parts: dict[str, bytes], slide_index: int, bbox: dict) -> None:
    """贴图前调用：bbox 顶边须在导语有效底边之下并留 GAP。"""
    slide_w, slide_h = slide_size(parts)
    root = parse(parts[slide_order(parts)[slide_index - 1]["part"]])
    intro = find_slots(root, slide_w, slide_h).get("intro")
    if not intro or not (intro.get("text") or "").strip():
        return
    if intro["y"] > slide_h * 0.45:  # 封面落款等，不是正文导语
        return
    box_bottom, eff, need, fit = _intro_metrics(intro)
    bottom = max(box_bottom, eff)
    gap = bbox["y"] - bottom
    if gap < GAP - 1e-3:
        raise ValueError(
            f"第 {slide_index} 页结构图顶边 y={bbox['y']:.2f} 侵入导语区"
            f"（导语有效底边 {bottom:.2f}，间隙 {gap:.2f} < {GAP}；"
            f"导语约 {need} 行、框约能放 {fit} 行）。请下移 bbox 或缩短导语。"
        )


def text_diagram_overlaps(parts: dict[str, bytes]) -> list[str]:
    """全稿扫描。报错条件：
    1) 结构图顶边侵入导语框，或与导语有效底边间隙 < GAP（默认 0.15″）；
    2) 导语字数超出框内行数，溢出文字会画到图上。
    间隙不足与硬重叠同等对待，不得静默通过。
    """
    errors = []
    slide_w, slide_h = slide_size(parts)
    for i, row in enumerate(slide_order(parts), 1):
        root = parse(parts[row["part"]])
        intro = find_slots(root, slide_w, slide_h).get("intro")
        if not intro or not (intro.get("text") or "").strip():
            continue
        if intro["y"] > slide_h * 0.45:
            continue
        diagrams = _content_diagrams(root, slide_w, slide_h)
        if not diagrams:
            continue
        box_bottom, eff, need, fit = _intro_metrics(intro)
        bottom = max(box_bottom, eff)
        if need > fit:
            errors.append(
                f"第 {i} 页导语约 {need} 行、框约能放 {fit} 行，文字会溢出到图上；"
                f"请删短导语或加大导语框并下移结构图"
            )
        for d in diagrams:
            gap = d["y"] - bottom
            if d["y"] < box_bottom - FLUSH_TOL:
                errors.append(
                    f"第 {i} 页「{d['name']}」侵入导语框"
                    f"（导语底 {box_bottom:.2f}，图顶 {d['y']:.2f}，重叠 {box_bottom - d['y']:.2f} 英寸）"
                )
            elif gap < GAP - 1e-3:
                errors.append(
                    f"第 {i} 页「{d['name']}」与导语纵向间隙不足"
                    f"（导语有效底边 {bottom:.2f}，图顶 {d['y']:.2f}，间隙 {gap:.2f} < {GAP}）；"
                    f"请下移结构图或缩短导语"
                )
            elif need > fit and d["y"] < eff - FLUSH_TOL:
                errors.append(
                    f"第 {i} 页「{d['name']}」压住溢出的导语文字"
                    f"（导语有效底边 {eff:.2f}，图顶 {d['y']:.2f}）"
                )
    return errors


def content_band_narrow(parts: dict[str, bytes], min_ratio: float = 0.70) -> list[str]:
    """正文页导语下方主内容（结构图或卡片组）外包框宽度占内容区过窄时告警。

    目录/封面/致谢跳过。阈值：外包框宽 < 页宽*min_ratio 且明显偏在一侧。
    """
    errors = []
    slide_w, slide_h = slide_size(parts)
    content_w = slide_w * 0.92
    for i, row in enumerate(slide_order(parts), 1):
        root = parse(parts[row["part"]])
        plain = "".join((t.text or "") for t in root.iter(q(A, "t")))
        compact = "".join(plain.split()).upper()
        if "目录" in plain or "CONTENTS" in compact:
            continue
        if "谢谢" in plain.replace(" ", "") or "谢  谢" in plain:
            continue
        # cover: little body text below mid
        intro = find_slots(root, slide_w, slide_h).get("intro")
        if intro and intro["y"] > slide_h * 0.45:
            continue
        boxes = []
        for el in root.iter(q(P, "pic"), q(P, "grpSp")):
            nv = el.find(".//" + q(P, "cNvPr"))
            name = nv.get("name") if nv is not None else ""
            box = _box(el)
            if not box or box["y"] < slide_h * 0.28:
                continue
            if name == "结构图" or (box["w"] >= slide_w * 0.25 and box["h"] >= slide_h * 0.2):
                boxes.append(box)
        # cards cluster
        slots = find_slots(root, slide_w, slide_h)
        cards = slots.get("cards") or []
        if len(cards) >= 2:
            xs = [c["x"] for c in cards]
            rights = [c["x"] + c["w"] for c in cards]
            boxes.append({
                "x": min(xs), "y": min(c["y"] for c in cards),
                "w": max(rights) - min(xs), "h": 1.0,
            })
        if not boxes:
            continue
        # union
        x0 = min(b["x"] for b in boxes)
        x1 = max(b["x"] + b["w"] for b in boxes)
        span = x1 - x0
        if span >= content_w * min_ratio:
            continue
        # biased left or right with large empty
        left_empty = x0
        right_empty = slide_w - x1
        if max(left_empty, right_empty) >= slide_w * 0.28:
            side = "右侧" if right_empty > left_empty else "左侧"
            errors.append(
                f"第 {i} 页主内容区偏窄（宽 {span:.1f}″ / 页宽 {slide_w:.1f}″），"
                f"{side}空白偏大；请将卡片或结构图横向铺满或居中对称"
            )
    return errors


def empty_shell_cards(parts: dict[str, bytes], min_h: float = 1.8, max_title_chars: int = 48) -> list[str]:
    """并列卡不得只有标题无正文：高卡片内仅一行短文案视为空壳。"""
    errors = []
    slide_w, slide_h = slide_size(parts)
    for i, row in enumerate(slide_order(parts), 1):
        root = parse(parts[row["part"]])
        plain = "".join((t.text or "") for t in root.iter(q(A, "t")))
        if "目录" in plain or "CONTENTS" in "".join(plain.split()).upper():
            continue
        slots = find_slots(root, slide_w, slide_h)
        cards = slots.get("cards") or []
        if len(cards) < 2:
            continue
        for c in cards:
            if c["h"] < min_h or c["y"] < slide_h * 0.28:
                continue
            # text whose center falls in card
            lines = []
            for sp in root.iter(q(P, "sp")):
                box = _box(sp)
                if not box:
                    continue
                cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
                if not (c["x"] <= cx <= c["x"] + c["w"] and c["y"] <= cy <= c["y"] + c["h"]):
                    continue
                t = "".join((el.text or "") for el in sp.iter(q(A, "t"))).strip()
                if t:
                    lines.append(t)
            joined = "\n".join(lines).strip()
            paras = [p for p in joined.replace("\r", "").split("\n") if p.strip()]
            # single short line in a tall card
            if len(paras) <= 1 and len(joined) <= max_title_chars:
                preview = (joined[:18] + "…") if len(joined) > 18 else (joined or "（无字）")
                errors.append(
                    f"第 {i} 页卡片「{preview}」只有标题/空壳（高 {c['h']:.1f}″），"
                    f"须有标题+至少一行说明，禁止只有标题的空壳卡"
                )
    return errors


def peer_row_widths(parts: dict[str, bytes], max_ratio: float = 0.12) -> list[str]:
    """同一行流程/时间轴/并列节点（含强调色块）宽度须一致；差异超过阈值报错。"""
    errors = []
    slide_w, slide_h = slide_size(parts)
    for i, row in enumerate(slide_order(parts), 1):
        root = parse(parts[row["part"]])
        peers: list[dict] = []
        # 结构图形状组内的同行高卡片
        for grp in root.iter(q(P, "grpSp")):
            nv = grp.find(".//" + q(P, "cNvPr"))
            if nv is None or nv.get("name") != "结构图":
                continue
            for sp in grp.iter(q(P, "sp")):
                box = _box(sp)
                if not box:
                    continue
                if box["h"] < 1.2 or box["w"] < 0.55 or box["w"] > slide_w * 0.45:
                    continue
                peers.append(box)
        # 正文区原生并列卡
        slots = find_slots(root, slide_w, slide_h)
        for c in slots.get("cards") or []:
            if c["h"] >= 1.2 and c["y"] > slide_h * 0.28:
                peers.append(c)
        if len(peers) < 2:
            continue
        # cluster by similar y (same row)
        peers = sorted(peers, key=lambda b: (round(b["y"], 1), b["x"]))
        row_boxes: list[dict] = []
        rows: list[list[dict]] = []
        for b in peers:
            if not row_boxes:
                row_boxes = [b]
                continue
            # same row if vertical centers close
            cy = b["y"] + b["h"] / 2
            ref = row_boxes[0]
            rcy = ref["y"] + ref["h"] / 2
            if abs(cy - rcy) <= max(ref["h"], b["h"]) * 0.35:
                row_boxes.append(b)
            else:
                rows.append(row_boxes)
                row_boxes = [b]
        if row_boxes:
            rows.append(row_boxes)
        for rb in rows:
            if len(rb) < 2:
                continue
            widths = [b["w"] for b in rb]
            lo, hi = min(widths), max(widths)
            if hi <= 0:
                continue
            # 表格式分栏（名列明显更窄）不是对等节点行
            if lo < hi * 0.55:
                continue
            hs = [b["h"] for b in rb]
            if min(hs) < max(hs) * 0.75:
                continue
            if (hi - lo) / hi > max_ratio:
                errors.append(
                    f"第 {i} 页同行节点宽度不一致"
                    f"（{lo:.2f}″–{hi:.2f}″，差 {(hi - lo) / hi * 100:.0f}% > {max_ratio * 100:.0f}%）；"
                    f"流程/时间轴/并列卡（含强调色块）须等宽"
                )
    return errors


def section_tabs_gaps(
    parts: dict[str, bytes],
    *,
    max_gap: float = 0.005,
    max_overlap: float = 0.005,
) -> list[str]:
    """正文顶栏章节页签须 edge-to-edge（gap≈0）：有缝或重叠则报错。

    识别：标题带内、高度较小、同一水平中线、数量≥3 的短导航形状。
    """
    errors = []
    slide_w, slide_h = slide_size(parts)
    for i, row in enumerate(slide_order(parts), 1):
        root = parse(parts[row["part"]])
        from .slides import absolute_shapes
        cands = []
        for s in absolute_shapes(root):
            if s["y"] > slide_h * 0.22 or s["h"] > 0.55 or s["h"] < 0.12:
                continue
            if s["w"] < 0.45 or s["w"] > 2.8:
                continue
            if not (s.get("text") or "").strip():
                continue
            cands.append(s)
        if len(cands) < 3:
            continue
        cands.sort(key=lambda s: s["x"])
        # 同一水平行：中线接近
        cy0 = cands[0]["y"] + cands[0]["h"] / 2
        row_tabs = [s for s in cands if abs((s["y"] + s["h"] / 2) - cy0) <= 0.08]
        if len(row_tabs) < 3:
            continue
        row_tabs.sort(key=lambda s: s["x"])
        # 同 x 去重（可编辑版偶发重复形状）
        deduped = []
        for s in row_tabs:
            if deduped and abs(s["x"] - deduped[-1]["x"]) < 0.02:
                continue
            deduped.append(s)
        row_tabs = deduped
        if len(row_tabs) < 3:
            continue
        for a, b in zip(row_tabs, row_tabs[1:]):
            gap = b["x"] - (a["x"] + a["w"])
            if gap > max_gap:
                errors.append(
                    f"第 {i} 页顶栏页签「{(a.get('text') or '')[:6]}」与「{(b.get('text') or '')[:6]}」"
                    f"之间有缝隙 {gap:.3f}″（须 edge-to-edge，gap=0）；请 relayout_section_tabs"
                )
            elif gap < -max_overlap:
                errors.append(
                    f"第 {i} 页顶栏页签「{(a.get('text') or '')[:6]}」与「{(b.get('text') or '')[:6]}」"
                    f"重叠 {-gap:.3f}″（禁止互相覆盖）；请 relayout_section_tabs"
                )
    return errors
