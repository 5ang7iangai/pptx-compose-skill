"""调大模型出 SVG：首轮生成，或在已有图上按审阅意见修补；每轮检查，不过就带着问题再修，留问题最少的一版。"""

from __future__ import annotations

from .checks import check_svg
from .normalize import extract_svg
from .prompt import build_prompt
from .sizing import canvas_for, font_px


async def generate_svg(adapter, diag: dict, palette: dict, retries: int = 2, start: str | None = None) -> str:
    """start 给出时不重画，只在这一版上按检查结果修补。"""
    width, height = canvas_for(diag["bbox"], diag.get("canvas_width", 1200))
    prompt = build_prompt(diag, width, height, palette)
    repair_prompt = build_prompt(diag, width, height, palette, with_example=False)
    system = "你是严谨的 SVG 信息图设计师，只输出符合约束的 SVG 代码块。"

    async def ask(text: str) -> str:
        # SVG 很长，思考会挤占输出额度，这里关掉思考
        return extract_svg(await adapter.ask(system, text, max_tokens=16384, thinking=False))

    svg = start or await ask(prompt)
    best, best_n = svg, None
    # 人工看图后的意见，只在修补已有图时随第一轮问题一起发回
    feedback = [f"（审阅意见）{t}" for t in diag.get("feedback") or []] if start else []
    for attempt in range(retries + 1):
        problems = check_svg(svg, width, height, diag.get("style"), diag.get("brief"), font_px(diag, width))
        if attempt == 0:
            problems = feedback + problems
        # 有审阅意见时原图已被人否掉，不参与择优
        if feedback and attempt == 0:
            pass
        elif best_n is None or len(problems) < best_n:
            best, best_n = svg, len(problems)
        if not problems or attempt == retries:
            break
        fix = (
            repair_prompt
            + "\n\n═══ 上一版 SVG ═══\n```svg\n" + svg + "\n```\n"
            + "\n═══ 上一版的问题：在上一版基础上只改这些地方，其余版式保持，输出完整 SVG ═══\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\n修补时图意里的每一项、每一句都要留下。检查若指出两组分类叠在一起，删掉多出来的那一组，"
            + "只留一组，同一排标题用同一种颜色，并对齐。大数字压住说明时，把说明移开，不要缩短数字。"
            + "检查若建议缩短文字，改成拆行或把同排卡片一起加宽，放不下就压缩留白。"
            + "不许为了通过检查删图意里的条目或缩字号，也不许增写图意里没有的句子。"
            + "文字超出画布时，把那一层整体上移到画布内。"
        )
        svg = await ask(fix)
    return best
