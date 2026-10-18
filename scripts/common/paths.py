"""Skill 内各类资源的位置，以及大模型配置文件的查找顺序。"""

from __future__ import annotations

import os
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL = SCRIPTS.parent
PROMPTS = SKILL / "prompts"
CATALOG = SKILL / "catalog"
STYLES_DIR = CATALOG / "styles"
LAYOUTS_DIR = CATALOG / "layouts"

CONFIG_ENV = "PPTX_COMPOSE_CONFIG"


def config_candidates(explicit: str | Path | None = None) -> list[Path]:
    """命令行 → 环境变量 → 当前目录 → Skill 目录及其上一级 → 用户目录。"""
    out: list[Path] = []
    if explicit:
        out.append(Path(explicit))
    if os.environ.get(CONFIG_ENV):
        out.append(Path(os.environ[CONFIG_ENV]))
    out += [
        Path.cwd() / "config.yaml",
        SKILL / "config.yaml",
        SKILL.parent / "config.yaml",
        Path.home() / ".config" / "pptx-compose" / "config.yaml",
    ]
    return out


def find_config(explicit: str | Path | None = None) -> Path:
    if explicit and not Path(explicit).exists():
        raise FileNotFoundError(f"找不到配置文件 {explicit}")
    for path in config_candidates(explicit):
        if path.exists():
            return path
    tried = "\n  ".join(str(p) for p in config_candidates(explicit))
    raise FileNotFoundError(f"找不到大模型配置 config.yaml（参考 config.example.yaml）。已查找：\n  {tried}")
