"""风格硬性要求：检查项和阈值写在 catalog/styles/<id>/style.yaml 的 checks 里。

    max_radius       矩形圆角 rx 不超过 max_rx（短边 ≤ min_side 的小件不算）
    bands            至少 min_count 条宽 ≥ min_width·画布宽、高 ≤ max_height·画布高的通栏
    dark_background  第一个矩形铺满画布、亮度 ≤ max_luminance
    no_shadow        不许 feDropShadow
"""

from __future__ import annotations

from ..catalog import style_meta
from ..palette import luminance


def _max_radius(rule, rects, root, vw, vh):
    n = len([r for r in rects if r["rx"] > rule["max_rx"] and min(r["w"], r["h"]) > rule.get("min_side", 16)])
    return {"n": n} if n else None


def _bands(rule, rects, root, vw, vh):
    n = len([r for r in rects if r["w"] >= vw * rule["min_width"] and r["h"] <= vh * rule["max_height"]])
    return {"n": n, "min_w": f"{vw * rule['min_width']:.0f}"} if n < rule["min_count"] else None


def _dark_background(rule, rects, root, vw, vh):
    bg = rects[0] if rects else None
    if not bg or bg["w"] < vw * 0.95 or bg["h"] < vh * 0.95 or luminance(bg.get("fill")) > rule["max_luminance"]:
        return {}
    return None


def _no_shadow(rule, rects, root, vw, vh):
    return {} if root.xpath("//*[local-name()='feDropShadow']") else None


RULES = {
    "max_radius": _max_radius,
    "bands": _bands,
    "dark_background": _dark_background,
    "no_shadow": _no_shadow,
}


def style_problems(root, items: list[dict], style: str, vw: float, vh: float) -> list[str]:
    rects = [it for it in items if it["kind"] == "rect" and "icon" not in it]
    out = []
    for rule in style_meta(style).get("checks") or []:
        hit = RULES[rule["type"]](rule, rects, root, vw, vh)
        if hit is not None:
            out.append(rule["hint"].format(**hit))
    return out
