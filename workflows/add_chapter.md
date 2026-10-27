# 加一章（add_chapter）

在现稿上加一章：扉页（可选）+ 正文页 + 各目录加条目 + 结构图两套。

## 步骤

1. 读现稿，写当次 [spec.md](../references/spec.md)（`title`、`anchor`、`divider`、`pages`、`slides`/`diagram`…）。
2. 助手写各页 `replacements` 与结构图 SVG（路径写入 spec 约定或 `--svg-dir`）。结构图选型：优先套用本稿/模板已有版式 → 内置库 → 新设计入库；遵守 [结构图.md](../references/结构图.md) 防单调。
3. 运行：
   ```text
   python scripts/add_chapter.py 现稿.pptx -o <中文题目>.pptx --spec 章节.json [--svg-dir run/diagrams]
   ```
   脚本**不调外部模型**；缺 SVG 则退出并提示助手补写。
4. `python scripts/stages/validate.py … --original 现稿.pptx`

也可用 stages：prepare 片段 → assemble 章 → apply_diagrams → validate（assemble 完整接线后续迭代）。

见 [增量改稿.md](../references/增量改稿.md)。
