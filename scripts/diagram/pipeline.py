"""任务脚本共用的出图流程：已有 SVG（助手写）→ 检查 / 渲染 → 图片版、可编辑版两份 pptx。

add_chapter、redraw_pages、stages/apply_diagrams 都走这里；不调用外部模型。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pptkit.ooxml import save_pptx, slide_order

from .catalog import bind_styles
from .checks import check_diagram
from .normalize import drop_comments
from .place import add_editable, add_picture
from .render import render_png

VARIANTS = ("图片版", "可编辑版")


def variant_path(dest: Path, tag: str) -> Path:
    return dest.with_name(f"{dest.stem}-{tag}{dest.suffix}")


def figure_dir(dest: Path) -> Path:
    d = dest.with_name(f"{dest.stem}-图")
    d.mkdir(parents=True, exist_ok=True)
    return d


def deck_font(card: dict) -> str:
    """可编辑版文字用的字体：主题东亚字体，没有就取页面上用得最多的实名字体。"""
    fonts = card.get("fonts") or {}
    used = fonts.get("used") or []
    chart = (fonts.get("roles") or {}).get("chart") or {}
    return chart.get("ea") or fonts.get("ea") or next((u["name"] for u in used if not u["name"].startswith("+")), "微软雅黑")


def resolve_diagram(spec: dict, page: dict) -> dict | None:
    """页上的 diagram 合上 spec 顶层的 style、fonts，页一级的 feedback 并进 diagram。

    没写 style 就不填，交给 bind_styles 按版式预置。不要在这里默认成圆角卡片。
    """
    diag = page.get("diagram")
    if not diag:
        return None
    diag = {**diag, "fonts": {**(spec.get("fonts") or {}), **(diag.get("fonts") or {})}}
    if not diag.get("style") and spec.get("style"):
        diag["style"] = spec["style"]
    if page.get("feedback"):
        diag["feedback"] = [*diag.get("feedback", []), *page["feedback"]]
    return diag


def make_job(fig_dir: Path, slide: int, label: int, diag: dict, regen: bool = False) -> dict:
    """slide 是产出里的页码；label 是缓存文件名里的页码（重做原稿时用原稿页码）。"""
    stem = f"{label}-{diag.get('name', '结构图')}"
    return {"slide": slide, "diagram": diag, "regen": regen,
            "svg_path": fig_dir / f"{stem}.svg", "png_path": fig_dir / f"{stem}.png"}


def prepare_svgs(jobs: list[dict], palette: dict | None = None,
                 regen: bool = False, fix: bool = False, svg_dir: Path | str | None = None) -> None:
    """每个 job 补上 svg 文本、problems，并渲染 png。

    SVG 必须已由助手写到 job["svg_path"]（或 svg_dir 下同名文件）。
    本函数不调用外部模型。palette 由调用方传入供后续扩展，当前检查不依赖它。
    regen/fix 仅提示助手改文件，不自动生成。
    """
    if svg_dir:
        svg_dir = Path(svg_dir)
        for j in jobs:
            alt = svg_dir / j["svg_path"].name
            if alt.exists() and not j["svg_path"].exists():
                j["svg_path"] = alt
    missing = [str(j["svg_path"]) for j in jobs if not j["svg_path"].exists()]
    if missing:
        raise SystemExit(
            "缺少助手写好的 SVG（pptx-unit 不调用外部模型）。"
            "请按 prompts/diagram/generate_svg.md 写好后重试：\n  " + "\n  ".join(missing)
        )
    if regen or fix:
        print(
            "提示: --regen/--fix 在 pptx-unit 中不调模型；"
            "请助手按 checks 问题（fix_svg.md）改写磁盘 SVG 后重跑。",
            flush=True,
        )
    for job in jobs:
        job["svg"] = drop_comments(job["svg_path"].read_text(encoding="utf-8"))
        job["problems"] = check_diagram(job["svg"], job["diagram"])
        render_png(job["svg"], job["png_path"])


def write_variants(parts: dict[str, bytes], jobs: list[dict], dest: Path, font: str,
                   font_roles: dict | None = None) -> dict:
    """同一份 parts 出两份：图片版贴 PNG，可编辑版插原生形状。"""
    from pptkit.fonts import check_font_roles
    picture_parts, editable_parts = dict(parts), dict(parts)
    for job in jobs:
        bbox = job["diagram"]["bbox"]
        add_picture(picture_parts, job["slide"], job["png_path"].read_bytes(), bbox)
        job["shapes"] = add_editable(editable_parts, job["slide"], job["svg"], bbox, font)
    pic_out, edit_out = variant_path(dest, "图片版"), variant_path(dest, "可编辑版")
    save_pptx(pic_out, picture_parts)
    save_pptx(edit_out, editable_parts)
    return {"图片版": str(pic_out), "可编辑版": str(edit_out),
            "_checks": check_font_roles(editable_parts, font_roles)}


def job_summary(jobs: list[dict]) -> list[dict]:
    return [{"slide": j["slide"], "svg": str(j["svg_path"]), "png": str(j["png_path"]),
             "layout": j["diagram"].get("layout"), "style": j["diagram"].get("style"),
             "style_reason": j["diagram"].get("style_reason"),
             "shapes": j.get("shapes"), "problems": j.get("problems")} for j in jobs]


def discard_workfiles(dest: Path) -> None:
    """两份 pptx 已经含有文字和图。过程目录、图缓存、报告只在生成时用，写完就删。"""
    for path in (dest.with_name(f"{dest.stem}-图"), dest.with_name(f"{dest.stem}-过程")):
        if path.is_dir():
            shutil.rmtree(path)
    report = dest.with_name(f"{dest.stem}-报告.json")
    if report.is_file():
        report.unlink()


def finish(parts: dict[str, bytes], jobs: list[dict], dest: Path, font: str, result: dict,
           font_roles: dict | None = None) -> dict:
    """写两版。检查结果留在返回值里，由入口打到屏幕上，不落盘。"""
    outputs = write_variants(parts, jobs, dest, font, font_roles)
    result["checks"] = outputs.pop("_checks", [])
    result["outputs"] = outputs
    result["diagrams"] = job_summary(jobs)
    result["slide_count"] = len(slide_order(parts))
    discard_workfiles(dest)
    return result
