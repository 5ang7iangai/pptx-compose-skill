# 重画结构图（redraw）

用户指定若干页重画结构图；未点名页保持（或按 `keep_slides` 裁剪）。

## 步骤

1. 写 [spec.md](../references/spec.md)「重做原稿」节（原稿页码、`clear`、`diagram.bbox/brief/layout/style`、`keep_slides`…）。用户未要求换结构时 layout 跟原图；要升级信息表达时按 [结构图.md](../references/结构图.md) 四级优先级选型，并避免与相邻页同 layout。
2. 助手按 brief 写各页 SVG 到 `--svg-dir`（文件名与 `pipeline.make_job` 约定一致：`{原稿页码}-{name}.svg`）。
3. ```text
   python scripts/redraw_pages.py 原稿.pptx -o <中文题目>.pptx --spec 重做.json --svg-dir run/diagrams
   ```
4. validate 两套；未改页应与原件一致（契约）。

见 [重做原稿.md](../references/重做原稿.md)。
