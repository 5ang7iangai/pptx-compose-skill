"""画布尺寸与字号：字号按幻灯片上的磅数约定，再换算成 SVG 画布单位。"""

from __future__ import annotations


def canvas_for(bbox: dict, width_px: int = 1200) -> tuple[int, int]:
    return width_px, int(round(width_px * bbox["h"] / bbox["w"]))


# 幻灯片上的字号（磅）；diagram 或 spec 的 fonts 可覆盖，取原页正文的字号
FONT_PT = {"body": 12, "title": 15, "label": 13, "note": 10}


def font_px(diag: dict, width: int | None = None) -> dict:
    """把 fonts（磅）换算成画布单位。"""
    width = width or diag.get("canvas_width", 1200)
    pt_per_px = diag["bbox"]["w"] * 72 / width
    pts = {**FONT_PT, **(diag.get("fonts") or {})}
    return {k: v / pt_per_px for k, v in pts.items()} | {"pt": pts, "pt_per_px": pt_per_px}
