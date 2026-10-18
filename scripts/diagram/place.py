"""把结构图写进幻灯片：可编辑版插形状组，图片版插 PNG。"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from pptkit.ooxml import A, P, R, dump, max_shape_id, parse, q, slide_order

from .to_ooxml import EMU, _sub, _xfrm, svg_to_group
from pptkit.layout_check import assert_bbox_clears_intro


def add_editable(parts: dict[str, bytes], slide_index: int, svg: str, bbox: dict, font: str = "微软雅黑") -> int:
    assert_bbox_clears_intro(parts, slide_index, bbox)
    part = slide_order(parts)[slide_index - 1]["part"]
    root = parse(parts[part])
    grp = svg_to_group(svg, bbox, max_shape_id(root), font)
    root.find(q(P, "cSld")).find(q(P, "spTree")).append(grp)
    parts[part] = dump(root)
    return len(grp) - 2


def add_picture(parts: dict[str, bytes], slide_index: int, png: bytes, bbox: dict, name: str = "结构图") -> None:
    assert_bbox_clears_intro(parts, slide_index, bbox)
    part = slide_order(parts)[slide_index - 1]["part"]
    nums = [int(m.group(1)) for k in parts if (m := re.fullmatch(r"ppt/media/image(\d+)\.\w+", k))]
    media = f"ppt/media/image{max(nums, default=0) + 1}.png"
    parts[media] = png
    ct = parts["[Content_Types].xml"].decode("utf-8")
    if 'Extension="png"' not in ct and "Extension='png'" not in ct:
        ct = ct.replace("<Default ", '<Default Extension="png" ContentType="image/png"/><Default ', 1)
        parts["[Content_Types].xml"] = ct.encode("utf-8")
    rels_part = part.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    rels = parts[rels_part].decode("utf-8")
    rid_nums = [int(n) for n in re.findall(r'Id="rId(\d+)"', rels)]
    rid = f"rId{max(rid_nums, default=0) + 1}"
    rels = rels.replace(
        "</Relationships>",
        f'<Relationship Id="{rid}" Type="{R}/image" Target="../media/{Path(media).name}"/></Relationships>',
    )
    parts[rels_part] = rels.encode("utf-8")
    root = parse(parts[part])
    sid = max_shape_id(root) + 1
    pic = etree.Element(q(P, "pic"))
    nv = _sub(pic, P, "nvPicPr")
    _sub(nv, P, "cNvPr", id=sid, name=name)
    _sub(_sub(nv, P, "cNvPicPr"), A, "picLocks", noChangeAspect="1")
    _sub(nv, P, "nvPr")
    bf = _sub(pic, P, "blipFill")
    blip = _sub(bf, A, "blip")
    blip.set(q(R, "embed"), rid)
    _sub(_sub(bf, A, "stretch"), A, "fillRect")
    sp_pr = _sub(pic, P, "spPr")
    _xfrm(sp_pr, int(bbox["x"] * EMU), int(bbox["y"] * EMU), int(bbox["w"] * EMU), int(bbox["h"] * EMU))
    _sub(_sub(sp_pr, A, "prstGeom", prst="rect"), A, "avLst")
    root.find(q(P, "cSld")).find(q(P, "spTree")).append(pic)
    parts[part] = dump(root)
