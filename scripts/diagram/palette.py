"""配色：由模板主色按色相推出整套色板（深浅、底色、字色、边线、深色底、c2/c3 编码色）。"""

from __future__ import annotations

import colorsys


DEFAULT_PALETTE = {
    "dominant": "007774", "dark": "065A58", "mid": "2A9D98", "light": "CFE8E6",
    "paper": "F4F8F7", "ink": "163332", "mute": "3D6B69", "line": "9EC9C6", "gold": "B8954A",
}


NEUTRAL = {"n50": "FAFAFA", "n200": "E4E4E7", "n500": "71717A", "n600": "7F7F7F", "n900": "18181B"}


def _hls(hex6: str) -> tuple[float, float, float]:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def _hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, min(max(l, 0), 1), min(max(s, 0), 1))
    return "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def _hue_gap(a: str, b: str) -> float:
    ha, hb = _hls(a)[0], _hls(b)[0]
    return min(abs(ha - hb), 1 - abs(ha - hb)) * 360


def pick_extras(dominant: str, rows: list[str]) -> list[str]:
    """模板里与主色、彼此色相都拉开的彩色，作分级/分类的第二、第三编码色；不够时用青、橙补。"""
    chosen = [dominant]
    for c in rows:
        _, l, s = _hls(c)
        if s > 0.97 and 0.45 < l < 0.55:
            continue  # FF0000 这类纯原色多是警示色，不当编码色
        if s > 0.35 and 0.25 < l < 0.65 and all(_hue_gap(c, x) >= 22 for x in chosen):
            chosen.append(c.upper())
        if len(chosen) == 3:
            break
    for fallback in ("1C9FA9", "E8913A"):
        if len(chosen) < 3 and all(_hue_gap(fallback, x) >= 22 for x in chosen):
            chosen.append(fallback)
    while len(chosen) < 3:
        chosen.append("E8913A")
    return chosen[1:]


def derive_palette(dominant: str, accent: str | None = None, extras: list[str] | None = None) -> dict:
    """由模板主色按色相推出整套：深浅、底色、字色、边线、深色底，换模板不会串色。"""
    h, l, s = _hls(dominant)
    pal = {
        "dominant": dominant.upper(),
        "dark": _hex(h, l * 0.72, s),
        "mid": _hex(h, min(l + 0.15, 0.55), s * 0.6),
        "light": _hex(h, 0.88, max(s * 0.45, 0.3)),
        "paper": _hex(h, 0.965, max(s * 0.3, 0.2)),
        "ink": _hex(h, 0.14, s * 0.4),
        "mute": _hex(h, 0.32, s * 0.3),
        "line": _hex(h, 0.74, s * 0.35),
        "night": _hex(h, 0.09, s * 0.35),
        "night2": _hex(h, 0.15, s * 0.3),
        "nightline": _hex(h, 0.28, s * 0.3),
        "glow": _hex(h, 0.6, 0.62),
        "gold": DEFAULT_PALETTE["gold"],
        **NEUTRAL,
    }
    for key, c in zip(("c2", "c3"), extras or pick_extras(dominant, [])):
        hc, _, sc = _hls(c)
        pal[key] = c.upper()
        pal[key + "l"] = _hex(hc, 0.93, max(sc * 0.5, 0.35))
    if accent and accent.upper() != dominant.upper():
        ha, la, sa = _hls(accent)
        hue_gap = min(abs(ha - h), 1 - abs(ha - h)) * 360
        if hue_gap > 25 and sa > 0.3 and 0.3 < la < 0.7:
            pal["gold"] = accent.upper()
    return pal


def pick_dominant(src: dict) -> str:
    """主色跟模板标题、顶栏走。浅黄这类亮色跳过，后面还有顶栏深色就用深色；全是浅色才压暗。"""
    light = None
    for c in src.get("title") or []:
        if not c:
            continue
        h, l, s = _hls(c)
        if s <= 0.18:
            continue
        if l > 0.46:
            light = light or c
            continue
        return c.upper()
    if light:
        h, _, s = _hls(light)
        return _hex(h, 0.33, max(s, 0.45))
    rows = [src.get("dominant"), src.get("accent")] + [c["hex"] for c in src.get("counts") or []]
    rows = [c for c in rows if c]
    for c in rows:
        _, l, s = _hls(c)
        if s > 0.25 and 0.18 < l < 0.45:
            return c.upper()
    if not rows:
        return DEFAULT_PALETTE["dominant"]
    h, _, s = _hls(rows[0])
    return _hex(h, 0.33, max(s, 0.5))


def palette_from(card: dict | None, override: dict | None = None) -> dict:
    src = (card or {}).get("palette") or {}
    override = {k: v.upper().lstrip("#") for k, v in (override or {}).items()}
    dominant = override.get("dominant") or pick_dominant(src)
    rows = [src.get("accent")] + [c["hex"] for c in src.get("counts") or []]
    extras = pick_extras(dominant, [c for c in rows if c])
    extras = [override.get("c2") or extras[0], override.get("c3") or extras[1]]
    pal = derive_palette(dominant, src.get("accent"), extras)
    pal.update(override)
    return pal


def luminance(hex6: str | None) -> float:
    if not hex6:
        return 255.0
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
