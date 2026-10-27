"""结构图：助手写 SVG → 规整 → 检查 → 图片版 PNG + 可编辑版 PPT 形状。

    catalog     风格库、版式库（catalog/ 目录）
    palette     由模板推色板
    sizing      画布尺寸、字号（磅 → 画布单位）
    prompt      拼提示词（给助手参考；不调外部模型）
    normalize   取出并规整 SVG
    checks/     各项检查
    render      SVG → PNG
    svg_parse   SVG → 图元
    to_ooxml    图元 → PPT 形状
    place       写进幻灯片
    pipeline    任务脚本共用的出图流程（读助手已写好的 .svg）

各模块直接按 diagram.<模块> 导入。SVG 由宿主助手按 prompts/diagram/ 写到磁盘。
"""
