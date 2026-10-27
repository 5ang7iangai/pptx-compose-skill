# 整套新编（compose）

用户给**单位模板 pptx** + 材料（docx/pdf/pptx/md/txt），出一份新汇报稿。

## 阶段

| 步 | 谁 | 动作 |
|---|---|---|
| 1 prepare | 脚本 | `python scripts/stages/prepare.py --template 模板.pptx --materials … -o 任务目录` → `run/manifest.json`、`run/风格卡.json` |
| 2 文案 | **助手** | 先据风格卡做「模板版式清单」；按 `prompts/text/` 写 `run/outline.json` 与 `run/pages.json`。结构图选型遵守 [结构图.md](../references/结构图.md) 四级优先级与防单调。字段见 `schemas/`、[阶段与契约.md](../references/阶段与契约.md) |
| 2b 阻塞门 | 人 | **页纲先在对话确认**再 assemble；用户明确「直接出」时仍须把页纲写在对话里 |
| 3 assemble | 脚本 | `python scripts/stages/assemble.py --run 任务目录/run` → `run/中间稿.pptx` + `run/diagram_jobs.json`（克隆+填字+目录+页签 gap=0） |
| 4 结构图 | **助手** | 按 jobs 写 `run/diagrams/<svg>`；`svg_diagram.py check` 不过则按 `prompts/diagram/fix_svg.md` 改 |
| 5 apply | 脚本 | `python scripts/stages/apply_diagrams.py --run 任务目录/run -o <中文题目>.pptx` → 两套 |
| 6 validate | 脚本 | `python scripts/stages/validate.py <图片版> <可编辑版> --original 模板.pptx --run 任务/run`（含 layout_policy 终检）或 `checks/run_all.py … --run 任务/run` |

## 产出

只交付两套 pptx（[交付约定.md](../references/交付约定.md)）。`run/` 可保留供调试，交付目录勿留过程预览图。

细则见 [整套新编.md](../references/整套新编.md)、[阶段与契约.md](../references/阶段与契约.md)。
