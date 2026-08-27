from __future__ import annotations

import json
from pathlib import Path

from .base import AdapterHealth, SearchAdapter, SearchRequest, SearchResultEnvelope


class RecordedFixtureAdapter:
    """Replay reviewed adapter envelopes for deterministic integration tests."""

    name = "fixture"

    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            available=self.fixture_path.is_file(),
            version="1.0",
            diagnostics=[] if self.fixture_path.is_file() else [f"Fixture not found: {self.fixture_path}"],
        )

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        health = self.health()
        if not health.available:
            return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="error", diagnostics=health.diagnostics)
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        record = payload.get("queries", {}).get(request.query_id)
        if record is None:
            return SearchResultEnvelope(
                adapter=self.name,
                query_id=request.query_id,
                status="partial",
                diagnostics=[f"No recorded result for {request.query_id}"],
            )
        record = dict(record)
        record["adapter"] = self.name
        record["query_id"] = request.query_id
        return SearchResultEnvelope.model_validate(record)


FixtureSearchAdapter = RecordedFixtureAdapter

