# -*- coding: utf-8 -*-
"""读写 pptx 包。幻灯片零件按字节复制，避免整页重排命名空间。"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU = 914400

SLIDE_CT = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
NOTES_CT = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def load_pptx(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {
            info.filename: zf.read(info.filename)
            for info in zf.infolist()
            if not info.is_dir()
        }


def save_pptx(path: Path, parts: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = sorted(parts)
    if "[Content_Types].xml" in parts:
        names.remove("[Content_Types].xml")
        names.insert(0, "[Content_Types].xml")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, parts[name])


def require_different(src: Path, dest: Path) -> None:
    if src.resolve() == dest.resolve():
        raise SystemExit("输出路径不能与原件相同。请另存为新文件。")


def parse(xml: bytes) -> etree._Element:
    return etree.fromstring(xml)


def dump(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def slide_rels_map(parts: dict[str, bytes]) -> dict[str, str]:
    root = parse(parts["ppt/_rels/presentation.xml.rels"])
    out = {}
    for rel in root:
        if rel.get("Type", "").endswith("/slide"):
            out[rel.get("Id")] = rel.get("Target")
    return out


def slide_order(parts: dict[str, bytes]) -> list[dict]:
    """按放映顺序返回幻灯片。index 从 1 起。"""
    pres = parse(parts["ppt/presentation.xml"])
    rels = slide_rels_map(parts)
    lst = pres.find(q(P, "sldIdLst"))
    rows = []
    for i, sld in enumerate(list(lst), start=1):
        rid = sld.get(q(R, "id"))
        target = rels[rid]
        part = "ppt/" + target.lstrip("/")
        rows.append(
            {
                "index": i,
                "id": int(sld.get("id")),
                "rid": rid,
                "target": target,
                "part": part,
            }
        )
    return rows


def joined_text(xml: bytes) -> str:
    root = parse(xml)
    return "".join((t.text or "") for t in root.iter(q(A, "t")))


def max_rid(rels_xml: bytes) -> int:
    nums = [int(n) for n in re.findall(r'Id="rId(\d+)"', rels_xml.decode("utf-8"))]
    return max(nums) if nums else 0


def _insert_before(xml: bytes, end_tag: str, snippet: str) -> bytes:
    text = xml.decode("utf-8")
    if end_tag not in text:
        raise SystemExit(f"找不到 {end_tag}")
    text = text.replace(end_tag, snippet + end_tag, 1)
    return text.encode("utf-8")


def add_override(parts: dict[str, bytes], part_name: str, content_type: str) -> None:
    text = parts["[Content_Types].xml"].decode("utf-8")
    if f'PartName="{part_name}"' in text:
        return
    snippet = f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
    parts["[Content_Types].xml"] = _insert_before(
        parts["[Content_Types].xml"], "</Types>", snippet
    )


def remove_override(parts: dict[str, bytes], part_name: str) -> None:
    text = parts["[Content_Types].xml"].decode("utf-8")
    text = re.sub(
        rf'<Override PartName="{re.escape(part_name)}" ContentType="[^"]*"/>',
        "",
        text,
        count=1,
    )
    parts["[Content_Types].xml"] = text.encode("utf-8")


def _next_slide_filename(parts: dict[str, bytes]) -> str:
    nums = [
        int(m.group(1))
        for name in parts
        if (m := re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name))
    ]
    return f"slide{max(nums) + 1}.xml"


def _content_type_of(parts: dict[str, bytes], part_name: str) -> str | None:
    text = parts["[Content_Types].xml"].decode("utf-8")
    needle = "/" + part_name
    for block in re.findall(r"<Override\b[^>]*/>", text):
        if f'PartName="{needle}"' not in block:
            continue
        found = re.search(r'ContentType="([^"]+)"', block)
        if found:
            return found.group(1)
    return None


def _duplicate_exclusive_targets(parts: dict[str, bytes], rels_text: str) -> str:
    """标签、批注不能两页共用，否则 PowerPoint 拒绝打开。"""
    exclusive = ("/tags", "/comments")
    cache: dict[str, str] = {}

    def next_name(folder: str, prefix: str) -> str:
        nums = [
            int(m.group(1))
            for name in parts
            if (m := re.fullmatch(rf"{re.escape(folder)}/{prefix}(\d+)\.xml", name))
        ]
        n = max(nums) + 1 if nums else 1
        return f"{folder}/{prefix}{n}.xml"

    def copy_target(target: str) -> str:
        if target in cache:
            return cache[target]
        filename = Path(target.replace("\\", "/")).name
        old = next(
            (
                key
                for key in parts
                if key.endswith("/" + filename)
                and any(bit in key for bit in ("/tags/", "/comments/"))
            ),
            None,
        )
        if old is None:
            cache[target] = target
            return target
        folder, prefix = old.rsplit("/", 1)[0], Path(filename).stem
        prefix = re.sub(r"\d+$", "", prefix) or "part"
        new_part = next_name(folder, prefix)
        parts[new_part] = parts[old]
        content_type = _content_type_of(parts, old)
        if content_type:
            add_override(parts, "/" + new_part, content_type)
        old_rels = old.replace(f"{folder}/", f"{folder}/_rels/") + ".rels"
        if old_rels in parts:
            new_rels = new_part.replace(f"{folder}/", f"{folder}/_rels/") + ".rels"
            parts[new_rels] = parts[old_rels]
        new_target = str(Path(target.replace("\\", "/")).with_name(Path(new_part).name)).replace("\\", "/")
        cache[target] = new_target
        return new_target

    def repl_block(match: re.Match) -> str:
        block = match.group(0)
        if not any(kind in block for kind in exclusive):
            return block
        found = re.search(r'Target="([^"]+)"', block)
        if not found:
            return block
        target = found.group(1)
        return block.replace(f'Target="{target}"', f'Target="{copy_target(target)}"', 1)

    return re.sub(r"<Relationship\b[^>]*/>", repl_block, rels_text)


def _next_notes_filename(parts: dict[str, bytes]) -> str:
    nums = [
        int(m.group(1))
        for name in parts
        if (m := re.fullmatch(r"ppt/notesSlides/notesSlide(\d+)\.xml", name))
    ]
    n = max(nums) + 1 if nums else 1
    return f"notesSlide{n}.xml"


def clone_slide(parts: dict[str, bytes], source_index: int, before_index: int | None) -> int:
    """复制一页并插入。before_index 为插入后的新序号；None 则加在末尾。返回新序号。"""
    order = slide_order(parts)
    if source_index < 1 or source_index > len(order):
        raise SystemExit(f"没有第 {source_index} 页")
    src = order[source_index - 1]
    new_name = _next_slide_filename(parts)
    new_part = f"ppt/slides/{new_name}"
    parts[new_part] = parts[src["part"]]

    src_rels = src["part"].replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    rels_text = parts[src_rels].decode("utf-8") if src_rels in parts else ""
    notes_match = re.search(
        r'Id="(rId\d+)"[^>]*Type="[^"]*notesSlide"[^>]*Target="([^"]+)"',
        rels_text,
    )
    if notes_match is None:
        notes_match = re.search(
            r'Type="[^"]*notesSlide"[^>]*Target="([^"]+)"[^>]*Id="(rId\d+)"',
            rels_text,
        )
        if notes_match:
            notes_target = notes_match.group(1)
        else:
            notes_target = None
    else:
        notes_target = notes_match.group(2)

    if notes_target:
        old_notes = "ppt/" + notes_target.replace("../", "").lstrip("/")
        # Target 形如 ../notesSlides/notesSlide6.xml
        if old_notes not in parts:
            old_notes = "ppt/notesSlides/" + Path(notes_target).name
        new_notes = _next_notes_filename(parts)
        new_notes_part = f"ppt/notesSlides/{new_notes}"
        if old_notes in parts:
            parts[new_notes_part] = parts[old_notes]
            old_notes_rels = old_notes.replace("ppt/notesSlides/", "ppt/notesSlides/_rels/") + ".rels"
            if old_notes_rels in parts:
                new_notes_rels = new_notes_part.replace(
                    "ppt/notesSlides/", "ppt/notesSlides/_rels/"
                ) + ".rels"
                notes_rels = parts[old_notes_rels].decode("utf-8")
                notes_rels = notes_rels.replace(Path(src["part"]).name, new_name)
                parts[new_notes_rels] = notes_rels.encode("utf-8")
            rels_text = rels_text.replace(Path(old_notes).name, new_notes)
            add_override(parts, "/" + new_notes_part, NOTES_CT)

    new_rels = new_part.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    if rels_text:
        rels_text = _duplicate_exclusive_targets(parts, rels_text)
        parts[new_rels] = rels_text.encode("utf-8")

    add_override(parts, "/" + new_part, SLIDE_CT)

    pres_rels = parts["ppt/_rels/presentation.xml.rels"]
    new_rid = f"rId{max_rid(pres_rels) + 1}"
    snippet = (
        f'<Relationship Id="{new_rid}" '
        f'Type="{R}/slide" Target="slides/{new_name}"/>'
    )
    parts["ppt/_rels/presentation.xml.rels"] = _insert_before(
        pres_rels, "</Relationships>", snippet
    )

    pres = parts["ppt/presentation.xml"].decode("utf-8")
    ids = [int(n) for n in re.findall(r'<p:sldId id="(\d+)"', pres)]
    new_id = max(ids) + 1 if ids else 256
    sld_xml = f'<p:sldId id="{new_id}" r:id="{new_rid}"/>'
    tags = list(re.finditer(r"<p:sldId\b[^>]*/>", pres))
    if not tags:
        raise SystemExit("presentation.xml 里没有幻灯片列表")
    if before_index is None or before_index > len(tags):
        insert_at = tags[-1].end()
        new_index = len(tags) + 1
    else:
        if before_index < 1:
            raise SystemExit("插入位置无效")
        insert_at = tags[before_index - 1].start()
        new_index = before_index
    pres = pres[:insert_at] + sld_xml + pres[insert_at:]
    parts["ppt/presentation.xml"] = pres.encode("utf-8")
    return new_index


def delete_slide(parts: dict[str, bytes], index: int) -> None:
    order = slide_order(parts)
    if index < 1 or index > len(order):
        raise SystemExit(f"没有第 {index} 页")
    row = order[index - 1]
    pres = parts["ppt/presentation.xml"].decode("utf-8")
    pres = re.sub(
        rf'<p:sldId id="{row["id"]}" r:id="{row["rid"]}"/>',
        "",
        pres,
        count=1,
    )
    parts["ppt/presentation.xml"] = pres.encode("utf-8")
    rels = parts["ppt/_rels/presentation.xml.rels"].decode("utf-8")
    rels = re.sub(
        rf'<Relationship Id="{row["rid"]}"[^>]*/>',
        "",
        rels,
        count=1,
    )
    parts["ppt/_rels/presentation.xml.rels"] = rels.encode("utf-8")

    rels_part = row["part"].replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    owned = []
    if rels_part in parts:
        root = parse(parts[rels_part])
        for rel in root:
            target = rel.get("Target") or ""
            kind = rel.get("Type") or ""
            if kind.endswith("/slideLayout") or kind.endswith("/image"):
                continue
            owned.append("ppt/" + target.replace("../", "").lstrip("/"))
        del parts[rels_part]
    remove_override(parts, "/" + row["part"])
    del parts[row["part"]]
    # 只删除不再被任何关系引用的备注和标签
    for part in owned:
        blob = "\n".join(
            v.decode("utf-8", errors="ignore")
            for k, v in parts.items()
            if k.endswith(".rels")
        )
        needle = Path(part).name
        if needle not in blob and part in parts:
            if part.startswith("ppt/notesSlides/"):
                extra = part.replace("ppt/notesSlides/", "ppt/notesSlides/_rels/") + ".rels"
            else:
                extra = ""
            del parts[part]
            remove_override(parts, "/" + part)
            if extra and extra in parts:
                del parts[extra]


def move_slide(parts: dict[str, bytes], index: int, before_index: int) -> None:
    """把 index 页挪到 before_index 之前。before_index 用移动前的序号。"""
    order = slide_order(parts)
    if index < 1 or index > len(order):
        raise SystemExit(f"没有第 {index} 页")
    pres = parts["ppt/presentation.xml"].decode("utf-8")
    tags = list(re.finditer(r"<p:sldId\b[^>]*/>", pres))
    block = tags[index - 1].group(0)
    pres_wo = pres[: tags[index - 1].start()] + pres[tags[index - 1].end() :]
    tags2 = list(re.finditer(r"<p:sldId\b[^>]*/>", pres_wo))
    # 删除后，原先 before_index 及之后的序号减 1（若 before 在 index 之后）
    if before_index > index:
        dest = before_index - 1
    else:
        dest = before_index
    dest = max(1, min(dest, len(tags2) + 1))
    if dest > len(tags2):
        insert_at = tags2[-1].end()
    else:
        insert_at = tags2[dest - 1].start()
    pres_wo = pres_wo[:insert_at] + block + pres_wo[insert_at:]
    parts["ppt/presentation.xml"] = pres_wo.encode("utf-8")


def find_ending_index(parts: dict[str, bytes]) -> int | None:
    for row in slide_order(parts):
        if "谢谢" in "".join(joined_text(parts[row["part"]]).split()):
            return row["index"]
    return None


def shape_text(sp: etree._Element) -> str:
    return "".join((t.text or "") for t in sp.iter(q(A, "t")))


def _local(tag: str) -> str:
    return tag.split("}")[-1] if tag else ""


def _own_xfrm(el: etree._Element):
    for child in el:
        if _local(child.tag) in ("spPr", "grpSpPr"):
            xfrm = child.find(q(A, "xfrm"))
            if xfrm is not None:
                return xfrm
    return None


def _box_of(xfrm) -> tuple[int, int, int, int] | None:
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


def _group_map(el: etree._Element):
    xfrm = None
    for child in el:
        if _local(child.tag) == "grpSpPr":
            xfrm = child.find(q(A, "xfrm"))
    box = _box_of(xfrm)
    if xfrm is None or box is None:
        return None
    ch_off = xfrm.find(q(A, "chOff"))
    ch_ext = xfrm.find(q(A, "chExt"))
    return (
        *box,
        int(ch_off.get("x") or 0) if ch_off is not None else 0,
        int(ch_off.get("y") or 0) if ch_off is not None else 0,
        int(ch_ext.get("cx") or 1) if ch_ext is not None else 1,
        int(ch_ext.get("cy") or 1) if ch_ext is not None else 1,
    )


def _apply_group(box, grp):
    x, y, w, h = box
    gx, gy, gw, gh, cx, cy, cw, ch = grp
    cw = cw or 1
    chh = ch or 1
    return (
        int(gx + (x - cx) * gw / cw),
        int(gy + (y - cy) * gh / chh),
        int(w * gw / cw),
        int(h * gh / chh),
    )


def absolute_shapes(root: etree._Element) -> list[dict]:
    """每个文字形状的绝对位置（英寸）。组合内的形状已换算到幻灯片坐标。"""
    found = []

    def walk(el, grp):
        tag = _local(el.tag)
        if tag == "grpSp":
            g = _group_map(el)
            use = g if g and g[2] and g[3] else grp
            for child in el:
                if _local(child.tag) not in ("nvGrpSpPr", "grpSpPr"):
                    walk(child, use)
            return
        if tag != "sp":
            return
        box = _box_of(_own_xfrm(el))
        if box and grp:
            box = _apply_group(box, grp)
        if not box:
            return
        nv = el.find(".//" + q(P, "cNvPr"))
        found.append(
            {
                "el": el,
                "name": nv.get("name") if nv is not None else "",
                "text": shape_text(el),
                "x": box[0] / EMU,
                "y": box[1] / EMU,
                "w": box[2] / EMU,
                "h": box[3] / EMU,
            }
        )

    tree = root.find(q(P, "cSld"))
    sp_tree = tree.find(q(P, "spTree")) if tree is not None else None
    if sp_tree is None:
        return found
    for child in sp_tree:
        if _local(child.tag) in ("nvGrpSpPr", "grpSpPr"):
            continue
        walk(child, None)
    return found


def max_shape_id(root: etree._Element) -> int:
    nums = []
    for nv in root.iter(q(P, "cNvPr")):
        if nv.get("id") and nv.get("id").isdigit():
            nums.append(int(nv.get("id")))
    return max(nums) if nums else 1
