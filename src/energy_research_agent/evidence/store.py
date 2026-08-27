from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TypeVar

from pydantic import BaseModel

from energy_research_agent.domain.models import (
    Claim,
    ConflictGroup,
    DataGap,
    Entity,
    EnergyProfile,
    EnterpriseEdge,
    Factory,
    ImageEvidence,
    Product,
    Retrieval,
    RunManifest,
    Solution,
    Source,
)

T = TypeVar("T", bound=BaseModel)


class EvidenceStoreError(RuntimeError):
    pass


MODEL_BY_KIND: dict[str, type[BaseModel]] = {
    "entity": Entity,
    "factory": Factory,
    "edge": EnterpriseEdge,
    "source": Source,
    "retrieval": Retrieval,
    "claim": Claim,
    "conflict": ConflictGroup,
    "gap": DataGap,
    "image": ImageEvidence,
    "product": Product,
    "energy_profile": EnergyProfile,
    "solution": Solution,
}

ID_FIELD_BY_KIND = {
    "entity": "entity_id",
    "factory": "factory_id",
    "edge": "edge_id",
    "source": "source_id",
    "retrieval": "retrieval_id",
    "claim": "claim_id",
    "conflict": "conflict_group_id",
    "gap": "gap_id",
    "image": "image_id",
    "product": "product_id",
    "energy_profile": "energy_profile_id",
    "solution": "solution_id",
}


def canonical_json(model: BaseModel | dict[str, Any]) -> str:
    value = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class EvidenceStore:
    """Append-only SQLite evidence store for local and test runs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_records (
                    run_id TEXT NOT NULL,
                    evidence_version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (run_id, kind, record_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_run_version
                    ON evidence_records(run_id, evidence_version, kind);
                CREATE TABLE IF NOT EXISTS validation_reports (
                    validation_report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS freezes (
                    freeze_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    evidence_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    root_hash TEXT NOT NULL,
                    UNIQUE(run_id, evidence_version),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS artifact_manifests (
                    artifact_manifest_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    freeze_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (freeze_id) REFERENCES freezes(freeze_id)
                );
                """
            )

    def create_run(self, run: RunManifest) -> None:
        with self.transaction() as connection:
            try:
                connection.execute(
                    "INSERT INTO runs(run_id, payload, created_at) VALUES (?, ?, ?)",
                    (run.run_id, canonical_json(run), run.created_at.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise EvidenceStoreError(f"Run already exists: {run.run_id}") from exc

    def get_run(self, run_id: str) -> RunManifest:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise EvidenceStoreError(f"Unknown run: {run_id}")
        return RunManifest.model_validate_json(row["payload"])

    def replace_run_manifest(self, run: RunManifest) -> None:
        """Update control metadata only; evidence remains append-only."""
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET payload = ? WHERE run_id = ?",
                (canonical_json(run), run.run_id),
            )
            if cursor.rowcount != 1:
                raise EvidenceStoreError(f"Unknown run: {run.run_id}")

    def add(self, run_id: str, evidence_version: int, kind: str, record: BaseModel) -> None:
        if kind not in MODEL_BY_KIND:
            raise EvidenceStoreError(f"Unsupported evidence kind: {kind}")
        model_type = MODEL_BY_KIND[kind]
        validated = model_type.model_validate(record.model_dump())
        record_id = str(getattr(validated, ID_FIELD_BY_KIND[kind]))
        with self.transaction() as connection:
            frozen = connection.execute(
                "SELECT 1 FROM freezes WHERE run_id = ? AND evidence_version >= ? LIMIT 1",
                (run_id, evidence_version),
            ).fetchone()
            if frozen:
                raise EvidenceStoreError(
                    f"Evidence version {evidence_version} for {run_id} is frozen; create a new version"
                )
            try:
                connection.execute(
                    "INSERT INTO evidence_records(run_id, evidence_version, kind, record_id, payload) VALUES (?, ?, ?, ?, ?)",
                    (run_id, evidence_version, kind, record_id, canonical_json(validated)),
                )
            except sqlite3.IntegrityError as exc:
                raise EvidenceStoreError(f"Duplicate or invalid record: {kind}/{record_id}") from exc

    def list(self, run_id: str, kind: str, *, up_to_version: int | None = None) -> list[BaseModel]:
        if kind not in MODEL_BY_KIND:
            raise EvidenceStoreError(f"Unsupported evidence kind: {kind}")
        query = "SELECT payload FROM evidence_records WHERE run_id = ? AND kind = ?"
        params: list[Any] = [run_id, kind]
        if up_to_version is not None:
            query += " AND evidence_version <= ?"
            params.append(up_to_version)
        query += " ORDER BY record_id"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        model_type = MODEL_BY_KIND[kind]
        return [model_type.model_validate_json(row["payload"]) for row in rows]

    def get(self, run_id: str, kind: str, record_id: str) -> BaseModel:
        if kind not in MODEL_BY_KIND:
            raise EvidenceStoreError(f"Unsupported evidence kind: {kind}")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM evidence_records WHERE run_id = ? AND kind = ? AND record_id = ?",
                (run_id, kind, record_id),
            ).fetchone()
        if not row:
            raise EvidenceStoreError(f"Unknown record: {kind}/{record_id}")
        return MODEL_BY_KIND[kind].model_validate_json(row["payload"])

    def has_record(self, run_id: str, kind: str, record_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM evidence_records WHERE run_id = ? AND kind = ? AND record_id = ?",
                (run_id, kind, record_id),
            ).fetchone() is not None

    def assert_referential_integrity(self, run_id: str, up_to_version: int) -> None:
        entities = {item.entity_id for item in self.list(run_id, "entity", up_to_version=up_to_version)}
        sources = {item.source_id for item in self.list(run_id, "source", up_to_version=up_to_version)}
        claims = self.list(run_id, "claim", up_to_version=up_to_version)
        retrievals = self.list(run_id, "retrieval", up_to_version=up_to_version)
        conflicts = self.list(run_id, "conflict", up_to_version=up_to_version)
        images = self.list(run_id, "image", up_to_version=up_to_version)
        products = self.list(run_id, "product", up_to_version=up_to_version)
        factories = self.list(run_id, "factory", up_to_version=up_to_version)
        edges = self.list(run_id, "edge", up_to_version=up_to_version)
        energy_profiles = self.list(run_id, "energy_profile", up_to_version=up_to_version)
        failures: list[str] = []
        for claim in claims:
            if claim.entity_id not in entities:
                failures.append(f"{claim.claim_id}: missing entity {claim.entity_id}")
            if claim.source_id not in sources:
                failures.append(f"{claim.claim_id}: missing source {claim.source_id}")
        claim_ids = {item.claim_id for item in claims}
        factory_ids = {item.factory_id for item in factories}
        product_ids = {item.product_id for item in products}
        for retrieval in retrievals:
            if retrieval.source_id not in sources:
                failures.append(f"{retrieval.retrieval_id}: missing source {retrieval.source_id}")
        for conflict in conflicts:
            for claim_id in conflict.claim_ids:
                if claim_id not in claim_ids:
                    failures.append(f"{conflict.conflict_group_id}: missing claim {claim_id}")
        for factory in factories:
            if factory.operator_entity_id not in entities:
                failures.append(f"{factory.factory_id}: missing operator {factory.operator_entity_id}")
        all_graph_ids = entities | factory_ids | product_ids
        for edge in edges:
            if edge.from_id not in all_graph_ids:
                failures.append(f"{edge.edge_id}: missing from_id {edge.from_id}")
            if edge.to_id not in all_graph_ids:
                failures.append(f"{edge.edge_id}: missing to_id {edge.to_id}")
        for image in images:
            if image.source_id not in sources:
                failures.append(f"{image.image_id}: missing source {image.source_id}")
            if image.entity_id and image.entity_id not in entities:
                failures.append(f"{image.image_id}: missing entity {image.entity_id}")
            if image.factory_id and image.factory_id not in factory_ids:
                failures.append(f"{image.image_id}: missing factory {image.factory_id}")
            if image.product_id and image.product_id not in product_ids:
                failures.append(f"{image.image_id}: missing product {image.product_id}")
        for product in products:
            if product.entity_id not in entities:
                failures.append(f"{product.product_id}: missing entity {product.entity_id}")
            for source_id in product.source_ids:
                if source_id not in sources:
                    failures.append(f"{product.product_id}: missing source {source_id}")
        for profile in energy_profiles:
            if profile.entity_id not in entities:
                failures.append(f"{profile.energy_profile_id}: missing entity {profile.entity_id}")
            if profile.factory_id and profile.factory_id not in factory_ids:
                failures.append(f"{profile.energy_profile_id}: missing factory {profile.factory_id}")
            for claim_id in profile.claim_ids:
                if claim_id not in claim_ids:
                    failures.append(f"{profile.energy_profile_id}: missing claim {claim_id}")
        if failures:
            raise EvidenceStoreError("Referential integrity failed: " + "; ".join(failures))
