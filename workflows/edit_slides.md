# 加页 / 改字 / 页操作（edit_slides）

小改动走 `scripts/slides.py` 子命令（加页、改字、删/复制/挪形状、重排页、页签 `relayout_section_tabs` 等）。**写出新文件，不覆盖原件。**

## 步骤

1. 确认必填（哪一页、改什么）；可选项按 SKILL「新建和改稿」。
2. `python scripts/slides.py <子命令> … -o 新稿.pptx`
3. 若本页需要结构图：助手写 SVG → `stages/apply_diagrams.py`（或对该页 brief 单独 apply）→ 两套交付。
4. 有顶栏页签改字后必须重排且 gap=0；跑 validate。

见 [增量改稿.md](../references/增量改稿.md)。
