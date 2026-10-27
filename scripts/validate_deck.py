# -*- coding: utf-8 -*-
"""检查 pptx 能否打开，以及本次改动是否到位。"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from lxml import etree

from pptkit.ooxml import A, P, load_pptx, parse, q, slide_order


def broken_targets(parts: dict[str, bytes]) -> list[str]:
    errors = []
    for name, blob in parts.items():
        if not name.endswith(".rels"):
            continue
        try:
            root = parse(blob)
        except etree.XMLSyntaxError:
            errors.append(f"{name} 无法解析")
            continue
        base = name.rsplit("/_rels/", 1)[0] if "/_rels/" in name else ""
        for rel in root:
            target = (rel.get("Target") or "").replace("\\", "/")
            if (not target or target.startswith("http") or target.startswith("#")
                    or rel.get("TargetMode") == "External"):
                continue
            if target.startswith("/"):
                resolved = target.lstrip("/")
            elif base:
                resolved = str(Path(base) / target)
            else:
                resolved = target
            resolved = Path(resolved).as_posix()
            while "/../" in "/" + resolved:
                parent, _, rest = resolved.partition("/../")
                parent = parent.rsplit("/", 1)[0] if "/" in parent else ""
                resolved = f"{parent}/{rest}" if parent else rest
            if resolved not in parts:
                errors.append(f"{name} -> {resolved}")
    order = slide_order(parts)
    listed = {row["part"] for row in order}
    for name in parts:
        if name.startswith("ppt/slides/slide") and name.endswith(".xml") and "/_rels/" not in name:
            if name not in listed:
                errors.append(f"幻灯片零件不在列表中: {name}")
    for row in order:
        if row["part"] not in parts:
            errors.append(f"列表指向缺失页: {row['part']}")
    return errors


def slide_plain(parts: dict[str, bytes], index: int) -> str:
    order = slide_order(parts)
    root = parse(parts[order[index - 1]["part"]])
    return "".join((t.text or "") for t in root.iter(q(A, "t")))


def diagram_ok(parts: dict[str, bytes], index: int) -> list[str]:
    order = slide_order(parts)
    root = parse(parts[order[index - 1]["part"]])
    errors = []
    groups = [g for g in root.iter(q(P, "grpSp")) if (g.find(q(P, "nvGrpSpPr")) is not None and (g.find(q(P, "nvGrpSpPr")).find(q(P, "cNvPr")) is not None) and g.find(q(P, "nvGrpSpPr")).find(q(P, "cNvPr")).get("name") == "结构图")]
    if not groups:
        errors.append(f"第 {index} 页没有名为「结构图」的组合")
        return errors
    grp = groups[-1]
    links = list(grp.iter(q(P, "cxnSp")))
    for link in links:
        st = link.find(".//" + q(A, "stCxn"))
        en = link.find(".//" + q(A, "endCxn"))
        if st is None or en is None or not st.get("id") or not en.get("id"):
            errors.append(f"第 {index} 页有连接符未连到图元")
    texts = "".join((t.text or "") for t in grp.iter(q(A, "t")))
    if not texts.strip():
        errors.append(f"第 {index} 页结构图里没有文字")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 pptx")
    parser.add_argument("pptx")
    parser.add_argument("--original", help="模板原件。只报告这次新增的关系错误")
    parser.add_argument("--require-text", action="append", default=[], help="形如 2:四、AI+辅助办公")
    parser.add_argument("--diagram-slide", type=int, action="append", default=[], help="这一页应有可编辑结构图")
    args = parser.parse_args()
    path = Path(args.pptx)
    if not zipfile.is_zipfile(path):
        raise SystemExit("不是有效的 pptx 压缩包")
    parts = load_pptx(path)
    errors = broken_targets(parts)
    if args.original:
        old = set(broken_targets(load_pptx(Path(args.original))))
        errors = [err for err in errors if err not in old]
    for item in args.require_text:
        if ":" not in item:
            raise SystemExit("--require-text 需要 页码:文字")
        index, text = item.split(":", 1)
        plain = slide_plain(parts, int(index))
        if text not in plain:
            errors.append(f"第 {index} 页缺少「{text}」")
    for index in args.diagram_slide:
        errors.extend(diagram_ok(parts, index))
    from pptkit.fonts import check_font_roles
    roles = None
    if args.original:
        from pptkit.profile import analyze
        roles = (analyze(Path(args.original)).get("fonts") or {}).get("roles")
    errors.extend(check_font_roles(parts, roles))
    from pptkit.layout_check import (
        text_diagram_overlaps, content_band_narrow,
        empty_shell_cards, peer_row_widths, section_tabs_gaps,
        section_tabs_text_fit,
    )
    errors.extend(text_diagram_overlaps(parts))
    errors.extend(content_band_narrow(parts))
    errors.extend(empty_shell_cards(parts))
    errors.extend(peer_row_widths(parts))
    errors.extend(section_tabs_gaps(parts))
    warnings = section_tabs_text_fit(parts)
    report = {
        "output": str(path),
        "slide_count": len(slide_order(parts)),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
