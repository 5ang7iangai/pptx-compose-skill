# spec 字段

`add_chapter.py`（加一章）和 `redraw_pages.py`（重做原稿）各读一份 spec JSON；整套新编由助手写 `run/outline.json` / `run/pages.json`（亦认旧名 `S3_大纲.json` 等），再经 `stages/assemble`，不读本 spec。三者的 `diagram` 字段相同，都交给 `diagram/pipeline.py`（读助手已写好的 SVG）出图。

spec 按当次模板现写，不从技能里取某一份旧稿。`match`、页码、`bbox` 都来自这次的稿。键名以 `_` 开头的（如 `_comment`）是给人看的注释，脚本忽略。

## 顶层（两类 spec 通用）

| 字段 | 说明 |
|---|---|
| `style` | 这一版式想用的风格。不写则用 `catalog/pairing.yaml` 里该版式的预置。必须在该版式支持的风格里；同一版式全稿只能一种，不支持就停下并列出能选的 |
| `fonts` | 图里字号（磅），和原页正文一致。默认 `{"body": 12, "title": 15, "label": 13, "note": 10}`，只写要改的键 |

## 加一章（add_chapter）

顶层：

| 字段 | 说明 |
|---|---|
| `title` | 新章名，如 `四、材料编制`，写进每一份目录 |
| `anchor` | 目录上已有的一条章节文字，用来复制样式，取最短能唯一定位的，如 `三、` |
| `divider` | 章节扉页的样例页码，可不写 |
| `pages` | 正文样例页码数组，按此顺序克隆 |
| `slides` | 每张正文页一项，和 `pages` 一一对应 |

`slides[]`：

| 字段 | 说明 |
|---|---|
| `replacements` | 文字替换，格式同 `slides.py fill` 的 map（见下） |
| `remove_pics` | `true` 时删掉正文区（上沿低于 2 英寸）的旧图 |
| `diagram` | 这页的结构图，见下 |
| `feedback` | 审阅意见数组；助手按 `fix_svg.md` 改磁盘 SVG 时一并参考（本技能 `--fix` 不调模型） |
| `regen` | `true` 时这页的图重画 |

## 重做原稿（redraw_pages）

页码一律写**原稿页码**。

| 字段 | 说明 |
|---|---|
| `keep_slides` | 只保留这些页，不写则全留 |
| `slides[].slide` | 原稿页码 |
| `slides[].clear` | `all`：清掉页上所有带位置的顶层形状（标题占位符除外）；`bbox`（默认）：只清中心落在 `diagram.bbox` 里的 |
| `slides[].keep_match` | 文字含这些片段的顶层形状不清，如导语开头几个字 |
| `slides[].resize` | `[{"match": "导语开头", "w": 12.3}]`，可写 x/y/w/h（英寸），改第一个含该文字的顶层形状 |
| `slides[].diagram` / `feedback` / `regen` | 同加一章 |

找 bbox 和 keep_match：`python scripts/inspect_slide.py 原稿.pptx 4 5` 列出每个顶层形状的位置和文字。

## diagram（结构图）

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 图名，缓存文件名 `<页码>-<name>.svg` |
| `bbox` | 是 | 图在页上的位置（英寸）`{"x","y","w","h"}`，量旧图或图区 |
| `brief` | 是 | 图意：分区、每块的标题和一句说明、先后关系；只写材料里有的。复杂版面直接给坐标骨架，见 [重做原稿.md](重做原稿.md) |
| `page_role` | | 这页讲什么，进提示词 |
| `title` | | 图标题，缺省用 `name` |
| `style` | | 这一页想用的风格。和顶层 `style` 一样，必须是该版式支持的；写在页上时，这一版式的其他页一起用它 |
| `layout` | | 版式 id，清单见 `catalog/图库.html`。不写则没有版式约束，风格用圆角卡片 |
| `fonts` | | 覆盖顶层 `fonts` |
| `feedback` | | 同页一级，两处会合并 |
| `canvas_width` | | 画布宽，默认 1200，高按 bbox 比例 |

## 文字替换 map（slides.py fill / replacements）

```json
{"slides": [{"slide": 6, "replacements": [
  {"match": "原句里能唯一定位的几个字", "text": "新的整段，长度接近原导语"},
  {"match": "卡片原标题", "paragraphs": ["新标题", "新描述"]},
  {"match": "页签", "text": "新页签", "all": true}
]}]}
```

- `match` 是形状全文里的一段，命中多处时改到唯一，或加 `"all": true`。
- `text` 整段替换；项目符号里换行写 `\n`，仍是一条符号。
- `paragraphs` 按段替换，顺序对应形状里的段落。卡片「粗体标题 + 正文」用它，各段保留原格式。
- 写在 `replacements` 里时不写外层 `slides` / `slide`，页由位置决定。

## 改标记

```text
python scripts/edit_spec.py spec.json 5 --regen               # 第 5 页下次重画
python scripts/edit_spec.py spec.json 5 --feedback 意见.txt    # 写入审阅意见（每行一条），再 --fix
python scripts/edit_spec.py spec.json 0 --clear               # 跑完后清掉全部 regen / feedback
```
