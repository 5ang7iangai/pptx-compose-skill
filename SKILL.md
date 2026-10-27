---
name: pptx-unit
description: >-
  按用户当次上传的单位 PPT 模板编制或修改 pptx（整套新编、加一章、加一页/改字、重画结构图）；克隆样例页、助手写文案与结构图
  SVG、脚本校验并交付图片版与可编辑版两套 pptx。不需要外部大模型 API。在用户提到单位模板、汇报 ppt、加一章、重画结构图或给出 .pptx
  底板时使用。
---
# 单位模板演示文稿编制（pptx-unit）

按用户**当次上传**的单位 PPT 为底板出新稿，不覆盖原件。本技能是 Anthropic 风格、**可完整迁移**的一包：拷到任意能跑 Python、能读写文件的助手即可用。

详细路由、阶段、硬性约定与目录以本技能文件夹内 `SKILL.md`、`workflows/`、`references/` 为准（多文件包，勿只依赖本摘要）。

## 零外部模型

- 不读 `config.yaml`，不配 API Key，脚本不发起模型 HTTP。
- 技能包内无 `generate_svg` 调模型实现、无 `config.yaml`；SVG/文案由宿主助手按 `prompts/` 写到任务 `run/`。
- Python 只做 profile、克隆填字、SVG 检查/渲染/转形状、两套打包、校验。

## 路由

| 用户要 | 路由 | 细则 |
|---|---|---|
| 材料 + 单位模板 → 新稿 | compose | workflows/compose.md |
| 现稿加一章 | add_chapter | workflows/add_chapter.md |
| 加一页 / 改字 / 删挪 / 页签 | edit_slides | workflows/edit_slides.md |
| 指定页重画结构图 | redraw | workflows/redraw.md |

见 workflows/routing.md。模板每次由用户上传；技能包不附带示例 pptx。

## 阶段（整套新编）

prepare → 助手文案 → assemble → 助手 SVG → apply_diagrams → validate → 交付两套（中文题目-图片版/可编辑版）。

页纲须先对话确认再落盘。校验不过不交付。

## 硬性要点

单位底板克隆；页签 gap=0（标题式页签/并列标题名单行平铺，宽度兼容最长名）；导语–图间隙≥0.15″；目录换成新大纲（模式 A 徽标或模式 B「一、」行，toc_entry_count=0 失败不交付）；目录与顶栏高亮成套（深色高亮非浅底）；同一 SVG 出两套 pptx；结构图禁止空壳空柱；正式汇报表述。

**结构图版式**：模板已有 → 套用模板；否则内置 `catalog/`；再否则宿主助手新设计并入库。多页不得连续同 `layout`，整稿 ≥4 图须 ≥3 种版式。`prepare` 写 `模板版式清单.json`；`assemble` / `validate --run` 跑 `layout_policy` 硬检。细则见 [references/结构图.md](references/结构图.md)。

## 从模板补进预置

看过模板里的结构图之后，先和 `catalog/` 对一下。结构和 `catalog/layouts/` 里某一种对得上、画法和 `catalog/styles/` 里某一种对得上，就用现成的，不要再造一套。

对不上（选用优先级走到 ④）才补进预置：补的是**通用**结构和画法，不写客户名、课题名、数字。范例颜色只是样品，成稿仍跟当次模板的标题和顶栏。设计时可借鉴公开信息图/汇报结构密度（如 PPT Master 一类思路），但外壳气质必须跟单位模板。

1. 新结构：写 `catalog/layouts/<id>.md`，第一行「版式：中文名（什么时候用）」。
2. 新画法：建 `catalog/styles/<id>/`，写 `rules.md`、`style.yaml`（`name`、`look`、`use`、`basis`、`checks`）、`example.svg`。
3. 改 `catalog/pairing.yaml`。新版式写 `default` 和 `styles`，`default` 必须在 `styles` 里。
4. 让页纲选得到：更新 `prompts/text/outline_pages.md` 的类型说明；若脚本有 `TYPE_LAYOUT` 一并加上。
5. 手改 `catalog/图库.html` 对照页（技能包暂无图库重建脚本；可跳过，以 `svg_diagram.py list` 与目录扫描为准）。
6. 运行 `python scripts/check_presets.py`。有缺口先补，再出图。

版式不在库里，或库里有版式但配对没写，出图应停下。脚本不发起外部模型 HTTP；新设计由宿主助手完成并落盘。

使用 Python 3.10+，依赖见 requirements.txt。
