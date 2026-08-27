from __future__ import annotations

import hashlib
import json
from typing import Any

from energy_research_agent.domain.enums import Severity, ValidationStatus
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.domain.models import DataFreeze, FrozenResearchBundle, ValidationReport

from .store import EvidenceStore, EvidenceStoreError, canonical_json


class FreezeError(RuntimeError):
    pass


class FreezeService:
    KINDS = (
        "entity", "factory", "edge", "source", "retrieval", "claim", "conflict",
        "gap", "image", "product", "energy_profile", "solution",
    )

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def create(self, run_id: str, evidence_version: int, report: ValidationReport) -> DataFreeze:
        if report.run_id != run_id:
            raise FreezeError("validation report belongs to another run")
        if report.status == ValidationStatus.BLOCKED:
            raise FreezeError("cannot freeze a blocked validation report")
        if any(f.severity in {Severity.ERROR, Severity.BLOCKER} for f in report.findings):
            raise FreezeError("cannot freeze while error or blocker findings remain")
        self.store.assert_referential_integrity(run_id, evidence_version)

        included: dict[str, list[str]] = {}
        hashes: dict[str, str] = {}
        for kind in self.KINDS:
            records = self.store.list(run_id, kind, up_to_version=evidence_version)
            from .store import ID_FIELD_BY_KIND
            id_field = ID_FIELD_BY_KIND[kind]
            ids: list[str] = []
            for record in records:
                record_id = str(getattr(record, id_field))
                ids.append(record_id)
                hashes[f"{kind}/{record_id}"] = hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()
            included[kind] = ids

        root_payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        root_hash = hashlib.sha256(root_payload).hexdigest()
        # Artifact QA may require multiple publication passes over an
        # unchanged immutable evidence version.  Freezing is therefore
        # idempotent: reuse the existing snapshot when (and only when) its
        # Merkle-style root is identical.  This preserves the no-mutation
        # contract while allowing Word/HTML/chart regeneration after a failed
        # publisher pass.
        with self.store.connect() as connection:
            existing = connection.execute(
                "SELECT payload, root_hash FROM freezes WHERE run_id = ? AND evidence_version = ?",
                (run_id, evidence_version),
            ).fetchone()
        if existing is not None:
            if existing["root_hash"] != root_hash:
                raise FreezeError(
                    f"Existing freeze root mismatch for {run_id} version {evidence_version}"
                )
            return DataFreeze.model_validate_json(existing["payload"])

        freeze = DataFreeze(
            freeze_id=new_sortable_id("FREEZE"),
            run_id=run_id,
            evidence_version=evidence_version,
            included_record_ids=included,
            record_hashes=hashes,
            root_hash=root_hash,
            validation_report_id=report.validation_report_id,
        )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO validation_reports(validation_report_id, run_id, payload) VALUES (?, ?, ?)",
                (report.validation_report_id, run_id, canonical_json(report)),
            )
            try:
                connection.execute(
                    "INSERT INTO freezes(freeze_id, run_id, evidence_version, payload, root_hash) VALUES (?, ?, ?, ?, ?)",
                    (freeze.freeze_id, run_id, evidence_version, canonical_json(freeze), freeze.root_hash),
                )
            except Exception as exc:
                raise FreezeError(f"Could not create freeze for {run_id} version {evidence_version}") from exc
        return freeze

    def load_bundle(self, freeze_id: str) -> FrozenResearchBundle:
        with self.store.connect() as connection:
            row = connection.execute("SELECT payload, run_id FROM freezes WHERE freeze_id = ?", (freeze_id,)).fetchone()
        if not row:
            raise FreezeError(f"Unknown freeze: {freeze_id}")
        freeze = DataFreeze.model_validate_json(row["payload"])
        run = self.store.get_run(freeze.run_id)
        return FrozenResearchBundle(
            freeze=freeze,
            run_manifest=run,
            entities=self.store.list(freeze.run_id, "entity", up_to_version=freeze.evidence_version),
            factories=self.store.list(freeze.run_id, "factory", up_to_version=freeze.evidence_version),
            edges=self.store.list(freeze.run_id, "edge", up_to_version=freeze.evidence_version),
            sources=self.store.list(freeze.run_id, "source", up_to_version=freeze.evidence_version),
            retrievals=self.store.list(freeze.run_id, "retrieval", up_to_version=freeze.evidence_version),
            claims=self.store.list(freeze.run_id, "claim", up_to_version=freeze.evidence_version),
            conflicts=self.store.list(freeze.run_id, "conflict", up_to_version=freeze.evidence_version),
            gaps=self.store.list(freeze.run_id, "gap", up_to_version=freeze.evidence_version),
            images=self.store.list(freeze.run_id, "image", up_to_version=freeze.evidence_version),
            products=self.store.list(freeze.run_id, "product", up_to_version=freeze.evidence_version),
            energy_profiles=self.store.list(freeze.run_id, "energy_profile", up_to_version=freeze.evidence_version),
            solutions=self.store.list(freeze.run_id, "solution", up_to_version=freeze.evidence_version),
        )
