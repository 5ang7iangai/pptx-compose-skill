"""
text/coherence.py — S5 连贯性审查 + 自动修复

对 S4 全量正文做跨页连贯性审查：
  - 术语一致性
  - 数据一致性
  - 叙事连贯性
  - 重复/遗漏/密度均衡

auto_fixable 的问题自动应用修复；其余问题按页汇总成 revise_notes，交给 pages.revise_pages 重写。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path

from common.paths import PROMPTS

log = logging.getLogger(__name__)


async def check_coherence(
    pages: list[dict],
    narrative_outline: dict,
    llm,  # LLMAdapter
    *,
    facts: dict[str, str] | None = None,
    limits: list[int] | None = None,
    prompt_path: str | Path | None = None,
    auto_fix: bool = True,
) -> tuple[list[dict], dict]:
    """
    对全量正文做连贯性审查。

    Args:
        pages: S4 的输出（每页正文列表）
        narrative_outline: S3 叙事大纲（story_arc 等）
        llm: LLMAdapter 实例
        facts: 事实库 {编号: 原文}，用来核对数据
        limits: 每页字数上限（页纲 text_plan.max_total_chars），审查改写不能超
        prompt_path: 审查提示词路径
        auto_fix: 是否自动应用可修复的问题

    Returns:
        (修复后的 pages, 审查报告 dict)；报告里 revise_notes 是需要重写的页 {页序号: [意见]}
    """
    from llm.adapter import as_json, load_prompt

    user_msg = (
        load_prompt(prompt_path or PROMPTS / "text" / "coherence_check.md")
        .replace("{all_pages_json}", as_json(_slim_pages(pages, limits)))
        .replace("{narrative_outline}", as_json(narrative_outline or {}))
        .replace("{available_facts}", "\n".join(f"{k}：{v}" for k, v in (facts or {}).items()) or "（无）")
    )
    log.info("S5: 开始连贯性审查 (%d 页)...", len(pages))
    report = _parse_json(await llm.ask("你是一名演示文稿质量审查专家。请输出 JSON。", user_msg))

    issues = report.get("issues", [])
    log.info("审查完成: score=%.2f, issues=%d", report.get("overall_score", 1.0), len(issues))

    fixed_pages = copy.deepcopy(pages)
    fix_count = 0
    notes: dict[int, list[str]] = {}
    for issue in issues if auto_fix else []:
        fix = issue.get("fix")
        if issue.get("auto_fixable") and fix and _apply_fix(fixed_pages, fix):
            fix_count += 1
            issue["_applied"] = True
            log.info("自动修复: 页%s [%s] %s -> %s", fix.get("page_index"), fix.get("field"),
                     str(fix.get("old_value", ""))[:30], str(fix.get("new_value", ""))[:30])
            continue
        rev = issue.get("revise") or {}
        idx = rev.get("page_index")
        if isinstance(idx, int) and 0 <= idx < len(pages):
            notes.setdefault(idx, []).append(rev.get("instruction") or issue.get("suggestion") or issue.get("description", ""))

    if fix_count:
        log.info("自动修复了 %d 个问题", fix_count)
    report["auto_fix_applied"] = fix_count
    report["revise_notes"] = {str(k): v for k, v in sorted(notes.items())}
    return fixed_pages, report


def _slim_pages(pages: list[dict], limits: list[int] | None = None) -> list[dict]:
    """保留审查需要的字段（去掉 diagram_data、notes 等）；字数由代码算，附上该页上限。"""
    from .pages import char_count

    slim = []
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            slim.append({"page_index": i, "_error": "not a dict"})
            continue
        item = {"page_index": i, "title": p.get("title", ""), "intro": p.get("intro", ""),
                "bullets": p.get("bullets", []), "chars": char_count(p)}
        if limits and i < len(limits) and limits[i]:
            item["max_chars"] = limits[i]
        slim.append(item)
    return slim


def _apply_fix(pages: list[dict], fix: dict) -> bool:
    """
    根据 fix 描述应用单个修复。
    fix 格式: {page_index, field, old_value, new_value}
    field 支持: "title", "intro", "bullets[N].text", "bullets[N].sub_bullets[M]"
    """
    page_idx = fix.get("page_index")
    field = fix.get("field", "")
    old_value = fix.get("old_value", "")
    new_value = fix.get("new_value", "")

    if page_idx is None or page_idx >= len(pages):
        return False

    page = pages[page_idx]

    # 直接字段
    if field in ("title", "intro", "notes"):
        current = page.get(field, "")
        if old_value and old_value in current:
            page[field] = current.replace(old_value, new_value)
            return True
        return False

    # bullets[N].text / bullets[N].sub_bullets[M]
    if field.startswith("bullets["):
        try:
            parts = field.split(".")
            bracket = parts[0]  # "bullets[N]"
            idx = int(bracket.split("[")[1].rstrip("]"))
            bullets = page.get("bullets", [])
            if idx >= len(bullets):
                return False

            if len(parts) == 1 or parts[1] == "text":
                current = bullets[idx].get("text", "")
                if old_value and old_value in current:
                    bullets[idx]["text"] = current.replace(old_value, new_value)
                    return True
            elif parts[1].startswith("sub_bullets["):
                sub_idx = int(parts[1].split("[")[1].rstrip("]"))
                subs = bullets[idx].get("sub_bullets", [])
                if sub_idx < len(subs) and old_value in subs[sub_idx]:
                    subs[sub_idx] = subs[sub_idx].replace(old_value, new_value)
                    return True
        except (ValueError, IndexError, KeyError):
            pass

    # 通用回退：在整个页面 JSON 做文本替换
    if old_value and new_value:
        page_str = json.dumps(page, ensure_ascii=False)
        if old_value in page_str:
            page_str = page_str.replace(old_value, new_value)
            try:
                pages[page_idx] = json.loads(page_str)
                return True
            except json.JSONDecodeError:
                pass

    return False


def _parse_json(raw: str) -> dict:
    from llm.parse import parse_llm_json
    return parse_llm_json(raw, fallback={"issues": [], "overall_score": 0.0, "summary": "解析失败"})


def save_report(report: dict, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("审查报告已保存: %s", out)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 4:
        print("用法: python -m text.coherence <页面正文.json> <大纲.json> <config.yaml> [输出_正文.json] [输出_报告.json]")
        sys.exit(1)

    pages_path = Path(sys.argv[1])
    outline_path = Path(sys.argv[2])
    config_path = Path(sys.argv[3])
    out_pages = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("out/页面正文_审后.json")
    out_report = Path(sys.argv[5]) if len(sys.argv) > 5 else Path("out/审查报告.json")

    pages = json.loads(pages_path.read_text(encoding="utf-8"))
    outline = json.loads(outline_path.read_text(encoding="utf-8"))

    from llm.adapter import LLMAdapter
    adapter = LLMAdapter(config_path)

    fixed_pages, report = asyncio.run(check_coherence(
        pages, outline.get("narrative", outline), adapter,
        limits=[(p.get("text_plan") or {}).get("max_total_chars", 0) for p in outline.get("pages", [])]))

    from .pages import save_pages
    save_pages(fixed_pages, out_pages)
    save_report(report, out_report)

    score = report.get("overall_score", 0)
    fixes = report.get("auto_fix_applied", 0)
    issues = len(report.get("issues", []))
    print(f"[OK] score={score:.2f}, issues={issues}, auto_fixed={fixes}")
