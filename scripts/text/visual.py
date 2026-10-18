"""
text/visual.py — S2 模板视觉理解

用视觉模型看模板缩略图 + 风格卡数据，输出对模板风格的自然语言描述。
无视觉模型时自动跳过，返回 None。
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from common.paths import PROMPTS

log = logging.getLogger(__name__)


async def profile_visual(
    template_path: str | Path,
    style_card: dict,
    llm,  # LLMAdapter instance
    *,
    prompt_path: str | Path | None = None,
    max_thumbnails: int = 8,
) -> dict | None:
    """
    用视觉模型分析模板缩略图，返回视觉理解 JSON。
    如果 LLM 没有配置 vision_model，返回 None。
    """
    if not llm.cfg.vision_model:
        log.info("未配置视觉模型，S2 跳过")
        return None

    from llm.adapter import as_json, load_prompt

    if prompt_path is None:
        prompt_path = PROMPTS / "text" / "visual_profile.md"

    template_path = Path(template_path)

    # 导出缩略图
    thumbnails = await _export_thumbnails(template_path, style_card, max_thumbnails)
    if not thumbnails:
        log.warning("无法导出缩略图，S2 跳过")
        return None

    log.info("导出 %d 张缩略图", len(thumbnails))

    # 准备风格卡摘要（不传全量，选关键字段）
    style_summary = _style_card_summary(style_card)

    # 调用视觉模型
    prompt_template = load_prompt(prompt_path)
    user_msg = prompt_template.replace(
        "{style_card_json}", as_json(style_summary)
    ).replace(
        "{image_count}", str(len(thumbnails))
    )

    system_msg = "你是一名专业的演示文稿设计顾问。请综合缩略图和数据，输出 JSON。"

    raw = await llm.ask_vision(system_msg, user_msg, thumbnails)
    result = _parse_json(raw)

    # 清理临时缩略图
    for t in thumbnails:
        try:
            t.unlink(missing_ok=True)
        except Exception:
            pass

    return result


async def _export_thumbnails(
    template_path: Path, style_card: dict, max_count: int
) -> list[Path]:
    """
    把 pptx 的关键页导出为 PNG 缩略图。
    优先选：封面、目录、典型正文页（含图和不含图的各一）、致谢页。
    """
    thumbnails: list[Path] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="pptx_thumb_"))

    # 选页策略：从风格卡的 slides 里选典型页
    slides_meta = style_card.get("slides", [])
    selected_indices: list[int] = []

    # 按 role 分组；缩略图取的是页内最大图片，没图片的页导不出，只在有图片的页里选
    role_map: dict[str, list[int]] = {}
    for i, s in enumerate(slides_meta):
        if s.get("picture_count", 1):
            role_map.setdefault(s.get("role", "unknown"), []).append(i)

    # 选代表页
    for role in ["cover", "toc", "content", "ending"]:
        pages = role_map.get(role, [])
        if pages:
            selected_indices.append(pages[0])
            if role == "content" and len(pages) > 1:
                selected_indices.append(pages[len(pages) // 2])

    # 补足到 max_count
    for i in (i for pages in role_map.values() for i in pages):
        if len(set(selected_indices)) >= max_count:
            break
        if i not in selected_indices:
            selected_indices.append(i)

    selected_indices = sorted(set(selected_indices))[:max_count]

    # 尝试用 Playwright + LibreOffice 导出，或用 python-pptx 提取幻灯片内的图片作为替代
    try:
        thumbnails = await _export_via_pptx_images(template_path, selected_indices, tmp_dir)
    except Exception as e:
        log.warning("缩略图导出失败: %s", e)

    return thumbnails


async def _export_via_pptx_images(
    template_path: Path, indices: list[int], tmp_dir: Path
) -> list[Path]:
    """
    简化方案：用 python-pptx 读取每页的所有形状，
    如果有图片则导出最大的那张作为页面缩略图的近似替代。
    如果页面没图片，跳过该页。
    
    注：真正的缩略图导出需要 LibreOffice headless 或 Playwright 渲染 PPTX。
    这里用图片提取作为轻量级替代，后续可升级。
    """
    from pptx import Presentation

    prs = Presentation(str(template_path))
    slides = list(prs.slides)
    thumbnails: list[Path] = []

    for idx in indices:
        if idx >= len(slides):
            continue
        slide = slides[idx]
        largest_image = None
        largest_area = 0

        for shape in slide.shapes:
            if shape.shape_type == 13:  # Picture
                area = (shape.width or 0) * (shape.height or 0)
                if area > largest_area:
                    largest_area = area
                    largest_image = shape

        if largest_image and hasattr(largest_image, "image"):
            ext = largest_image.image.content_type.split("/")[-1]
            if ext == "jpeg":
                ext = "jpg"
            out_path = tmp_dir / f"slide_{idx+1:02d}.{ext}"
            out_path.write_bytes(largest_image.image.blob)
            thumbnails.append(out_path)

    return thumbnails


def _style_card_summary(style_card: dict) -> dict:
    """提取风格卡的关键字段，不传全量"""
    return {
        "canvas": style_card.get("canvas", {}),
        "palette": style_card.get("palette", {}),
        "fonts": style_card.get("fonts", {}),
        "slide_count": len(style_card.get("slides", [])),
        "slide_roles": [
            {"index": s.get("index"), "role": s.get("role", ""), "layout": s.get("layout", "")}
            for s in style_card.get("slides", [])
        ],
    }


def _parse_json(raw: str) -> dict:
    """从 LLM 返回中提取 JSON"""
    from llm.parse import parse_llm_json
    return parse_llm_json(raw)


def save_visual_profile(profile: dict | None, output_path: str | Path) -> Path | None:
    if profile is None:
        return None
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("视觉理解已保存: %s", out)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 3:
        print("用法: python -m text.visual <风格卡.json> <config.yaml> [模板.pptx] [输出.json]")
        sys.exit(1)

    style_path = Path(sys.argv[1])
    config_path = Path(sys.argv[2])
    template_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    output_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("out/视觉理解.json")

    style_card = json.loads(style_path.read_text(encoding="utf-8"))

    from llm.adapter import LLMAdapter
    adapter = LLMAdapter(config_path)

    if template_path:
        result = asyncio.run(profile_visual(template_path, style_card, adapter))
    else:
        result = None
        print("未提供模板路径，跳过")

    if result:
        save_visual_profile(result, output_path)
        print("[OK] 视觉理解已生成")
    else:
        print("[SKIP] 无视觉模型或导出失败")
