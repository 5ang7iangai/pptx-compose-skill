"""风格库与版式库：扫描 catalog/ 目录，加风格或版式只需加文件，不改代码。

    catalog/styles/<id>/rules.md     写进提示词的风格规则
    catalog/styles/<id>/example.svg  范例（可无）
    catalog/styles/<id>/style.yaml   name 名称、look 一句人话、basis 参照的设计规范、use 适用场景、checks 硬性检查
    catalog/layouts/<id>.md          版式规则（结构）
    catalog/pairing.yaml             每种版式的预置风格和支持的风格
"""

from __future__ import annotations

from functools import lru_cache
import yaml

from common.paths import LAYOUTS_DIR, STYLES_DIR

DEFAULT_STYLE = "rounded"


def style_ids() -> list[str]:
    return sorted(p.name for p in STYLES_DIR.iterdir() if (p / "rules.md").exists())


def layout_ids() -> list[str]:
    return sorted(p.stem for p in LAYOUTS_DIR.glob("*.md"))


@lru_cache(maxsize=None)
def style_meta(style: str) -> dict:
    path = STYLES_DIR / style / "style.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def style_rules(style: str) -> str:
    if style not in style_ids():
        raise ValueError(f"未知风格 {style}，可选：{', '.join(style_ids())}")
    return (STYLES_DIR / style / "rules.md").read_text(encoding="utf-8").strip()


def style_example(style: str) -> str | None:
    path = STYLES_DIR / style / "example.svg"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def layout_rules(layout: str) -> str:
    if layout not in layout_ids():
        raise ValueError(f"未知版式 {layout}，可选：{', '.join(layout_ids())}")
    return (LAYOUTS_DIR / f"{layout}.md").read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def pairing() -> dict:
    path = STYLES_DIR.parent / "pairing.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("layouts", {})
    data.setdefault("fallback", DEFAULT_STYLE)
    return data


def _style_name(style: str) -> str:
    return style_meta(style).get("name") or style


def layout_style(layout: str | None, requested: str | None = None) -> tuple[str, str]:
    """确定这一版式用哪种风格。返回 (风格 id, 原因)。不支持就抛出 ValueError，信息里列出能选的中文名。"""
    table = pairing()["layouts"]
    fallback = pairing()["fallback"]
    if not layout:
        style = requested or fallback
        if style not in style_ids():
            raise ValueError(f"未知风格 {style}，可选：{', '.join(style_ids())}")
        return style, f"这一页没有锁定版式，使用{_style_name(style)}"
    if layout not in table:
        if layout not in layout_ids():
            raise ValueError(
                f"版式 {layout} 不在预置里。先按模板里的图，把结构和画法补进 "
                "catalog/layouts、catalog/styles 和 pairing.yaml，再出图。"
            )
        raise ValueError(f"版式 {layout} 还没有预置风格。先写入 catalog/pairing.yaml 的 default 和 styles，再出图。")
    row = table[layout]
    allowed = list(row["styles"])
    default = row["default"]
    if requested is None:
        return default, f"版式 {layout} 的预置风格"
    if requested not in style_ids():
        raise ValueError(f"未知风格 {requested}，可选：{', '.join(style_ids())}")
    if requested not in allowed:
        names = "、".join(_style_name(s) for s in allowed)
        raise ValueError(f"版式 {layout} 不支持{_style_name(requested)}。可以选：{names}")
    if requested == default:
        return requested, f"版式 {layout} 的预置风格"
    return requested, f"版式 {layout} 改用{_style_name(requested)}"


def bind_styles(diags: list[dict], requested: str | None = None) -> None:
    """同一版式收成一种风格，写回每个 diagram 的 style 和 style_reason。

    requested 是整稿想用的风格（新建一般不传）。某一页自己写了 style，则这一版式都用它。
    同一版式写出两种风格，或写出该版式不支持的风格，就抛出 ValueError，不出图。
    """
    groups: dict[str, list[dict]] = {}
    for diag in diags:
        groups.setdefault(diag.get("layout") or "", []).append(diag)
    for layout, group in groups.items():
        asked = list(dict.fromkeys(d["style"] for d in group if d.get("style")))
        if len(asked) > 1:
            names = "、".join(_style_name(s) for s in asked)
            raise ValueError(f"版式 {layout or '未指定'} 在同一份稿里只能用一种风格，现在写了 {names}")
        choice = asked[0] if asked else requested
        chosen, reason = layout_style(layout or None, choice)
        for diag in group:
            diag["style"] = chosen
            diag["style_reason"] = reason


def preset_gaps() -> list[str]:
    """版式、风格、配对三者对不齐的地方。空列表表示预置能直接用。"""
    issues = []
    layouts, styles = set(layout_ids()), set(style_ids())
    table = pairing()["layouts"]
    for lid in sorted(layouts - set(table)):
        issues.append(f"版式 {lid} 没有写进 pairing.yaml")
    used: set[str] = set()
    for lid, row in table.items():
        if lid not in layouts:
            issues.append(f"pairing.yaml 里的版式 {lid} 没有 layouts/{lid}.md")
        allowed = list((row or {}).get("styles") or [])
        default = (row or {}).get("default")
        if default not in allowed:
            issues.append(f"版式 {lid} 的 default 不在 styles 里")
        for sid in [default, *allowed]:
            if sid not in styles:
                issues.append(f"版式 {lid} 用了不存在的风格 {sid}")
        used.update(allowed)
    for sid in sorted(styles - used):
        issues.append(f"风格 {sid} 没有出现在任何版式的可选列表里")
    if pairing()["fallback"] not in styles:
        issues.append(f"fallback {pairing()['fallback']} 不是已有风格")
    return issues


def describe() -> dict:
    """列出全部风格和版式，供命令行 `svg_diagram.py list` 和文档核对。"""
    layouts = {}
    for lid in layout_ids():
        first = (LAYOUTS_DIR / f"{lid}.md").read_text(encoding="utf-8").strip().splitlines()[0]
        layouts[lid] = first.lstrip("# ").strip()
    return {
        "fallback": pairing()["fallback"],
        "styles": {sid: {k: style_meta(sid).get(k, "") for k in ("name", "look", "use", "basis")} for sid in style_ids()},
        "layouts": layouts,
        "pairing": {lid: pairing()["layouts"][lid] for lid in layout_ids() if lid in pairing()["layouts"]},
    }
