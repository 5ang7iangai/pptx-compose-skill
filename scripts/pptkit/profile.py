# -*- coding: utf-8 -*-
"""从一份 pptx 抽取风格卡。每次现抽，不写回模板。"""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

from lxml import etree
from PIL import Image, ImageFilter, ImageStat

from .ooxml import A, P, R, EMU, load_pptx, parse, q, slide_order

INCH = EMU


def lum(hex6: str) -> float:
    r = int(hex6[0:2], 16)
    g = int(hex6[2:4], 16)
    b = int(hex6[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def local(tag: str) -> str:
    return tag.split("}")[-1] if tag else ""


def xfrm_box(el: etree._Element) -> tuple[int, int, int, int] | None:
    xfrm = None
    for child in el:
        if local(child.tag) in ("spPr", "grpSpPr", "xfrm"):
            if local(child.tag) == "xfrm":
                xfrm = child
            else:
                for sub in child:
                    if local(sub.tag) == "xfrm":
                        xfrm = sub
                        break
        if xfrm is not None:
            break
    if xfrm is None:
        xfrm = el.find(q(A, "xfrm"))
    if xfrm is None:
        return None
    off = xfrm.find(q(A, "off"))
    ext = xfrm.find(q(A, "ext"))
    if off is None or ext is None:
        return None
    return (
        int(off.get("x") or 0),
        int(off.get("y") or 0),
        int(ext.get("cx") or 0),
        int(ext.get("cy") or 0),
    )


def group_xfrm(el: etree._Element) -> tuple[int, int, int, int, int, int, int, int] | None:
    xfrm = None
    for child in el:
        if local(child.tag) == "grpSpPr":
            xfrm = child.find(q(A, "xfrm"))
            break
    if xfrm is None:
        return None
    off = xfrm.find(q(A, "off"))
    ext = xfrm.find(q(A, "ext"))
    ch_off = xfrm.find(q(A, "chOff"))
    ch_ext = xfrm.find(q(A, "chExt"))
    if off is None or ext is None:
        return None
    return (
        int(off.get("x") or 0),
        int(off.get("y") or 0),
        int(ext.get("cx") or 0),
        int(ext.get("cy") or 0),
        int(ch_off.get("x") or 0) if ch_off is not None else 0,
        int(ch_off.get("y") or 0) if ch_off is not None else 0,
        int(ch_ext.get("cx") or 1) if ch_ext is not None else 1,
        int(ch_ext.get("cy") or 1) if ch_ext is not None else 1,
    )


def apply_group(box, grp) -> tuple[int, int, int, int]:
    x, y, w, h = box
    gx, gy, gw, gh, cx, cy, cw, ch = grp
    cw = cw or 1
    ch = ch or 1
    return (
        int(gx + (x - cx) * gw / cw),
        int(gy + (y - cy) * gh / ch),
        int(w * gw / cw),
        int(h * gh / ch),
    )


def shape_name(el: etree._Element) -> str:
    nv = el.find(".//" + q(P, "cNvPr"))
    return nv.get("name") if nv is not None and nv.get("name") else ""


def shape_text(el: etree._Element) -> str:
    return "".join((t.text or "") for t in el.iter(q(A, "t"))).strip()


def _srgb(node: etree._Element | None) -> str | None:
    if node is None:
        return None
    srgb = node.find(q(A, "srgbClr"))
    val = (srgb.get("val") if srgb is not None else "") or ""
    return val.upper() if len(val) == 6 else None


def shape_paint(el: etree._Element) -> tuple[str | None, str | None]:
    """形状的实色填充和文字色（只认写成 srgb 的）。"""
    fill = None
    for child in el:
        if local(child.tag) == "spPr":
            fill = _srgb(child.find(q(A, "solidFill")))
            break
    font = None
    for run in el.iter(q(A, "r")):
        node = run.find(q(A, "t"))
        if node is None or not (node.text or "").strip():
            continue
        font = _srgb(run.find(".//" + q(A, "solidFill")))
        if font:
            break
    return fill, font


def prst_of(el: etree._Element) -> str:
    prst = el.find(".//" + q(A, "prstGeom"))
    return prst.get("prst") if prst is not None else ""


def theme_info(parts: dict[str, bytes]) -> dict:
    raw = parts.get("ppt/theme/theme1.xml")
    if not raw:
        return {}
    root = parse(raw)
    scheme = root.find(".//" + q(A, "clrScheme"))
    colors = {}
    if scheme is not None:
        for child in scheme:
            srgb = child.find(".//" + q(A, "srgbClr"))
            sys = child.find(".//" + q(A, "sysClr"))
            val = srgb.get("val") if srgb is not None else (sys.get("lastClr") if sys is not None else "")
            colors[local(child.tag)] = val
    fonts = {}
    for which in ("majorFont", "minorFont"):
        node = root.find(".//" + q(A, which))
        if node is None:
            continue
        for el in node:
            if el.get("typeface") and local(el.tag) in ("latin", "ea", "cs"):
                fonts[f"{which}_{local(el.tag)}"] = el.get("typeface")
    return {"name": root.get("name") or "", "colors": colors, "fonts": fonts}


def image_features(data: bytes) -> dict:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    small = im.resize((48, 48))
    pix = list(small.getdata())
    n = len(pix)

    def white(r, g, b):
        return r > 240 and g > 240 and b > 240

    def teal(r, g, b):
        return r <= 130 and 70 <= g <= 200 and 60 <= b <= 190 and g >= r - 5 and b >= r - 15

    top = list(im.crop((0, 0, w, max(1, int(h * 0.18)))).resize((40, 8)).getdata())

    def redish(r, g, b):
        return r > 140 and r > g + 25 and r > b + 25

    edges = im.convert("L").resize((64, 64)).filter(ImageFilter.FIND_EDGES)
    return {
        "white": round(sum(white(*c) for c in pix) / n, 3),
        "teal": round(sum(teal(*c) for c in pix) / n, 3),
        "topred": round(sum(redish(*c) for c in top) / len(top), 3),
        "edge": round(ImageStat.Stat(edges).mean[0], 1),
        "std": round(sum(ImageStat.Stat(small).stddev) / 3, 1),
    }


def classify_picture(box_in, slide_w, slide_h, feat: dict) -> tuple[str, str]:
    """只自动判定有把握的类。其余标 review，由助手看图后改 kind。"""
    x, y, w, h = box_in
    if w >= slide_w * 0.85 and h <= slide_h * 0.55 and feat["edge"] < 20:
        return "decoration", "high"
    if w <= slide_w * 0.30 and h <= slide_h * 0.22 and x < slide_w * 0.28 and y < slide_h * 0.22:
        return "logo", "high"
    if feat["topred"] >= 0.08 and feat["white"] >= 0.45:
        return "document", "medium"
    return "review", "low"


def palette_from_counts(counts: Counter, title_colors: Counter | None = None) -> dict:
    ranked = counts.most_common()
    saturated = [(c, n) for c, n in ranked if 40 <= lum(c) <= 200]
    lights = [(c, n) for c, n in ranked if lum(c) > 200]
    darks = [(c, n) for c, n in ranked if lum(c) < 40]
    mid_lights = [(c, n) for c, n in ranked if 160 <= lum(c) <= 230]

    def first(rows, default):
        return rows[0][0] if rows else default

    return {
        "dominant": first(saturated, "006F68"),
        "accent": saturated[1][0] if len(saturated) > 1 else first(saturated, "006F68"),
        "surface": first(lights, "F2F2F2"),
        "light": first(mid_lights, "E7F3F2"),
        "text": first(darks, "000000"),
        "counts": [{"hex": c, "n": n} for c, n in ranked[:12]],
        "title": [c for c, _ in (title_colors or Counter()).most_common(8)],
    }


def layout_name(parts: dict[str, bytes], slide_part: str) -> str:
    rels_part = slide_part.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    if rels_part not in parts:
        return ""
    root = parse(parts[rels_part])
    for rel in root:
        if (rel.get("Type") or "").endswith("/slideLayout"):
            target = rel.get("Target") or ""
            part = "ppt/" + target.replace("../", "").lstrip("/")
            if part not in parts:
                part = "ppt/slideLayouts/" + Path(target).name
            if part not in parts:
                return Path(target).name
            lay = parse(parts[part])
            c_sld = lay.find(q(P, "cSld"))
            return c_sld.get("name") if c_sld is not None and c_sld.get("name") else Path(part).name
    return ""


def picture_media(parts: dict[str, bytes], slide_part: str) -> dict[str, str]:
    rels_part = slide_part.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    out = {}
    if rels_part not in parts:
        return out
    for rel in parse(parts[rels_part]):
        if (rel.get("Type") or "").endswith("/image"):
            target = (rel.get("Target") or "").replace("\\", "/")
            out[rel.get("Id")] = Path(target).name
    return out


def walk_slide(root, groups, sink_shapes, sink_pics, geoms):
    def walk(el, grp):
        tag = local(el.tag)
        if tag == "grpSp":
            g = group_xfrm(el)
            for child in el:
                if local(child.tag) not in ("nvGrpSpPr", "grpSpPr"):
                    walk(child, g if g and g[2] and g[3] else grp)
            return
        if tag in ("sp", "cxnSp"):
            box = xfrm_box(el)
            if box and grp:
                box = apply_group(box, grp)
            prst = prst_of(el)
            if prst:
                geoms[prst] += 1
            if tag == "sp":
                text = shape_text(el)
                ph = el.find(".//" + q(P, "ph"))
                fill, font = shape_paint(el)
                sink_shapes.append(
                    {
                        "name": shape_name(el),
                        "text": text,
                        "prst": prst,
                        "placeholder": ph.get("type") if ph is not None and ph.get("type") else ("body" if ph is not None else ""),
                        "box": box,
                        "fill": fill,
                        "font": font,
                    }
                )
            return
        if tag == "pic":
            box = xfrm_box(el)
            if box and grp:
                box = apply_group(box, grp)
            blip = el.find(".//" + q(A, "blip"))
            rid = blip.get(q(R, "embed")) if blip is not None else ""
            sink_pics.append({"name": shape_name(el), "rid": rid, "box": box})

    for child in root.find(q(P, "cSld")).find(q(P, "spTree")):
        if local(child.tag) in ("nvGrpSpPr", "grpSpPr"):
            continue
        walk(child, None)


def role_of(index: int, text: str) -> str:
    compact = "".join(text.split()).upper()
    if "谢谢" in compact or "感谢" in compact:
        return "ending"
    # 「目 录」「CO NTENTS」字间有空格，连写后仍是目录页
    if "目录" in compact or "CONTENTS" in compact:
        return "toc"
    if index == 1:
        return "cover"
    return "content"


def analyze(path: Path) -> dict:
    parts = load_pptx(path)
    pres = parse(parts["ppt/presentation.xml"])
    sld_sz = pres.find(q(P, "sldSz"))
    cx = int(sld_sz.get("cx"))
    cy = int(sld_sz.get("cy"))
    slide_w = round(cx / INCH, 2)
    slide_h = round(cy / INCH, 2)
    theme = theme_info(parts)
    fill_counts: Counter = Counter()
    font_counts: Counter = Counter()
    title_colors: Counter = Counter()
    slides = []
    for row in slide_order(parts):
        root = parse(parts[row["part"]])
        for node in root.iter(q(A, "srgbClr")):
            val = (node.get("val") or "").upper()
            if len(val) == 6:
                fill_counts[val] += 1
        for node in root.iter(q(A, "latin")):
            if node.get("typeface"):
                font_counts[node.get("typeface")] += 1
        for node in root.iter(q(A, "ea")):
            if node.get("typeface"):
                font_counts[node.get("typeface")] += 1
        shapes: list[dict] = []
        pics: list[dict] = []
        geoms: Counter = Counter()
        walk_slide(root, None, shapes, pics, geoms)
        media = picture_media(parts, row["part"])
        pictures = []
        for i, pic in enumerate(pics, start=1):
            box = pic["box"] or (0, 0, 0, 0)
            box_in = tuple(round(v / INCH, 2) for v in box)
            name = media.get(pic["rid"], "")
            data = parts.get(f"ppt/media/{name}", b"")
            feat = image_features(data) if data else {"white": 0, "teal": 0, "topred": 0, "edge": 0, "std": 0}
            kind, confidence = classify_picture(box_in, slide_w, slide_h, feat)
            hint = ""
            if kind == "review" and feat["teal"] >= 0.08 and feat["std"] >= 40:
                hint = "diagram"
            pictures.append(
                {
                    "index": i,
                    "name": pic["name"],
                    "media": name,
                    "x": box_in[0],
                    "y": box_in[1],
                    "w": box_in[2],
                    "h": box_in[3],
                    "kind": kind,
                    "confidence": confidence,
                    "hint": hint,
                    "features": feat,
                }
            )
        text_slots = []
        for sp in shapes:
            if not sp["text"]:
                continue
            box = sp["box"] or (0, 0, 0, 0)
            text_slots.append(
                {
                    "name": sp["name"],
                    "text": sp["text"],
                    "prst": sp["prst"],
                    "x": round(box[0] / INCH, 2),
                    "y": round(box[1] / INCH, 2),
                    "w": round(box[2] / INCH, 2),
                    "h": round(box[3] / INCH, 2),
                }
            )
        for sp in shapes:
            box = sp["box"]
            is_title = sp["placeholder"] in ("title", "ctrTitle")
            in_header = bool(box) and box[1] < cy * 0.22
            wide = bool(box) and box[2] > cx * 0.4
            if is_title and sp.get("font"):
                title_colors[sp["font"]] += 8
            if is_title and sp.get("fill"):
                title_colors[sp["fill"]] += 5
            if in_header and wide and sp.get("fill"):
                title_colors[sp["fill"]] += 6
            elif in_header and sp.get("font") and sp.get("text"):
                title_colors[sp["font"]] += 2
        placeholders = [sp["placeholder"] for sp in shapes if sp["placeholder"]]
        text_all = "\n".join(sp["text"] for sp in shapes if sp["text"])
        chrome = sorted({sp["text"] for sp in shapes if sp["text"] and len(sp["text"]) <= 8})
        slides.append(
            {
                "index": row["index"],
                "part": row["part"],
                "layout": layout_name(parts, row["part"]),
                "role": role_of(row["index"], text_all),
                "placeholders": placeholders,
                "has_shape_diagram": geoms.get("chevron", 0) > 0 or geoms.get("straightConnector1", 0) >= 3,
                "geoms": dict(geoms),
                "picture_count": len(pictures),
                "shape_count": len(shapes),
                "chrome": chrome,
                "text_slots": text_slots,
                "pictures": pictures,
            }
        )
    patterns = []
    groups: dict[tuple, list[int]] = {}
    for slide in slides:
        key = (slide["role"], tuple(slide["chrome"]), slide["picture_count"], slide["has_shape_diagram"])
        groups.setdefault(key, []).append(slide["index"])
    for n, (key, indexes) in enumerate(groups.items(), start=1):
        patterns.append(
            {
                "id": f"p{n}",
                "role": key[0],
                "chrome": list(key[1]),
                "picture_count": key[2],
                "has_shape_diagram": key[3],
                "slides": indexes,
            }
        )
    content = [s for s in slides if s["role"] == "content"]
    ph_content = sum(1 for s in content if s["placeholders"])
    build_path = "placeholder" if content and ph_content > len(content) / 2 else "exemplar"
    layouts_with_num = 0
    for name, blob in parts.items():
        if name.startswith("ppt/slideLayouts/slideLayout") and name.endswith(".xml"):
            if 'type="sldNum"' in blob.decode("utf-8", errors="ignore"):
                layouts_with_num += 1
    slides_with_num = sum(1 for s in slides if "sldNum" in s["placeholders"])
    fonts = theme.get("fonts", {})
    from .fonts import learn_font_roles
    roles = learn_font_roles(parts)
    return {
        "source": str(path),
        "canvas": {"cx": cx, "cy": cy, "w_in": slide_w, "h_in": slide_h},
        "theme": theme,
        "fonts": {
            "ea": fonts.get("majorFont_ea") or fonts.get("minorFont_ea") or "",
            "latin": fonts.get("majorFont_latin") or fonts.get("minorFont_latin") or "",
            "used": [{"name": n, "n": c} for n, c in font_counts.most_common(8)],
            "roles": roles,
        },
        "palette": palette_from_counts(fill_counts, title_colors),
        "build_path": build_path,
        "page_number": {
            "on_slides": slides_with_num,
            "layouts_with_sldNum": layouts_with_num,
        },
        "slide_count": len(slides),
        "slides": slides,
        "patterns": patterns,
    }
