"""
text/outline.py — S3 叙事大纲 + 页纲展开

两步 LLM 调用：
  1. 叙事大纲：确定故事节拍、页数分配、全局密度
  2. 页纲展开：为每页规划文字量、引用事实、图形类型

要在两步之间人工确认，用 compose.py --until S3 停下，改 -过程/S3_大纲.json 后 --resume。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from common.paths import PROMPTS

log = logging.getLogger(__name__)


async def write_outline(
    material_summary: dict,
    style_card: dict,
    requirement: str,
    llm,  # LLMAdapter
    *,
    visual_profile: dict | None = None,
    page_slots: dict[int, dict] | None = None,
    cover_title_chars: int = 0,
    prompt_dir: str | Path | None = None,
) -> dict:
    """
    S3：叙事大纲 + 页纲展开。返回的页纲里带 narrative（叙事大纲），S5 审查要用。

    Args:
        material_summary: S1 的输出（材料摘要，事实已编号）
        style_card: profile_deck 的输出（模板风格卡）
        requirement: 用户的制作要求
        llm: LLMAdapter 实例
        visual_profile: S2 的输出（视觉理解），可选
        page_slots: 正文样例页的容量 {页码: pptkit.autofill.page_capacity + diagram_area}；
            不给时退回风格卡里的文字框统计
        cover_title_chars: 封面标题框能放几个汉字宽（pptkit.autofill.cover_title_room），0 表示不限
        prompt_dir: 提示词目录，默认 prompts/text/
    """
    prompt_dir = Path(prompt_dir or PROMPTS / "text")
    log.info("S3-1: 生成叙事大纲...")
    narrative = await _generate_narrative(material_summary, style_card, requirement, visual_profile, llm, prompt_dir)
    log.info("S3-2: 展开逐页页纲...")
    outline = await _expand_pages(narrative, material_summary, style_card, requirement, page_slots,
                                  cover_title_chars, llm, prompt_dir)
    outline["narrative"] = narrative
    return outline


async def _generate_narrative(
    summary: dict, style_card: dict, requirement: str,
    visual_profile: dict | None, llm, prompt_dir: Path,
) -> dict:
    from llm.adapter import as_json, load_prompt

    slides_meta = style_card.get("slides", [])
    role_count: dict[str, int] = {}
    for s in slides_meta:
        role = s.get("role", "content")
        role_count[role] = role_count.get(role, 0) + 1
    page_type_dist = "、".join(f"{r} {c}页" for r, c in role_count.items())

    vp_summary = ""
    if visual_profile and not visual_profile.get("_parse_error"):
        vp_summary = (
            f"模板视觉风格：{visual_profile.get('overall_tone', '未知')}\n"
            f"视觉节奏：{visual_profile.get('visual_rhythm', '未知')}\n"
            f"图形风格：{visual_profile.get('diagram_style_description', '未知')}"
        )

    user_msg = load_prompt(
        prompt_dir / "outline_narrative.md",
        material_summary=as_json(summary),
        requirement=requirement,
        template_page_count=str(len(slides_meta)),
        page_type_distribution=page_type_dist,
        visual_profile_summary=vp_summary or "（无视觉理解数据）",
    )
    raw = await llm.ask("你是一名资深的企业汇报材料策划师。请输出 JSON。", user_msg)
    return _parse_json(raw)


def describe_pages(style_card: dict, page_slots: dict[int, dict] | None) -> str:
    """可选的正文样例页，一页一行：原标题、能装多少字、有没有图区。页码与 clone_from 同为 1 起。"""
    lines = []
    for s in style_card.get("slides", []):
        if s.get("role") != "content":
            continue
        idx = s["index"]
        cap = (page_slots or {}).get(idx)
        if cap is None:
            slots = s.get("text_slots") or []
            lines.append(f"页{idx}：{len(slots)} 个文字框，约 {sum(len(t.get('text', '')) for t in slots)} 字")
            continue
        head = f"页{idx}「{cap['title']}」：" if cap.get("title") else f"页{idx}："
        if cap["cards"]:
            body = f"导语框约 {cap['intro_chars']} 字；{len(cap['cards'])} 张卡片，每张约 {round(sum(cap['cards']) / len(cap['cards']))} 字（一张放一条要点）"
        else:
            body = f"一个正文框约 {cap['intro_chars']} 字，写成一段话，不要拆成多条"
            if cap.get("intro_lines"):
                body += f"；约 {cap['intro_lines']} 行、每行约 {cap['line_chars']} 字"
        lines.append(head + body + ("；有图区" if cap.get("diagram_area") else "；无图区"))
    return "\n".join(lines) or "（无正文样例页）"


async def _expand_pages(
    narrative: dict, summary: dict, style_card: dict, requirement: str,
    page_slots: dict[int, dict] | None, cover_title_chars: int, llm, prompt_dir: Path,
) -> dict:
    from llm.adapter import as_json, load_prompt

    user_msg = load_prompt(
        prompt_dir / "outline_pages.md",
        requirement=requirement,
        cover_title_rule=(f"；封面只有一行，不超过 {cover_title_chars} 个汉字宽（西文和数字约两个算一个字）"
                          if cover_title_chars else ""),
        narrative_outline=as_json(narrative),
        material_summary=as_json(summary),
        available_pages=describe_pages(style_card, page_slots),
    )
    raw = await llm.ask("你是一名资深的企业汇报材料策划师。请输出 JSON。", user_msg)
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    from llm.parse import parse_llm_json
    return parse_llm_json(raw)


def save_outline(outline: dict, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    page_count = len(outline.get("pages", []))
    log.info("大纲已保存: %s (%d 页)", out, page_count)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 4:
        print("用法: python -m text.outline <摘要.json> <风格卡.json> <config.yaml> [要求] [视觉理解.json] [输出.json]")
        sys.exit(1)

    summary_path = Path(sys.argv[1])
    style_path = Path(sys.argv[2])
    config_path = Path(sys.argv[3])
    requirement = sys.argv[4] if len(sys.argv) > 4 else "请根据材料制作一份汇报PPT"
    vp_path = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    output_path = Path(sys.argv[6]) if len(sys.argv) > 6 else Path("out/大纲.json")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    style_card = json.loads(style_path.read_text(encoding="utf-8"))
    vp = json.loads(vp_path.read_text(encoding="utf-8")) if vp_path and vp_path.exists() else None

    from llm.adapter import LLMAdapter
    adapter = LLMAdapter(config_path)

    outline = asyncio.run(write_outline(summary, style_card, requirement, adapter, visual_profile=vp))
    save_outline(outline, output_path)
    print(f"[OK] 大纲已生成: {len(outline.get('pages', []))} 页")
