"""结构图：大模型出 SVG → 规整 → 检查/修补 → 图片版 PNG + 可编辑版 PPT 形状。

    catalog     风格库、版式库（catalog/ 目录）
    palette     由模板推色板
    sizing      画布尺寸、字号（磅 → 画布单位）
    prompt      拼提示词
    normalize   取出并规整 SVG
    checks/     各项检查
    generate    生成与修补循环
    render      SVG → PNG
    svg_parse   SVG → 图元
    to_ooxml    图元 → PPT 形状
    place       写进幻灯片
    pipeline    任务脚本共用的出图流程

各模块直接按 diagram.<模块> 导入。
"""
