"""
llm.adapter — 大模型统一调用接口

配置文件按 common.paths.find_config 的顺序查找，可不传路径。

支持 provider：
  - openai  （覆盖 OpenAI 兼容接口：云端 / Azure / 本地 Ollama / vLLM 等）
  - anthropic（Anthropic Messages API）

功能：
  - ask()           纯文本对话
  - ask_vision()    带图片对话（S2 模板视觉理解）
  - run_parallel()  并行调用，限流自动退回串行
  - load_prompt()   读 prompts/ 下的提示词并替换 {占位符}
  - as_json()       注入提示词的数据块用紧凑 JSON
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from common.paths import PROMPTS, find_config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _resolve_env(val: str | None) -> str | None:
    """把 ${ENV_VAR} 替换成环境变量的值"""
    if val is None:
        return None
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        env_name = val[2:-1]
        resolved = os.environ.get(env_name)
        if resolved is None:
            raise ValueError(f"环境变量 {env_name} 未设置（config.yaml 中引用了 {val}）")
        return resolved
    return val


class LLMConfig:
    """从 config.yaml 解析出来的配置"""

    def __init__(self, path: str | Path | None = None):
        path = find_config(path)
        self.path = path
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        # 兼容两种格式：嵌套在 llm: 下 或 扁平放在顶层
        llm = raw.get("llm") or raw

        self.provider: str = llm.get("provider", "openai")
        self.model: str = llm.get("model", "gpt-4o")
        self.api_key: str = _resolve_env(llm.get("api_key"))
        self.base_url: str = llm.get("base_url", "https://api.example.com/v1")
        self.max_tokens: int = llm.get("max_tokens", 16000)
        self.temperature: float = llm.get("temperature", 0.3)
        # None 表示沿用模型默认；false 表示关闭推理模型的思考
        self.thinking: bool | None = llm.get("thinking")

        # 视觉模型（可选）
        self.vision_model: str | None = llm.get("vision_model")
        self.vision_base_url: str = llm.get("vision_base_url") or self.base_url
        self.vision_api_key: str = _resolve_env(llm.get("vision_api_key")) or self.api_key

        # 并发
        self.max_concurrent: int = llm.get("max_concurrent", 5)
        self.retry_delay_sec: float = llm.get("retry_delay_sec", 1.0)


# ---------------------------------------------------------------------------
# Rate limit exception
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """API 返回 429 或类似限流响应"""


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------

async def _openai_chat(
    cfg: LLMConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
    thinking: bool | None = None,
) -> str:
    """调用 OpenAI 兼容接口，返回 assistant content 文本。

    thinking=False 时关闭推理模型的思考，避免思考耗尽 max_tokens 导致正文为空。
    """
    url = (base_url or cfg.base_url).rstrip("/") + "/chat/completions"
    key = api_key or cfg.api_key
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload: dict[str, Any] = {
        "model": model or cfg.model,
        "messages": messages,
        "max_tokens": max_tokens or cfg.max_tokens,
        "temperature": cfg.temperature,
    }
    use_thinking = cfg.thinking if thinking is None else thinking
    if use_thinking is False:
        payload["thinking"] = {"type": "disabled"}

    async with httpx.AsyncClient(timeout=300) as client:
        for attempt in range(3):
            try:
                resp = await client.post(url, headers=headers, json=payload)
                break
            except (httpx.RemoteProtocolError, httpx.ConnectError) as e:
                if attempt < 2:
                    log.warning("API 连接异常 (尝试 %d/3): %s，%.1f 秒后重试",
                                attempt + 1, e, (attempt + 1) * 2)
                    await asyncio.sleep((attempt + 1) * 2)
                else:
                    raise
        if resp.status_code == 429:
            raise RateLimitError(f"429 Too Many Requests: {resp.text[:200]}")
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"].get("content") or ""
        if not content.strip() and choice.get("finish_reason") == "length":
            raise RuntimeError(
                f"模型输出被 max_tokens={payload['max_tokens']} 截断且正文为空"
                "（多半是思考占满了额度），请调大 max_tokens 或关闭 thinking"
            )
        return content


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

async def _anthropic_chat(
    cfg: LLMConfig,
    system: str,
    user_content: list[dict] | str,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """调用 Anthropic Messages API"""
    # base_url 请在 config 里填 Anthropic 兼容根地址（形如 https://api.example.com/v1）；
    # 若已是完整 /messages 地址则直接使用。
    base = (cfg.base_url or "https://api.example.com/v1").rstrip("/")
    url = base if base.endswith("/messages") else f"{base}/messages"
    key = api_key or cfg.api_key
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    if isinstance(user_content, str):
        content = [{"type": "text", "text": user_content}]
    else:
        content = user_content

    payload: dict[str, Any] = {
        "model": model or cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 429:
            raise RateLimitError(f"429 Too Many Requests: {resp.text[:200]}")
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


# ---------------------------------------------------------------------------
# Image encoding helper
# ---------------------------------------------------------------------------

def _encode_image_b64(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode("ascii")


def _image_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(suffix.lstrip("."), "image/png")


# ---------------------------------------------------------------------------
# LLMAdapter — public API
# ---------------------------------------------------------------------------

class LLMAdapter:
    """统一的大模型调用接口"""

    def __init__(self, config_path: str | Path | None = None):
        self.cfg = LLMConfig(config_path)
        log.info("LLM 适配器初始化: provider=%s model=%s", self.cfg.provider, self.cfg.model)

    # ── 纯文本对话 ──

    async def ask(
        self, system: str, user: str, *, max_tokens: int | None = None, thinking: bool | None = None
    ) -> str:
        """纯文本对话，返回 assistant 内容"""
        if self.cfg.provider == "anthropic":
            return await _anthropic_chat(self.cfg, system, user)
        else:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            return await _openai_chat(self.cfg, messages, max_tokens=max_tokens, thinking=thinking)

    def ask_sync(self, system: str, user: str) -> str:
        """同步版本（方便脚本直接调用）"""
        return asyncio.run(self.ask(system, user))

    # ── 带图片对话（视觉模型） ──

    async def ask_vision(self, system: str, user: str, images: list[Path]) -> str:
        """带图片的对话，用于 S2 视觉理解"""
        if not self.cfg.vision_model:
            raise RuntimeError("config.yaml 中未配置 vision_model，无法调用视觉模型")

        if self.cfg.provider == "anthropic":
            content: list[dict] = [{"type": "text", "text": user}]
            for img_path in images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _image_media_type(img_path),
                        "data": _encode_image_b64(img_path),
                    },
                })
            return await _anthropic_chat(
                self.cfg, system, content,
                model=self.cfg.vision_model,
                api_key=self.cfg.vision_api_key,
            )
        else:
            # OpenAI 兼容格式的 vision
            user_content: list[dict] = [{"type": "text", "text": user}]
            for img_path in images:
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{_image_media_type(img_path)};base64,{_encode_image_b64(img_path)}",
                    },
                })
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ]
            return await _openai_chat(
                self.cfg, messages,
                model=self.cfg.vision_model,
                base_url=self.cfg.vision_base_url,
                api_key=self.cfg.vision_api_key,
            )

    # ── 并行调用 + 限流降级 ──

    async def run_parallel(self, coros: list) -> list:
        """
        并行执行多个协程。
        遇到 RateLimitError 时自动取消剩余任务，退回串行。
        """
        if self.cfg.max_concurrent <= 1:
            return await self._run_serial(coros)

        sem = asyncio.Semaphore(self.cfg.max_concurrent)

        async def guarded(coro):
            async with sem:
                return await coro

        tasks = [asyncio.create_task(guarded(c)) for c in coros]

        try:
            results = await asyncio.gather(*tasks)
            return list(results)
        except (RateLimitError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            log.warning("API 并发异常 (%s)，取消剩余任务，自动退回串行模式", type(e).__name__)
            for t in tasks:
                if not t.done():
                    t.cancel()
            # 收集已完成的结果
            completed = {}
            for i, t in enumerate(tasks):
                if t.done() and not t.cancelled() and t.exception() is None:
                    completed[i] = t.result()
            # 串行补跑未完成的
            results_list: list = [None] * len(coros)
            for i, val in completed.items():
                results_list[i] = val
            for i in range(len(coros)):
                if results_list[i] is None:
                    await asyncio.sleep(self.cfg.retry_delay_sec)
                    results_list[i] = await coros[i]
            return results_list

    async def _run_serial(self, coros: list) -> list:
        results = []
        for c in coros:
            results.append(await c)
            if self.cfg.retry_delay_sec > 0:
                await asyncio.sleep(self.cfg.retry_delay_sec)
        return results


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def as_json(obj) -> str:
    """注入提示词的数据块用紧凑 JSON：不缩进、不加空格，模型读起来一样，省下排版占的 token。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def load_prompt(prompt_path: str | Path, **kwargs: str) -> str:
    """加载提示词模板，替换 {variable} 占位符。相对路径按 prompts/ 目录解析，如 "text/write_page.md"。"""
    path = Path(prompt_path)
    if not path.is_absolute() and not path.exists():
        path = PROMPTS / path
    if not path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {path}")
    template = path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", str(value))
    return template


# ---------------------------------------------------------------------------
# CLI quick-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    adapter = LLMAdapter(config_path)
    question = sys.argv[2] if len(sys.argv) > 2 else "请用一句话介绍你自己。"

    print(f"Provider: {adapter.cfg.provider}")
    print(f"Model:    {adapter.cfg.model}")
    print(f"Question: {question}")
    print("---")
    answer = adapter.ask_sync("你是一个助手。", question)
    print(answer)
