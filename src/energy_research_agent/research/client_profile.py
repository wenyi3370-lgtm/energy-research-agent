"""Configured client capability boundary for decision intelligence.

Client capabilities are configuration, never inferred from the target company
and never silently hard-coded in a recommendation template.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class ClientCapabilityStatus(str, Enum):
    VERIFIED_CLIENT_CAPABILITY = "VERIFIED_CLIENT_CAPABILITY"
    CONFIGURED_CLIENT_CAPABILITY = "CONFIGURED_CLIENT_CAPABILITY"
    ASSUMED_CLIENT_CAPABILITY = "ASSUMED_CLIENT_CAPABILITY"
    UNKNOWN_CLIENT_CAPABILITY = "UNKNOWN_CLIENT_CAPABILITY"


class ClientCapability(BaseModel):
    capability_id: str
    name: str
    description: str = ""
    status: ClientCapabilityStatus
    applicable_opportunity_types: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_requires_evidence(self) -> "ClientCapability":
        if self.status == ClientCapabilityStatus.VERIFIED_CLIENT_CAPABILITY and not self.evidence_refs:
            raise ValueError("verified client capability requires evidence_refs")
        return self

    @property
    def supports_formal_recommendation(self) -> bool:
        return self.status in {
            ClientCapabilityStatus.VERIFIED_CLIENT_CAPABILITY,
            ClientCapabilityStatus.CONFIGURED_CLIENT_CAPABILITY,
        }


class ClientProfile(BaseModel):
    schema_version: str = "1.0"
    client_id: str
    client_name: str
    role: str
    capabilities: list[ClientCapability] = Field(default_factory=list)
    excluded_capabilities: list[str] = Field(default_factory=list)
    provenance: str = "configuration"

    def capability_matches(self, opportunity_type: str) -> list[ClientCapability]:
        wanted = opportunity_type.casefold()
        return [
            capability for capability in self.capabilities
            if wanted in {item.casefold() for item in capability.applicable_opportunity_types}
        ]

    @property
    def stable_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_client_profile_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "client_profiles" / "sichuan_power_battery_innovation_center.yaml"


def load_client_profile(path: Path | None = None) -> ClientProfile:
    config_path = path or default_client_profile_path()
    payload: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return ClientProfile.model_validate(payload)


def client_profile_from_manifest(manifest: Any) -> ClientProfile:
    snapshot = getattr(manifest, "client_profile", None)
    return ClientProfile.model_validate(snapshot) if snapshot else load_client_profile()
