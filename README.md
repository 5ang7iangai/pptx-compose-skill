# pptx-compose

基于模板学习的 PPT 制作 Skill：按你提供的 `.pptx` 模板编制或修改演示文稿，抽取版式与风格，由大模型生成 SVG 结构图，并交付**图片版**与**可编辑版**两套 pptx。

## 能做什么

- 整套新编（材料 + 模板 → 新稿）
- 在现稿上加一章 / 加一页 / 改字改版
- 重做原稿中的结构图
- 内置版式与风格图库（`catalog/`），可扩展

详见 `SKILL.md` 与 `docs/`。

## 安装

将本目录复制到 Agent 的 workflows 目录，例如：

```bash
cp -r pptx-compose /path/to/agent-data/workflows/pptx-compose
```

目录名保持 `pptx-compose`，以便 Skill 被正确发现。

## 配置大模型

1. 复制示例配置：

```bash
cp config.example.yaml config.yaml
# 或放到 ~/.config/pptx-compose/config.yaml
```

2. 在 `config.yaml` 中填写你自己的：

- `api_key`（推荐用环境变量，如 `${LLM_API_KEY}`）
- `base_url`（你的 OpenAI 兼容或 Anthropic 兼容接口地址）
- `model` / 可选的 `vision_model`

**本仓库不包含真实密钥或私有接口地址。** `config.example.yaml` 里的 `https://api.example.com/v1` 仅为占位符，请自行替换。切勿把含真实密钥的 `config.yaml` 提交到公开仓库或网盘。

配置查找顺序见 `SKILL.md` 开头（`--config` → 环境变量 `PPTX_COMPOSE_CONFIG` → 当前目录 → 技能目录 → `~/.config/pptx-compose/`）。

## 依赖（概要）

Python 3.10+；脚本侧常用 `httpx`、`lxml`、`Pillow` 等。按你使用的运行环境安装即可。出图 PNG 可能需要本机 SVG 光栅化相关工具（见 `docs/结构图.md`）。

## 许可

本项目采用 MIT 许可证，详见 `LICENSE`。

## 隐私说明

开源包已去除示例中的内部课题名、行业标识性示例文案，以及真实 API 配置。若你后续向 catalog 或文档追加自有模板截图、logo、落款，请在公开前自行脱敏。
