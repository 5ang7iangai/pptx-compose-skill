# 路由

先根据用户请求选一条路由，再打开对应 workflow。**每条路由结束都必须：两套 pptx + checks 通过**（或显式列出失败项，禁止静默交付）。

| 路由 | 请求形状 | 权威文档 | 脚本主链 | 输出契约 |
|---|---|---|---|---|
| `compose` | 材料 + 单位模板 → 新汇报稿 | [compose.md](compose.md)、[整套新编.md](../references/整套新编.md) | prepare → 助手文案 → assemble → 助手 SVG → apply_diagrams → validate | `<题目>-图片版.pptx` + `<题目>-可编辑版.pptx`；validate 退出 0 |
| `add_chapter` | 现稿加一章（扉页+正文+目录+图） | [add_chapter.md](add_chapter.md)、[增量改稿.md](../references/增量改稿.md)、[spec.md](../references/spec.md) | 写 spec → 助手写章内正文/SVG → `add_chapter.py`（吃已有 SVG）或 stages → validate | 同上两套 |
| `edit_slides` | 加页/改字/删页/挪形状/页签重排 | [edit_slides.md](edit_slides.md)、[增量改稿.md](../references/增量改稿.md) | `slides.py` 子命令；若需图则助手 SVG → apply → validate | 新路径 pptx；有图则两套 |
| `redraw` | 指定页重画结构图，其余保留 | [redraw.md](redraw.md)、[重做原稿.md](../references/重做原稿.md)、[spec.md](../references/spec.md) | 写 spec → 清图区 → 助手 SVG → `redraw_pages.py` / apply → validate | 同上两套；未点名页契约保留 |

## 硬性

- 底板 = 用户当次上传的 `.pptx`，技能包不内置模板。
- 推理由宿主助手完成；脚本不调外部模型。
- 校验见 [校验与验收.md](../references/校验与验收.md)、[checks/](../checks/)。
