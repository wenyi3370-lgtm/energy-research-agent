from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EER_", extra="ignore")

    primary_provider: str = "deepseek"
    fallback_provider: str = "openai"
    primary_model: str = "deepseek-chat"
    fallback_model: str = "gpt-5"
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    openai_api_base: str | None = None
    openai_api_key: str | None = None
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

