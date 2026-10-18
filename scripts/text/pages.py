"""
text/pages.py — S4 逐页撰写

根据 S3 页纲为每页独立撰写正文内容。
默认并行调用 LLM，遇到 RateLimitError 时自动降级为串行。\nrevise_pages 按 S5 审查意见重写有问题的页。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from common.paths import PROMPTS

log = logging.getLogger(__name__)


async def write_all_pages(
    page_outline: dict,
    material_summary: dict,
    llm,  # LLMAdapter
    *,
    prompt_path: str | Path | None = None,
) -> list[dict]:
    """
    为页纲中的每一页并行撰写正文。

    Returns:
        与 page_outline["pages"] 等长的正文列表
    """
    pages = page_outline.get("pages", [])
    template = _template(prompt_path)
    facts = fact_table(material_summary)
    log.info("开始撰写 %d 页内容...", len(pages))
    results = await llm.run_parallel([
        _write_single_page(page, facts, _prev_page_summary(pages, i), template, llm)
        for i, page in enumerate(pages)
    ])
    log.info("全部 %d 页撰写完成", len(results))
    return results


async def revise_pages(
    page_outline: dict,
    material_summary: dict,
    contents: list[dict],
    notes: dict[int, list[str]],
    llm,
    *,
    prompt_path: str | Path | None = None,
) -> list[dict]:
    """按 S5 审查意见重写有问题的页（并行一轮），其余页原样返回。notes: {页序号: [意见]}。"""
    pages = page_outline.get("pages", [])
    targets = [i for i in sorted(notes) if 0 <= i < min(len(pages), len(contents))]
    if not targets:
        return contents
    template = _template(prompt_path)
    facts = fact_table(material_summary)
    log.info("按审查意见重写 %d 页: %s", len(targets), targets)
    redone = await llm.run_parallel([
        _write_single_page(pages[i], facts, _prev_page_summary(pages, i), template, llm,
                           review=(notes[i], contents[i]))
        for i in targets
    ])
    out = list(contents)
    for i, page in zip(targets, redone):
        if isinstance(page, dict) and (page.get("title") or page.get("bullets")):
            out[i] = page
    return out


def _template(prompt_path) -> str:
    from llm.adapter import load_prompt
    return load_prompt(prompt_path or PROMPTS / "text" / "write_page.md")


async def _write_single_page(
    page: dict, facts: dict[str, str], prev_summary: str, prompt_template: str, llm,
    *, review: tuple[list[str], dict] | None = None,
) -> dict:
    """撰写单页；review=(意见, 上一版正文) 时按意见改写。"""
    from llm.adapter import as_json

    plan = dict(page.get("text_plan") or {})
    wanted = [k for k in plan.pop("key_facts_to_use", []) or [] if isinstance(k, str)]
    focus = [f"{k}：{facts[k]}" for k in wanted if k in facts]
    focus += [k for k in wanted if k not in facts]
    diagrams = page.get("diagrams") or []
    review_text = ""
    if review:
        prev = {k: review[1].get(k) for k in ("title", "intro", "bullets") if review[1].get(k)}
        review_text = ("═══ 审查意见（按意见修改上一版，未提到的地方保持不变） ═══\n\n"
                       + "\n".join(f"- {n}" for n in review[0])
                       + "\n\n上一版正文：" + as_json(prev) + "\n\n")

    user_msg = (
        prompt_template
        .replace("{page_role}", page.get("role", "正文"))
        .replace("{beat}", page.get("beat", ""))
        .replace("{density}", page.get("density", "medium"))
        .replace("{text_plan}", as_json(plan))
        .replace("{focus_facts}", "\n".join(focus) or "（页纲未指定，从事实库中挑选相关的）")
        .replace("{diagram_info}", as_json(diagrams) if diagrams else "（此页无图形需求）")
        .replace("{available_facts}", "\n".join(f"{k}：{v}" for k, v in facts.items()) or "（无结构化事实数据）")
        .replace("{prev_page_summary}", prev_summary)
        .replace("{review_notes}", review_text)
    )
    result = _parse_json(await llm.ask("你是一名企业PPT文稿撰写专家。请输出 JSON。", user_msg))
    log.info("页 %s %s (%d 字)", page.get("page_index", "?"), "已按意见重写" if review else "撰写完成",
             char_count(result))
    return result


def char_count(page: dict) -> int:
    """页面正文字数：标题 + 导语 + 要点 + 子要点。"""
    if not isinstance(page, dict):
        return 0
    n = len(page.get("title") or "") + len(page.get("intro") or "")
    for b in page.get("bullets") or []:
        if isinstance(b, dict):
            n += len(b.get("text") or "") + sum(len(x) for x in b.get("sub_bullets") or [] if isinstance(x, str))
        elif isinstance(b, str):
            n += len(b)
    return n


def fact_table(summary: dict) -> dict[str, str]:
    """{编号: 原文}，编号来自 S1（F1… / D1…）；旧缓存没有 id 时按顺序补。"""
    table = {}
    for i, f in enumerate(summary.get("key_facts") or [], 1):
        if isinstance(f, dict):
            text = f.get("fact", "") + (f"（来源：{f['source']}）" if f.get("source") else "")
            table[f.get("id") or f"F{i}"] = text
    for i, d in enumerate(summary.get("data_points") or [], 1):
        if isinstance(d, dict):
            before, after = d.get("before", ""), d.get("after", "")
            text = f"{d.get('metric', '')}：{before} → {after}" if before else f"{d.get('metric', '')}：{after}"
            table[d.get("id") or f"D{i}"] = text
    return table


def _prev_page_summary(pages: list[dict], current_idx: int) -> str:
    """生成前一页的概要"""
    if current_idx <= 0:
        return "（这是第一页）"
    prev = pages[current_idx - 1]
    return f"前一页: [{prev.get('beat', '')}] {prev.get('role', '')}。衔接: {prev.get('transition_to_next', '')}"


def _parse_json(raw: str) -> dict:
    from llm.parse import parse_llm_json
    return parse_llm_json(raw, fallback={"title": "", "bullets": []})


def save_pages(pages: list[dict], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    total_chars = sum(char_count(p) for p in pages)
    log.info("页面正文已保存: %s (%d 页, 约 %d 字)", out, len(pages), total_chars)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 4:
        print("用法: python -m text.pages <大纲.json> <摘要.json> <config.yaml> [输出.json]")
        sys.exit(1)

    outline_path = Path(sys.argv[1])
    summary_path = Path(sys.argv[2])
    config_path = Path(sys.argv[3])
    output_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("out/页面正文.json")

    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    from llm.adapter import LLMAdapter
    adapter = LLMAdapter(config_path)

    results = asyncio.run(write_all_pages(outline, summary, adapter))
    save_pages(results, output_path)
    print(f"[OK] {len(results)} 页正文已生成")
