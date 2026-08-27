"""Vision-capable verification hook (P0 image system).

``visual_verified`` on ImageEvidence may ONLY be set by a verifier that
actually looks at the image pixels.  This module provides the pluggable
hook plus a gateway-based default:

- ``VisionVerdict`` — the only data shape a vision verifier may return.
- ``default_vision_verifier()`` — prefers DeepSeek-V4-Flash-Vision-Exp via the
  research gateway credentials (``EER_DEEPSEEK_API_KEY``, ≤384 tokens per
  image); an explicit OpenAI-compatible endpoint via
  ``ENTERPRISE_VISION_ENDPOINT``/``ENTERPRISE_VISION_KEY`` or
  ``config/vision_gateway.yaml`` takes precedence; OpenAI fallback uses
  ``EER_OPENAI_API_KEY``.  Returns ``None`` when nothing is configured.
- Context signals (title/alt text) NEVER set ``visual_verified``.

When no vision capability is available, images stay ``visual_verified=False``
and are withheld from publication by the publication gate — never silently
promoted as verified entity photos.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from enterprise_energy_research.domain.models import ImageEvidence


class VisionVerdict(BaseModel):
    verified: bool
    score: float
    description: str | None = None
    entity_matched: bool = False
    rationale: str = ""


# A vision verifier receives the image record and, when available, the local
# file bytes.  It returns a verdict or None ("cannot look at pixels").
VisionVerifier = Callable[[ImageEvidence, bytes | None], VisionVerdict | None]


def _load_gateway_config() -> dict[str, Any] | None:
    # 1) explicit vision endpoint (dedicated OpenAI-compatible gateway)
    endpoint = os.getenv("ENTERPRISE_VISION_ENDPOINT")
    key = os.getenv("ENTERPRISE_VISION_KEY")
    if endpoint:
        return {
            "endpoint": endpoint, "key": key or "",
            "model": os.getenv("ENTERPRISE_VISION_MODEL", "deepseek-v4-flash-vision-exp"),
            "proxy": os.getenv("EER_OUTBOUND_PROXY") or None,
        }
    # 2) config/vision_gateway.yaml
    for parent in Path(__file__).resolve().parents:
        config = parent / "config" / "vision_gateway.yaml"
        if config.is_file():
            try:
                payload = json.loads(config.read_text(encoding="utf-8"))
                if payload.get("endpoint"):
                    return payload
            except json.JSONDecodeError:
                return None
    # 3) reuse the existing research model gateway — DeepSeek first:
    #    deepseek-v4-flash-vision-exp (≤384 tokens per image, priced as V4-Flash)
    try:
        from enterprise_energy_research.settings import Settings
        settings = Settings()  # type: ignore[call-arg]
        provider = (settings.vision_provider or "auto").lower()
        # Dedicated vision credentials take precedence: when the research
        # gateway is repointed at a non-native provider (e.g. SiliconFlow),
        # the native DeepSeek vision model stays reachable through its own
        # key/base (EER_VISION_API_KEY / EER_VISION_API_BASE).
        if provider in {"auto", "deepseek"} and settings.vision_api_key:
            return {
                "endpoint": settings.vision_api_base.rstrip("/"),
                "key": settings.vision_api_key,
                "model": settings.deepseek_vision_model or "deepseek-v4-flash-vision-exp",
                "proxy": settings.outbound_proxy,
            }
        if provider in {"auto", "deepseek"} and settings.deepseek_api_key:
            return {
                "endpoint": settings.deepseek_api_base.rstrip("/"),
                "key": settings.deepseek_api_key,
                "model": settings.deepseek_vision_model or "deepseek-v4-flash-vision-exp",
                "proxy": settings.outbound_proxy,
            }
        if provider in {"auto", "openai"} and settings.openai_api_key:
            return {
                "endpoint": (settings.openai_api_base or "https://api.openai.com/v1").rstrip("/"),
                "key": settings.openai_api_key,
                "model": settings.openai_vision_model or "gpt-4o-mini",
                "proxy": settings.outbound_proxy,
            }
    except Exception:  # noqa: BLE001 - settings unavailable → no vision gateway
        return None
    return None


class GatewayVisionVerifier:
    """OpenAI-compatible vision endpoint; verdict from pixels + prompt."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.endpoint = str(config["endpoint"]).rstrip("/")
        self.key = str(config.get("key", ""))
        self.model = str(config.get("model", "gpt-4o-mini"))
        self.proxy = str(config.get("proxy") or "").strip() or None
        self.timeout_seconds = max(
            10, min(45, int(os.getenv("EER_VISION_TIMEOUT_SECONDS", "30")))
        )

    def __call__(self, image: ImageEvidence, image_bytes: bytes | None) -> VisionVerdict | None:
        if image_bytes is None:
            return None
        import urllib.request

        prompt = (
            "这是企业调研中的一张证据图片。请只根据图片像素内容回答："
            "1) 图中主体属于哪一类（产品/工厂/办公楼/设备/证书/项目现场/其他）；"
            "2) 用一句话客观描述画面内容，不推断未在图中出现的名称、数字或关系；"
            "3) 图片是否能支撑将其绑定到目标实体，请给出 0-1 的置信度。"
            f"目标实体类型：{image.target_entity_type or image.image_type}。"
        )
        mime = image.mime_type or "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            # DeepSeek-V4-Flash-Vision-Exp is a reasoning model: reasoning
            # tokens count against max_tokens, so keep headroom for the answer.
            "max_tokens": 1500,
        }
        request = urllib.request.Request(
            self.endpoint + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
            },
            method="POST",
        )
        try:
            proxy_map = {"http": self.proxy, "https": self.proxy} if self.proxy else {}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy_map))
            with opener.open(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return None
        text = str(content)
        return parse_vision_text(text)


def parse_vision_text(text: str) -> VisionVerdict:
    """Parse a vision model's free-text answer into a verdict.

    Providers vary the answer format, e.g.:

      1) 图中主体属于哪一类：产品 / 工厂 / 办公楼 / 设备 / 证书 / 项目现场 / 其他
      2) 一句话客观描述...
      3) 0 或 1.0（置信度，可能不带"置信度"字样，也可能写作 "3) 1.0"）

    The category token is the FIRST occurrence of any class word; the score
    is the number after "置信度" or the trailing number of a "3)" answer.
    """
    category_match = re.search(r"(产品|工厂|办公楼|设备|证书|项目现场|其他)", text)
    category = category_match.group(1) if category_match else "其他"
    score = 0.0
    # Providers commonly add Markdown emphasis around the score and a
    # parenthetical explanation after it. Accept ``置信度：**1.0**`` and
    # section-3 answers without requiring the number to be the final token.
    score_match = re.search(r"置信度[：:]?\s*\**\s*([0-9]+(?:\.[0-9]+)?)", text)
    if score_match:
        score = float(score_match.group(1))
    else:
        section_three = re.search(
            r"(?:^|\n)\s*3\)\s*[^\n]*?\**\s*([01](?:\.\d+)?)\s*\**",
            text,
        )
        if section_three:
            score = float(section_three.group(1))
    if score > 1.0:
        score = score / 100.0 if score <= 100.0 else score / 10.0
    score = max(0.0, min(1.0, score))
    # The vision model must BOTH classify the pixels as an entity scene
    # AND give a confident binding score.
    scene_classes = {"产品", "工厂", "办公楼", "设备", "证书", "项目现场"}
    verified = category in scene_classes and score >= 0.6
    return VisionVerdict(
        verified=verified,
        score=score,
        description=text[:200],
        entity_matched=verified,
        rationale=text[:300],
    )


def default_vision_verifier() -> VisionVerifier | None:
    config = _load_gateway_config()
    if not config:
        return None
    return GatewayVisionVerifier(config)
