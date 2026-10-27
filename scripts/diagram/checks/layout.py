"""版面检查：圆内文字、粗线压字、竖向空白带、图标压字、文字出卡片、卡片出分区、图标重叠或出卡片。"""

from __future__ import annotations

import math

from .scene import Scene, area, item_box, label, overlap


def circles(sc: Scene) -> list[str]:
    """大圆里的文字和图示：要在圆内、并在圆里上下居中。
    同心的装饰环不重复查，只查有填充的那层；扁椭圆（圆柱顶面）不算。"""
    out = []
    items, texts, vw, vh = sc.items, sc.texts, sc.vw, sc.vh
    seen_c: list[tuple] = []
    for c in sorted(items, key=lambda it: -it.get("w", 0)):
        if c["kind"] != "ellipse" or c.get("icon") or not c.get("fill") or c["w"] < min(vw, vh) * 0.25 \
                or not 0.7 < c["w"] / max(c["h"], 1) < 1.4:
            continue
        center = (c["x"] + c["w"] / 2, c["y"] + c["h"] / 2)
        if any(abs(center[0] - o[0]) < 6 and abs(center[1] - o[1]) < 6 for o in seen_c):
            continue
        seen_c.append(center)
        cx, cy, rx, ry = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2, c["w"] / 2, c["h"] / 2
        inside = [t for t in texts if abs((t["box_px"][0] + t["box_px"][2]) / 2 - cx) < rx * 0.9
                  and abs((t["box_px"][1] + t["box_px"][3]) / 2 - cy) < ry * 0.95]
        for t in inside:
            x0, y0, x1, y1 = t["box_px"]
            y0, y1 = y0 + t["size"] * 0.2, y1 - t["size"] * 0.2
            worst = max(((x - cx) / (rx - t["size"] * 0.5)) ** 2 + ((y - cy) / (ry - t["size"] * 0.5)) ** 2
                        for x in (x0, x1) for y in (y0, y1))
            if worst > 1:
                out.append(f"圆形（中心 {cx:.0f},{cy:.0f}，半径 {rx:.0f}）里的文字「{t['text'].strip()[:12]}」"
                           f"（y {y0:.0f}–{y1:.0f}）超出或贴住圆边：上移或缩短，离圆边至少半个字号")
        icons = [b for b in (item_box(it) for it in items if it.get("icon")) if b
                 and abs((b[0] + b[2]) / 2 - cx) < rx * 0.8 and abs((b[1] + b[3]) / 2 - cy) < ry * 0.8]
        tops = [t["box_px"][1] + t["size"] * 0.2 for t in inside] + [b[1] for b in icons]
        bots = [t["box_px"][3] - t["size"] * 0.2 for t in inside] + [b[3] for b in icons]
        if tops:
            mid = (min(tops) + max(bots)) / 2
            if abs(mid - cy) > ry * 0.12:
                where = "偏下" if mid > cy else "偏上"
                out.append(f"圆形（中心 y≈{cy:.0f}）里的图示和文字整体{where}（内容中心 y≈{mid:.0f}）："
                           f"整体{'上' if mid > cy else '下'}移约 {abs(mid - cy):.0f}，让内容在圆里上下居中")
    return out


def thick_lines(sc: Scene) -> list[str]:
    """粗箭头/粗线（线宽 ≥ 3）穿过文字。"""
    out = []
    for ln in sc.items:
        if ln["kind"] not in ("line", "path") or ln.get("icon") or (ln.get("stroke_width") or 0) < 3:
            continue
        lb = item_box(ln)
        if not lb:
            continue
        half = ln["stroke_width"] / 2
        lb = (lb[0] - half, lb[1] - half, lb[2] + half, lb[3] + half)
        for t in sc.texts:
            x0, y0, x1, y1 = t["box_px"]
            tb = (x0, y0 + t["size"] * 0.2, x1, y1 - t["size"] * 0.2)
            if overlap(lb, tb) > 2:
                out.append(f"文字「{t['text'].strip()[:12]}」（x {tb[0]:.0f}–{tb[2]:.0f}）压在粗箭头/粗线"
                           f"（x {lb[0]:.0f}–{lb[2]:.0f}，y {lb[1]:.0f}–{lb[3]:.0f}）上：文字挪到箭头一侧，离箭头至少 6")
                break
    return out


def vertical_gap(sc: Scene) -> list[str]:
    """内容中间整条竖向空出来（宽于画布 6%）。"""
    out = []
    vw, vh = sc.vw, sc.vh
    spans = []
    for it in sc.items:
        b = item_box(it) if it["kind"] != "text" else it["box_px"]
        if not b or (b[2] - b[0] >= vw * 0.95 and b[3] - b[1] >= vh * 0.95):
            continue
        spans.append((b[0], b[2]))
    spans.sort()
    if spans:
        right = spans[0][1]
        for x0, x1 in spans[1:]:
            if x0 - right > vw * 0.06:
                out.append(f"内容中间 x {right:.0f}–{x0:.0f} 整条空着（{x0 - right:.0f} 宽）："
                           f"把左边部分加宽或右边部分左移，两部分空隙不超过 {vw * 0.04:.0f}")
            right = max(right, x1)
    return out


def icons_on_text(sc: Scene) -> list[str]:
    """图标压住上下文字，或和同一行文字左右挤在一起（每行文字只报一个图标）。"""
    out = []
    for it, b in zip(sc.texts, sc.boxes):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if any(c[0] <= cx <= c[2] and c[1] <= cy <= c[3] for c in sc.icons):
            continue  # 写在圆圈里的编号或图标字
        pad = it["size"] * 0.12
        loose = (b[0] - pad, b[1] - it["size"] * 0.15, b[2] + pad, b[3] + it["size"] * 0.15)
        for c in sc.icons:
            if overlap(loose, c) <= 4:
                continue
            gap = it["size"] * 0.4
            if abs((c[1] + c[3]) / 2 - (b[1] + b[3]) / 2) < it["size"] * 0.5:
                out.append(
                    f"图标（x≈{c[0]:.0f}–{c[2]:.0f}）和同一行文字「{label(it)}」（x≈{b[0]:.0f}–{b[2]:.0f}）左右挤在一起："
                    f"文字起点要在图标右缘再往右至少 {gap:.0f}"
                )
            elif (c[1] + c[3]) / 2 < (b[1] + b[3]) / 2:
                need = c[3] + gap - b[1]
                out.append(
                    f"图标（底边 y≈{c[3]:.0f}）压住下方文字「{label(it)}」（字顶 y≈{b[1]:.0f}）："
                    f"把这行文字及它下面的文字一起下移约 {need:.0f}，或把图标上移/缩小 {need:.0f}，图标仍要在卡片内"
                )
            else:
                need = b[3] + gap - c[1]
                out.append(
                    f"文字「{label(it)}」（字底 y≈{b[3]:.0f}）压住下方图标（顶边 y≈{c[1]:.0f}）："
                    f"图标下移约 {need:.0f}，或文字上移 {need:.0f}"
                )
            break
    return out


def text_in_cards(sc: Scene) -> list[str]:
    """文字要在所属卡片内、离边框留白；不属于任何卡片的文字不能伸进别的框或骑在边线上。"""
    out = []
    cards = sc.cards
    for it, b in zip(sc.texts, sc.boxes):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        host = [c for c in cards if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]]
        if not host:
            # 不属于任何卡片的文字伸进了别的卡片（如左侧正文写太长压进右侧架构）
            hit = next((c for c in cards if overlap(b, c) > (b[2] - b[0]) * (b[3] - b[1]) * 0.1
                        and not (b[0] >= c[0] - 2 and b[2] <= c[2] + 2)), None)
            if hit:
                out.append(
                    f"文字「{label(it)}」（x {b[0]:.0f}–{b[2]:.0f}）伸进了旁边的框（x {hit[0]:.0f}–{hit[2]:.0f}）："
                    f"这一行改短、多拆一行，右端不超过 {hit[0] - it['size'] * 0.5:.0f}"
                )
                continue
            # 中心已掉出卡片、但字身还骑在卡片上下边线上
            for c in cards:
                if b[0] >= c[0] - 2 and b[2] <= c[2] + 2 and (b[1] < c[3] < b[3] or b[1] < c[1] < b[3]):
                    edge = c[3] if b[1] < c[3] < b[3] else c[1]
                    out.append(
                        f"文字「{label(it)}」（y {b[1]:.0f}–{b[3]:.0f}）骑在卡片边线 y≈{edge:.0f} 上："
                        f"加高卡片（x {c[0]:.0f}–{c[2]:.0f}）或减小行高，让最后一行底部离卡片下边至少 {it['size']:.0f}"
                    )
                    break
            continue
        c = min(host, key=area)
        if b[0] < c[0] + 2 or b[2] > c[2] - 2:
            # 竖排标签一字一行，窄条里左右留一点即可
            pad = it["size"] * (0.15 if len(it["text"].strip()) <= 1 else 0.5)
            if b[0] >= c[0] + pad - 0.5 and b[2] <= c[2] - pad + 0.5:
                continue
            need = max(c[0] + pad - b[0], b[2] - (c[2] - pad))
            chars = max(1, math.ceil(need / it["size"]))
            out.append(
                f"文字「{label(it)}」（x {b[0]:.0f}–{b[2]:.0f}）贴住或超出卡片边框（x {c[0]:.0f}–{c[2]:.0f}）："
                f"拆成两行，或把卡片加宽 {need:.0f}（同排卡片一起调整）；不要删图意里的文字"
            )
        elif b[1] < c[1] or b[3] > c[3]:
            out.append(f"文字「{label(it)}」上下超出所在卡片或色条，加高卡片或上移文字")
    return out


def cards_in_zones(sc: Scene) -> list[str]:
    """小卡片和比它大得多的分区交叠超过三成却没被装下，就是越出了分区。"""
    out = []
    for a in sc.cards:
        for b in sc.cards:
            if area(b) <= area(a) * 1.5:
                continue
            inter = overlap(a, b)
            inside = a[0] >= b[0] - 1 and a[1] >= b[1] - 1 and a[2] <= b[2] + 1 and a[3] <= b[3] + 1
            if inter > area(a) * 0.3 and not inside:
                out.append(
                    f"卡片「{sc.text_in(a)}」（x {a[0]:.0f}–{a[2]:.0f}，y {a[1]:.0f}–{a[3]:.0f}）越出了所在分区"
                    f"（x {b[0]:.0f}–{b[2]:.0f}，y {b[1]:.0f}–{b[3]:.0f}）：同排卡片一起收窄，或把分区加宽到能装下，离边至少 8"
                )
                break
    return out


def stacked_categories(sc: Scene) -> list[str]:
    """同一排的分类标题叠在一起。多出来的一组常常还换了颜色。"""
    from ..palette import luminance

    headers = []
    for it in sc.items:
        if it["kind"] != "rect" or it.get("icon"):
            continue
        fill = it.get("fill") or ""
        if not fill or luminance(fill) > 170:
            continue
        if not (18 <= it["h"] <= sc.vh * 0.16 and sc.vw * 0.05 <= it["w"] <= sc.vw * 0.4):
            continue
        headers.append(it)
    for i in range(len(headers)):
        for j in range(i + 1, len(headers)):
            a, b = headers[i], headers[j]
            ba = (a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"])
            bb = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
            if overlap(ba, bb) < 30:
                continue
            if abs(a["y"] - b["y"]) > max(a["h"], b["h"]):
                continue
            color = "颜色也不一样，" if (a.get("fill") or "").upper() != (b.get("fill") or "").upper() else ""
            return [
                f"分类标题「{sc.text_in(ba) or '一组'}」和「{sc.text_in(bb) or '另一组'}」叠在一起，{color}"
                "删掉多出来的那一组，只留一组；同一排分类标题用同一种强调色，顶部对齐、分类框同高"
            ]
    return []


def icon_overlap(sc: Scene) -> list[str]:
    icons = sc.icons
    for i in range(len(icons)):
        for j in range(i + 1, len(icons)):
            if overlap(icons[i], icons[j]) > 4:
                return ["有图标互相重叠，图标之间要留空"]
    return []


def icons_in_cards(sc: Scene) -> list[str]:
    """图标中心落在卡片里，就要整个在卡片里（只报第一个）。"""
    for c in sc.icons:
        cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        host = [r for r in sc.cards if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]]
        if host:
            r = min(host, key=area)
            if c[1] < r[1] - 1 or c[3] > r[3] + 1 or c[0] < r[0] - 1 or c[2] > r[2] + 1:
                return [
                    f"卡片「{sc.text_in(r)}」（x {r[0]:.0f}–{r[2]:.0f}，y {r[1]:.0f}–{r[3]:.0f}）里的图标"
                    f"（x {c[0]:.0f}–{c[2]:.0f}，y {c[1]:.0f}–{c[3]:.0f}）伸出了卡片边框："
                    "把图标移进卡片并离边至少 8，或缩小图标"
                ]
    return []


def peer_equal_widths(sc: Scene, max_ratio: float = 0.12) -> list[str]:
    """同一行卡片/节点（含强调色块）宽度须接近；差超阈值报错。"""
    cards = sorted(sc.cards, key=lambda c: (round(c[1], 0), c[0]))
    if len(cards) < 2:
        return []
    rows: list[list] = []
    cur = [cards[0]]
    for c in cards[1:]:
        ref = cur[0]
        rcy = (ref[1] + ref[3]) / 2
        cy = (c[1] + c[3]) / 2
        if abs(cy - rcy) <= max(ref[3] - ref[1], c[3] - c[1]) * 0.35:
            cur.append(c)
        else:
            rows.append(cur)
            cur = [c]
    rows.append(cur)
    out = []
    for row in rows:
        # 只要「节点型」：高度接近、数量>=2，排除通栏底框
        if len(row) < 2:
            continue
        hs = [c[3] - c[1] for c in row]
        ws = [c[2] - c[0] for c in row]
        if max(hs) < sc.vh * 0.18:
            continue
        if max(ws) > sc.vw * 0.55:  # 通栏
            continue
        lo, hi = min(ws), max(ws)
        # 同排「对等节点」：高度接近且最窄也不小于最宽的 55%（排除表格式名列/内容列）
        if min(hs) < max(hs) * 0.75:
            continue
        if lo < hi * 0.55:
            continue  # 明显分栏表，不是等宽节点行
        if hi > 0 and (hi - lo) / hi > max_ratio:
            out.append(
                f"同一行节点宽度不一致（{lo:.0f}–{hi:.0f}，差 {(hi - lo) / hi * 100:.0f}%）："
                f"流程/时间轴/并列卡（含最后强调色块）须等宽，把窄的加宽或与同排一起重排"
            )
    return out


def card_title_body(sc: Scene) -> list[str]:
    """并列/流程卡内须有标题+至少一行说明；编号圆点不算说明。禁止细框空柱。"""
    import re
    out = []
    for c in sc.cards:
        cw, ch = c[2] - c[0], c[3] - c[1]
        if ch < sc.vh * 0.18 or cw < sc.vw * 0.06 or cw > sc.vw * 0.62:
            continue
        texts = [t for t, b in zip(sc.texts, sc.boxes)
                 if c[0] <= (b[0] + b[2]) / 2 <= c[2] and c[1] <= (b[1] + b[3]) / 2 <= c[3]]
        if not texts:
            continue
        body = [t for t in texts if not re.fullmatch(r"\d{1,2}", (t.get("text") or "").strip())]
        chars = sum(len((t.get("text") or "").strip()) for t in body)
        # 只有编号+短标题，或有效字过少相对卡片面积 → 空壳/空柱
        if len(body) <= 1 and chars <= 48:
            name = label(body[0]) if body else label(texts[0])
            out.append(
                f"卡片「{name}」（x {c[0]:.0f}–{c[2]:.0f}）只有标题无说明："
                f"补至少一行正文（做法/要点），禁止细框空柱或大片留白"
            )
        elif ch > sc.vh * 0.35 and chars < 18:
            name = label(body[0]) if body else label(texts[0])
            out.append(
                f"卡片「{name}」过高却字太少（{chars} 字）：加标题下说明行，或降低卡片高度填满信息"
            )
    return out[:6]


def sparse_content(sc: Scene) -> list[str]:
    """整图有效文字过稀：业务汇报结构图信息密度须接近正文页，禁止大片空洞。"""
    chars = sum(len((t.get("text") or "").strip()) for t in sc.texts)
    # 画布面积归一：以 1200×500 为参照，至少约 80 汉字量级
    expect = max(60, int((sc.vw * sc.vh) / (1200 * 500) * 90))
    if chars < expect and len(sc.texts) < 10:
        return [
            f"结构图文字过稀（约 {chars} 字 / {len(sc.texts)} 行，期望≥{expect} 字或≥10 行）："
            f"流程/对照卡须标题+≥1 行说明，pipeline 多行写做法与特点，禁止三字格+大留白"
        ]
    if chars < expect * 0.7:
        return [
            f"结构图信息密度偏低（约 {chars} 字，期望约 {expect}）：补说明行与箭头旁注，贴近业务汇报密度"
        ]
    return []


def contrast_hierarchy(sc: Scene) -> list[str]:
    """结构图内标题与正文须有足够对比度/层级；禁止标题与正文同为浅色。"""
    from ..palette import luminance
    out = []
    light_all = []
    for c in sc.cards:
        cw = c[2] - c[0]
        if cw < sc.vw * 0.08 or cw > sc.vw * 0.55:
            continue
        texts = [(t, b) for t, b in zip(sc.texts, sc.boxes)
                 if c[0] <= (b[0] + b[2]) / 2 <= c[2] and c[1] <= (b[1] + b[3]) / 2 <= c[3]]
        if len(texts) < 2:
            continue
        # 按字号分：较大的当标题
        texts_sorted = sorted(texts, key=lambda tb: -tb[0].get("size", 12))
        title_t = texts_sorted[0][0]
        body_ts = [t for t, _ in texts_sorted[1:]]
        tfill = (title_t.get("fill") or "").lstrip("#").upper()
        if len(tfill) != 6:
            continue
        tl = luminance(tfill)
        body_ls = []
        for bt in body_ts:
            bf = (bt.get("fill") or "").lstrip("#").upper()
            if len(bf) == 6:
                body_ls.append(luminance(bf))
        if not body_ls:
            continue
        bl = sum(body_ls) / len(body_ls)
        light_all.append((tl, bl, title_t))
        # 两者都偏浅（相对白底）
        if tl > 150 and bl > 150:
            out.append(
                f"卡片「{label(title_t)}」标题与正文同为浅色"
                f"（标题亮度≈{tl:.0f}，正文≈{bl:.0f}）："
                f"标题改用模板主色/强调色或更深字色，正文用近黑深色，并用色带/编号区分层级"
            )
    # 整图文字普遍偏浅
    if light_all and all(tl > 160 and bl > 160 for tl, bl, _ in light_all):
        out.append(
            "结构图标题与正文普遍偏浅、缺少层级：标题用主色/强调色，正文用深色可读字色，"
            "可用色带标题条或编号块区分，不要整页只有浅灰"
        )
    return list(dict.fromkeys(out))[:4]
