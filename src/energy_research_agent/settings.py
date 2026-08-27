from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repository root; accept it from the working directory
# first (docker-compose style), then from the repo root (source checkout).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES: tuple[str, ...] = (".env", str(_REPO_ROOT / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ERA_",
        extra="ignore",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
    )

    primary_provider: str = "deepseek"
    fallback_provider: str = "openai"
    primary_model: str = "deepseek-chat"
    fallback_model: str = "gpt-5"
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    openai_api_base: str | None = None
    openai_api_key: str | None = None
    # Reasoning models (DeepSeek-V4 family on SiliconFlow) spend quota on
    # chain-of-thought tokens the pipeline never reads; default off keeps
    # extraction/distillation quality-neutral at ~60% lower cost.
    enable_thinking: bool = False
    # Network controls for the provider-neutral HTTP gateway.  The proxy is
    # opt-in so a healthy direct route stays untouched; live acceptance may
    # explicitly point it at a local Clash/Mihomo listener (for example
    # http://127.0.0.1:7897).
    outbound_proxy: str | None = None
    model_timeout_seconds: int = 45
    model_max_attempts: int = 2
    # Vision-capable model used by the image pixel-verification pipeline; the
    # gateway credentials are shared with the research gateway (deepseek/openai).
    # DeepSeek-V4-Flash-Vision-Exp converts each image to at most 384 tokens.
    vision_provider: str = "auto"  # auto | deepseek | openai
    deepseek_vision_model: str = "deepseek-v4-flash-vision-exp"
    openai_vision_model: str = "gpt-4o-mini"
    # Dedicated vision credentials: when the research gateway points at a
    # non-native provider (e.g. SiliconFlow), the native DeepSeek vision
    # model stays reachable through its own key/base (defaults keep the
    # legacy single-key setup working unchanged).
    vision_api_key: str | None = None
    vision_api_base: str = "https://api.deepseek.com"
    database_url: str | None = None
    fail_closed: bool = True
    output_root: Path = Field(default=Path("outputs"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "primary_provider": self.primary_provider,
            "fallback_provider": self.fallback_provider,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "deepseek_api_base": self.deepseek_api_base,
            "openai_api_base": self.openai_api_base,
            "enable_thinking": self.enable_thinking,
            "outbound_proxy": "configured" if self.outbound_proxy else None,
            "model_timeout_seconds": self.model_timeout_seconds,
            "model_max_attempts": self.model_max_attempts,
            "vision_provider": self.vision_provider,
            "vision_api_base": self.vision_api_base,
            "deepseek_vision_model": self.deepseek_vision_model,
            "openai_vision_model": self.openai_vision_model,
            "database_url": "configured" if self.database_url else None,
            "fail_closed": self.fail_closed,
            "output_root": str(self.output_root),
        }

    def config_hash(self) -> str:
        payload = json.dumps(self.safe_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value
