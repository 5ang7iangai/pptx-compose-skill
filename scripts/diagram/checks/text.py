"""文字本身的检查：字号下限、正文行距、出画布、画重、互压、左右贴太紧。"""

from __future__ import annotations

import math
import re

from .scene import Scene, label, overlap


def paragraph_lines(texts: list[dict]) -> set[int]:
    """左对齐、上下相邻（基线差 < 2.2 倍字号）、合计 30 字以上的多行文字，视为一段正文（短的多行旁注不算）。"""
    parent = list(range(len(texts)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i, a in enumerate(texts):
        for j, b in enumerate(texts):
            if i != j and abs(a["box_px"][0] - b["box_px"][0]) < 2 and abs(a["size"] - b["size"]) < 0.5 \
                    and 0 < b["y"] - a["y"] < a["size"] * 2.2:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(texts)):
        groups.setdefault(find(i), []).append(i)
    out = set()
    for g in groups.values():
        if len(g) >= 2 and sum(len(texts[i]["text"].strip()) for i in g) >= 30:
            out |= set(g)
    return out


def font_size(sc: Scene, para: set[int], fonts: dict | None) -> list[str]:
    """fonts 是 sizing.font_px 的结果：正文段落不低于 body，任何字不低于 note。"""
    if not fonts:
        return []
    out = []
    texts = sc.texts
    small = [t for k, t in enumerate(texts) if k in para and t["size"] < fonts["body"] * 0.95]
    if small:
        sizes = "、".join(sorted({f"{t['size']:g}" for t in small}))
        out.append(
            f"正文字号太小：{len(small)} 行多行正文用了 {sizes}，要求 {math.ceil(fonts['body'])}"
            f"（≈{fonts['pt']['body']:g} 磅）：字号调到 {math.ceil(fonts['body'])}，行距 {math.ceil(fonts['body'] * 1.5)}，"
            f"卡片随之加高，不够放就压缩其他留白，例如「{small[0]['text'].strip()[:12]}」"
        )
    tiny = [t for t in texts if t["size"] < fonts["note"] * 0.95]
    if tiny:
        out.append(
            f"有 {len(tiny)} 行字小于 {math.ceil(fonts['note'])}（≈{fonts['pt']['note']:g} 磅），"
            f"如「{tiny[0]['text'].strip()[:12]}」字号 {tiny[0]['size']:g}：调到不小于 {math.ceil(fonts['note'])}"
        )
    return out


def paragraph_spacing(sc: Scene, para: set[int]) -> list[str]:
    """多行正文行距在 1.15–1.35 倍字号之间：没压字，但显得挤。"""
    texts = sc.texts
    tight = sorted({round(b["y"] - a["y"]) for i, a in enumerate(texts) for j, b in enumerate(texts)
                    if i in para and j in para and abs(a["box_px"][0] - b["box_px"][0]) < 2
                    and a["size"] * 1.15 <= b["y"] - a["y"] < a["size"] * 1.35})
    if tight:
        return [f"多行正文行距只有 {tight[0]}，显得挤：相邻两行基线差调到字号的 1.5 倍，卡片随之加高"]
    return []


def out_of_canvas(sc: Scene) -> list[str]:
    return [f"文字超出画布：「{label(it)}」" for it, b in zip(sc.texts, sc.boxes)
            if b[0] < -2 or b[1] < -2 or b[2] > sc.vw + 2 or b[3] > sc.vh + 2]


def duplicates(sc: Scene, brief: str | None) -> list[str]:
    """同一句话（4 字以上）出现次数比图意里多，就是画重了。"""
    texts, boxes = sc.texts, sc.boxes

    def continuation(i: int) -> bool:
        """紧贴在上一行正下方、对齐的文字是长条目折出来的续行，不单独算重复。"""
        b, s = boxes[i], texts[i]["size"]
        cx = (b[0] + b[2]) / 2
        for j, o in enumerate(boxes):
            if j != i and 0 <= b[1] - o[3] < s * 0.9 and (
                    abs((o[0] + o[2]) / 2 - cx) < s * 0.6 or abs(o[0] - b[0]) < s * 0.3):
                return True
        return False

    # 同一名称字号不同（如左侧级别标题和右侧架构框）是不同角色，按字号分组计数
    seen: dict[tuple, int] = {}
    for i, it in enumerate(texts):
        if continuation(i):
            continue
        key = re.sub(r"\s+", "", it["text"])
        if len(key) >= 4:
            seen[(key, round(it["size"]))] = seen.get((key, round(it["size"])), 0) + 1
    plain_brief = re.sub(r"\s+", "", brief or "")
    return [f"「{key[:14]}」重复出现了 {n} 次：每一项只画一次，删掉多余的那一份"
            for (key, _), n in seen.items() if n > max(1, plain_brief.count(key))]


def pairs(sc: Scene) -> list[str]:
    """两两比较：互相压住、行距太小、左右贴太紧（每对只报最重的一条）。"""
    out = []
    texts, boxes = sc.texts, sc.boxes
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = boxes[i], boxes[j]
            inter = overlap(a, b)
            small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if small > 0 and inter / small > 0.08:
                big, small_t = (texts[i], texts[j]) if texts[i]["size"] >= texts[j]["size"] else (texts[j], texts[i])
                if big["size"] >= small_t["size"] * 2:
                    out.append(
                        f"大数字「{label(big)}」压住了「{label(small_t)}」："
                        f"说明放到数字上方或下方，间距至少 {big['size'] * 0.35:.0f}，不要缩短数字，也不要让说明骑在数字上"
                    )
                else:
                    out.append(f"文字互相压住：「{label(texts[i])}」和「{label(texts[j])}」，拉开间距或缩短")
                continue
            v = min(a[3], b[3]) - max(a[1], b[1])
            gap = max(a[0], b[0]) - min(a[2], b[2])
            size = min(texts[i]["size"], texts[j]["size"])
            step = abs(texts[i]["y"] - texts[j]["y"])
            if gap < 0 and 0 < step < size * 1.15:
                top = min(texts[i], texts[j], key=lambda t: t["y"])
                out.append(
                    f"行距太小：「{label(texts[i])}」和「{label(texts[j])}」基线只差 {step:.0f}（字号 {size:.0f}），"
                    f"下面一行及其后各行下移到行距至少 {size * 1.5:.0f}，卡片随之加高（上一行 y={top['y']:.0f}）"
                )
                continue
            if v > size * 0.4 and 0 <= gap < size * 0.4:
                out.append(f"文字左右贴得太紧：「{label(texts[i])}」和「{label(texts[j])}」，中间至少留半个字宽")
    return out
