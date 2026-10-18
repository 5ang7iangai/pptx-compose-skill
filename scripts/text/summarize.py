"""
text/summarize.py — S1 材料深度摘要

将 text.material 的输出进一步压缩为结构化摘要，
提取关键事实、论据、数据、缺失信息等，供后续阶段使用。
长材料（超过 context 的 60%）自动分段摘要再合并。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from common.paths import PROMPTS
from typing import Any

log = logging.getLogger(__name__)

# 按 token ≈ 字符数 × 0.5（中文偏保守估计）的粗略比例
CHARS_PER_TOKEN_ESTIMATE = 2
DEFAULT_CONTEXT_LIMIT_TOKENS = 120000  # 假设模型 context 128k，取 60% ≈ 76k tokens
TABLE_ROWS = 30  # 表格行里常是关键数据，只截前几行会丢数


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN_ESTIMATE


def _material_to_text(material: dict) -> str:
    """把 text.material 的 JSON 输出拼成一段可读文本"""
    parts: list[str] = []
    if material.get("title"):
        parts.append(f"标题：{material['title']}\n")
    for sec in material.get("sections", []):
        heading = sec.get("heading", "")
        body = sec.get("body", "")
        if heading:
            parts.append(f"{'#' * max(sec.get('level', 1), 1)} {heading}")
        if body:
            parts.append(body)
        parts.append("")  # blank line between sections

    for tbl in material.get("tables", []):
        parts.append(f"[表格: {tbl.get('caption', '')}]")
        if tbl.get("headers"):
            parts.append(" | ".join(tbl["headers"]))
        for row in tbl.get("rows", [])[:TABLE_ROWS]:
            parts.append(" | ".join(row))
        if len(tbl.get("rows", [])) > TABLE_ROWS:
            parts.append(f"... 共 {len(tbl['rows'])} 行")
        parts.append("")

    if material.get("images"):  # 只有文件名、页码，没有内容，逐条列出白占篇幅
        parts.append(f"[图片] 材料中有 {len(material['images'])} 张图片，内容未识别")

    return "\n".join(parts)


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """按段落边界分割文本，每块不超过 max_chars"""
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for \n\n
        if current_len + para_len > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


async def summarize(
    material: dict,
    llm,  # LLMAdapter instance
    *,
    requirement: str = "",
    prompt_path: str | Path | None = None,
    context_limit_tokens: int = DEFAULT_CONTEXT_LIMIT_TOKENS,
) -> dict:
    """
    生成材料的结构化摘要。

    Args:
        material: text.material.read_material() 的输出
        llm: LLMAdapter 实例
        requirement: 用户的制作要求；摘要要覆盖要求里点名的各部分
        prompt_path: 提示词模板路径，默认 prompts/summarize_material.md
        context_limit_tokens: 模型 context window 的安全上限（token 数）

    Returns:
        结构化摘要 dict
    """
    from llm.adapter import load_prompt

    template = load_prompt(prompt_path or PROMPTS / "text" / "summarize_material.md").replace(
        "{requirement}", requirement or "（未给出，按材料本身组织）")
    full_text = _material_to_text(material)
    log.info("材料全文 %d 字 (≈%d tokens)", len(full_text), _estimate_tokens(full_text))

    # 判断是否需要分段
    safe_char_limit = context_limit_tokens * CHARS_PER_TOKEN_ESTIMATE
    # 提示词本身大概占 1000 字，留余量
    material_char_limit = safe_char_limit - 2000

    if len(full_text) <= material_char_limit:
        # 短材料：一次摘要
        log.info("材料较短，单次摘要")
        summary = await _summarize_single(full_text, llm, template)
    else:
        # 长材料：分段摘要 → 合并
        chunks = _split_into_chunks(full_text, material_char_limit)
        log.info("材料较长，分 %d 段摘要后合并", len(chunks))
        summary = await _summarize_chunked(chunks, llm, template)
    return number_facts(summary)


def number_facts(summary: dict) -> dict:
    """事实编 F1…、数据编 D1…；页纲只写编号，撰写时由程序换回原文，避免模型来回抄写长句。"""
    for prefix, key in (("F", "key_facts"), ("D", "data_points")):
        for i, item in enumerate(summary.get(key) or [], 1):
            if isinstance(item, dict):
                item["id"] = f"{prefix}{i}"
    return summary


async def _summarize_single(text: str, llm, prompt_template: str) -> dict:
    user_msg = prompt_template.replace("{material_text}", text)
    system_msg = "你是一个专业的企业汇报材料分析师。请按照要求输出 JSON。"

    raw = await llm.ask(system_msg, user_msg)
    return _parse_summary_json(raw)


async def _summarize_chunked(chunks: list[str], llm, prompt_template: str) -> dict:
    """分段摘要后合并"""
    system_msg = "你是一个专业的企业汇报材料分析师。请按照要求输出 JSON。"

    # 逐段摘要（用 llm.run_parallel 自动处理并发/限流）
    async def summarize_chunk(chunk_text: str):
        user_msg = prompt_template.replace("{material_text}", chunk_text)
        raw = await llm.ask(system_msg, user_msg)
        return _parse_summary_json(raw)

    coros = [summarize_chunk(c) for c in chunks]
    partial_summaries = await llm.run_parallel(coros)

    # 合并多段摘要
    return _merge_summaries(partial_summaries)


def _merge_summaries(summaries: list[dict]) -> dict:
    """合并多段摘要为一份"""
    merged: dict[str, Any] = {
        "core_proposition": "",
        "key_facts": [],
        "arguments": [],
        "entities": [],
        "data_points": [],
        "missing_info": [],
        "audience_hint": "",
        "suggested_narrative": "",
    }

    propositions = []
    audiences = []
    narratives = []

    for s in summaries:
        if not isinstance(s, dict):
            continue
        if s.get("core_proposition"):
            propositions.append(s["core_proposition"])
        merged["key_facts"].extend(s.get("key_facts", []))
        merged["arguments"].extend(s.get("arguments", []))
        merged["entities"].extend(s.get("entities", []))
        merged["data_points"].extend(s.get("data_points", []))
        merged["missing_info"].extend(s.get("missing_info", []))
        if s.get("audience_hint"):
            audiences.append(s["audience_hint"])
        if s.get("suggested_narrative"):
            narratives.append(s["suggested_narrative"])

    # 去重
    merged["entities"] = list(dict.fromkeys(merged["entities"]))
    merged["missing_info"] = list(dict.fromkeys(merged["missing_info"]))

    # key_facts 按 fact 去重
    seen_facts: set[str] = set()
    unique_facts = []
    for f in merged["key_facts"]:
        fact_text = f.get("fact", "")
        if fact_text not in seen_facts:
            seen_facts.add(fact_text)
            unique_facts.append(f)
    merged["key_facts"] = unique_facts

    # 取第一个非空值
    merged["core_proposition"] = " ".join(propositions) if propositions else ""
    merged["audience_hint"] = audiences[0] if audiences else ""
    merged["suggested_narrative"] = narratives[0] if narratives else ""

    return merged


def _parse_summary_json(raw: str) -> dict:
    """从 LLM 返回中提取 JSON"""
    from llm.parse import parse_llm_json
    return parse_llm_json(raw, fallback={
        "core_proposition": "",
        "key_facts": [],
        "arguments": [],
        "entities": [],
        "data_points": [],
        "missing_info": [],
        "audience_hint": "",
        "suggested_narrative": "",
    })


def save_summary(summary: dict, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("摘要已保存: %s (key_facts=%d, arguments=%d, data_points=%d)",
             out, len(summary.get("key_facts", [])),
             len(summary.get("arguments", [])),
             len(summary.get("data_points", [])))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 3:
        print("用法: python -m text.summarize <材料.json> <config.yaml> [输出.json]")
        sys.exit(1)

    material_path = Path(sys.argv[1])
    config_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else material_path.with_suffix(".summary.json")

    material = json.loads(material_path.read_text(encoding="utf-8"))

    from llm.adapter import LLMAdapter
    adapter = LLMAdapter(config_path)

    summary = asyncio.run(summarize(material, adapter))
    save_summary(summary, output_path)
    print(f"[OK] facts={len(summary.get('key_facts', []))}, "
          f"args={len(summary.get('arguments', []))}, "
          f"entities={len(summary.get('entities', []))}")
