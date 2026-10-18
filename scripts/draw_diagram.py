# -*- coding: utf-8 -*-
"""兜底出图：不调大模型，按版式 JSON 直接画七种可编辑结构图（bands/layers/flowchart/…）。

    python scripts/draw_diagram.py 稿.pptx -o 新.pptx --slide 5 --spec 版式.json [--pic 1] [--svg 预览.svg]

只在没有大模型或要求纯规则排版时用；版式字段见 docs/兜底排版.md。实现在 fallback/draw.py。
"""

from fallback.draw import main

if __name__ == "__main__":
    main()
