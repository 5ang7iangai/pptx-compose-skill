"""检查共用的几何场景：从图元里一次算好文字框、图标框、卡片框，各项检查只读不改。"""

from __future__ import annotations

from dataclasses import dataclass, field


def item_box(it: dict) -> tuple | None:
    if it["kind"] in ("rect", "ellipse"):
        return it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"]
    if it["kind"] == "line":
        (x1, y1), (x2, y2) = it["p1"], it["p2"]
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    if it["kind"] == "path":
        pts = [(s[i], s[i + 1]) for s in it["segs"] for i in range(1, len(s) - 1, 2)]
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return min(xs), min(ys), max(xs), max(ys)
    return None


def overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def area(r) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def label(it: dict) -> str:
    return it["text"].strip()[:14]


@dataclass
class Scene:
    items: list[dict]
    vw: float
    vh: float
    texts: list[dict] = field(default_factory=list)   # 不在图标里的文字
    boxes: list[tuple] = field(default_factory=list)  # 与 texts 一一对应，已收紧到字身
    icons: list[tuple] = field(default_factory=list)
    cards: list[tuple] = field(default_factory=list)

    def text_in(self, r) -> str:
        """落在框 r 里的第一行文字，用来在提示里点名这个框。"""
        return next((label(t) for t, bx in zip(self.texts, self.boxes)
                     if r[0] <= (bx[0] + bx[2]) / 2 <= r[2] and r[1] <= (bx[1] + bx[3]) / 2 <= r[3]), "")


def build_scene(items: list[dict], vw: float, vh: float) -> Scene:
    sc = Scene(items, vw, vh)
    for it in items:
        if it["kind"] == "text" and not it.get("icon"):
            x0, y0, x1, y1 = it["box_px"]
            # 行高里上下各有一点留白，比较时收紧到字身
            sc.texts.append(it)
            sc.boxes.append((x0, y0 + it["size"] * 0.2, x1, y1 - it["size"] * 0.2))
    # 每个 <use> 图标取它全部图元的总外框（有圆底时就是圆底，纯线条图标是线条范围）；图标内部的小件不单独比较
    icon_box: dict[int, tuple] = {}
    for it in items:
        n = it.get("icon")
        b = item_box(it) if n else None
        if b:
            o = icon_box.get(n)
            icon_box[n] = b if not o else (min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3]))
    icons = list(icon_box.values())
    icons += [(it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"])
              for it in items if it["kind"] == "ellipse" and not it.get("icon")
              and it["w"] < min(vw, vh) * 0.12]
    # 连线端点、编号小圆点不算图标
    sc.icons = [c for c in icons if min(c[2] - c[0], c[3] - c[1]) >= 12]
    sc.cards = [(it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"])
                for it in items if it["kind"] == "rect" and not it.get("icon")
                and not (it["w"] >= vw * 0.95 and it["h"] >= vh * 0.95)]
    return sc
