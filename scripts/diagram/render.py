"""SVG → 高清 PNG（Playwright 截图），用于图片版。"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree


def render_png(svg: str, out_png: Path, scale: int = 4) -> Path:
    from playwright.sync_api import sync_playwright

    root = etree.fromstring(svg.encode("utf-8"))
    vb = [float(v) for v in re.split(r"[\s,]+", root.get("viewBox").strip())]
    w, h = int(round(vb[2])), int(round(vb[3]))
    root.set("width", str(w))
    root.set("height", str(h))
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;background:#ffffff'>"
        + etree.tostring(root, encoding="unicode") + "</body></html>"
    )
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
        page.set_content(html)
        page.wait_for_timeout(200)
        page.locator("svg").first.screenshot(path=str(out_png))
        browser.close()
    return out_png
