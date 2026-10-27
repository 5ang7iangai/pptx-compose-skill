# pptx-unit

本仓库发布技能 **pptx-unit**，是原先开源包 **pptx-compose** 的后继版本。仓库名仍是 `pptx-compose-skill`，公开链接和微信关键词回复不用改。

按用户当次上传的单位 PPT 模板编制或修改演示文稿：整套新编、加一章、加一页或改字、重画结构图。交付**图片版**与**可编辑版**两套 pptx。

## 和 pptx-compose 的差别

- 技能名改为 **pptx-unit**。
- **不需要** `config.yaml`，也不需要外部大模型 API。
- 文案和结构图 SVG 由宿主助手按 `prompts/` 写到任务目录。
- Python 脚本只做模板分析、克隆填字、SVG 检查与渲染、转成形状、打包和校验，不向模型服务发请求。

## 能做什么

- 材料 + 单位模板 → 新稿（`workflows/compose.md`）
- 现稿加一章（`workflows/add_chapter.md`）
- 加一页 / 改字 / 删挪（`workflows/edit_slides.md`）
- 指定页重画结构图（`workflows/redraw.md`）

从 `SKILL.md` 进入；阶段和约定在 `workflows/`、`references/`。

## 安装

把本仓库复制成助手 skills 或 workflows 目录下的文件夹，文件夹名用 `pptx-unit`（与 `SKILL.md` 里的 `name` 一致）：

```bash
git clone https://github.com/5ang7iangai/pptx-compose-skill.git pptx-unit
```

已经克隆到别的目录时：

```bash
cp -r /path/to/pptx-compose-skill /path/to/assistant/skills/pptx-unit
```

复制后，该文件夹根目录应直接有 `SKILL.md`。

## 依赖

Python 3.10+：

```bash
pip install -r requirements.txt
```

主要是 `python-pptx`、`Pillow`、`PyYAML`、`lxml`、`playwright`（SVG 转 PNG）。没有模型 SDK，也不用配置接口地址或密钥。

## 许可

MIT，见 `LICENSE`。

## 公开发布注意

对外发布前按 [references/公开发布脱敏.md](references/公开发布脱敏.md) 做全包自检。示例、图库和说明只用通用占位（如「一、背景与目标」「二、实施方案」，顶栏例「现状梳理 | 路径设计 | 试点验证 | 推广安排」），不写真实单位、课题、成稿题目、联系方式或本机路径。

包内没有 API 密钥、`config.yaml` 或单位模板 pptx。若往 `catalog/` 追加自有模板截图、logo 或落款，公开前请自行脱敏。
