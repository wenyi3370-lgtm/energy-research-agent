from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class GatewayError(RuntimeError):
    pass


class ModelRequest(BaseModel):
    purpose: str
    messages: list[dict[str, str]]
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StructuredRequest(ModelRequest, Generic[T]):
    response_model: type[T]


class ModelResponse(BaseModel):
    provider: str
    model: str
    content: str
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    raw_id: str | None = None


@runtime_checkable
class ModelGateway(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...
    def structured(self, request: StructuredRequest[T]) -> T: ...
    def health(self) -> dict[str, Any]: ...

