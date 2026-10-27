"""Skill 内各类资源的位置。

pptx-unit 无 config.yaml、无外部模型：本模块只提供路径常量，不查找配置文件。
"""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL = SCRIPTS.parent
PROMPTS = SKILL / "prompts"
CATALOG = SKILL / "catalog"
STYLES_DIR = CATALOG / "styles"
LAYOUTS_DIR = CATALOG / "layouts"
SCHEMAS = SKILL / "schemas"
CHECKS = SKILL / "checks"
REFERENCES = SKILL / "references"
