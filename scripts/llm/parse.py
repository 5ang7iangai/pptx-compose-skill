"""
llm/parse.py — 解析大模型返回的 JSON

所有从 LLM 返回中提取 JSON 的场景统一用这个模块，
确保对各种边界情况的处理一致。
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def parse_llm_json(raw: str, fallback: dict | None = None) -> dict:
    """
    从 LLM 返回的文本中提取 JSON 对象。

    处理：
      - ```json ... ``` 包裹
      - 前后有解释文字
      - BOM / \\r\\n
      - 嵌套花括号的正确配对

    Args:
        raw: LLM 返回的原始文本
        fallback: 解析失败时返回的默认值（会加 _parse_error=True）

    Returns:
        解析出的 dict
    """
    text = raw.strip().replace('\r\n', '\n').lstrip('\ufeff')

    # 去掉 ```json ... ``` 或 ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    # 1) 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 2) 找最外层 { ... } 用深度配对
    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(brace_start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        break

        # 3) JSON 可能被 max_tokens 截断——尝试修补
        if depth > 0:
            log.warning("JSON 似乎被截断 (未闭合深度=%d)，尝试修补", depth)
            truncated = text[brace_start:]
            repaired = _try_repair_truncated_json(truncated)
            if repaired is not None:
                return repaired

    # 3) 解析失败
    log.warning("无法解析 LLM 返回的 JSON: %s...", text[:200])
    if fallback is not None:
        fallback["_parse_error"] = True
        fallback["_raw"] = text[:500]
        return fallback

    return {"_raw": text[:500], "_parse_error": True}


def _try_repair_truncated_json(text: str) -> dict | None:
    """
    尝试修复被 max_tokens 截断的 JSON。
    策略：从末尾往前找最后一个完整的 key-value，截断到那里并闭合。
    """
    # 找到最后一个完整的逗号位置（在字符串外）
    in_string = False
    escape = False
    last_comma = -1
    depth = 0

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            depth += 1
        elif ch in ('}', ']'):
            depth -= 1
        elif ch == ',' and depth <= 2:  # 顶层或第一层嵌套
            last_comma = i

    if last_comma > 0:
        # 截断到最后一个逗号，然后加上足够的闭合括号
        fragment = text[:last_comma]
        # 计算需要的闭合括号
        open_braces = fragment.count('{') - fragment.count('}')
        open_brackets = fragment.count('[') - fragment.count(']')
        suffix = ']' * max(open_brackets, 0) + '}' * max(open_braces, 0)

        try:
            result = json.loads(fragment + suffix)
            if isinstance(result, dict):
                log.info("JSON 截断修复成功 (截断在 %d/%d 字符处)", last_comma, len(text))
                result["_repaired"] = True
                return result
        except json.JSONDecodeError:
            pass

    return None
