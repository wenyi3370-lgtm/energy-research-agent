"""Unified publication plane (§37/§38).

One artifact owner: after the agent finishes synthesis, the enterprise run's
evidence and the market evidence are merged into one unified evidence run,
frozen as a single snapshot, and published through the same deterministic
chain the portal uses (Phase2Runner + ArtifactPublicationService). Cross-domain
findings ride into the frozen bundle so every publisher renders the
enterprise-market chapters without any publisher change. Overseas deliverables
are referenced as validated sub-artifacts, never re-published.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from enterprise_energy_research.domain.enums import RunStatus, SourceLevel
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import CrossDomainFinding, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore, canonical_json
from enterprise_energy_research.graph.runner import Phase2Runner
from enterprise_energy_research.graph.state import ResearchState

# Record kinds carried into the unified freeze (analysis payloads are
# recomputed by the pipeline; images/products stay with their source run).
UNIFIED_KINDS = ("entity", "factory", "edge", "source", "retrieval", "claim", "conflict", "gap", "product", "image")

# Per-run sequence ids (SOURCE-S001, CLAIM-000123, IMAGE-I001, ...) restart in
# every run, so raw record ids collide across runs. Merging by id alone lets a
# later run's same-id record shadow an earlier one and silently re-binds that
# run's claims to the earlier run's source (observed as VERIFIED claims bound
# to SOURCE_C/D records -> WEAK_SOURCE_MARKED_VERIFIED -> publication
# BLOCKED). The merge therefore namespaces colliding ids and rewrites every
# cross-record reference.
_ID_FIELD = {"conflict": "conflict_group_id"}
_ID_PREFIX = {
    "entity": "ENT", "factory": "FAC", "edge": "EDGE", "source": "SOURCE",
    "retrieval": "RETRIEVAL", "claim": "CLAIM", "conflict": "CONFLICT",
    "gap": "GAP", "product": "PROD", "image": "IMAGE",
}
# Kind processing order: natural-key dedup for products needs the entity and
# image remaps resolved first.
_MERGE_ORDER = ("entity", "source", "image", "factory", "edge", "retrieval", "claim", "conflict", "gap", "product")
_SINGLE_REFS = {
    "entity": ("parent_entity_id", "actual_controller_entity_id"),
    "factory": ("operator_entity_id",),
    "edge": ("from_id", "to_id"),
    "retrieval": ("source_id",),
    "claim": ("entity_id", "source_id", "conflict_group_id"),
    "conflict": ("entity_id",),
    "gap": ("entity_id",),
    "product": ("entity_id", "image_id"),
    "image": ("source_id", "entity_id", "factory_id", "product_id"),
}
_LIST_REFS = {
    "entity": ("supporting_claim_ids",),
    "factory": ("supporting_claim_ids",),
    "edge": ("claim_ids",),
    "conflict": ("claim_ids", "selected_claim_ids"),
    "product": ("source_ids",),
}


def _record_id(record: Any, kind: str) -> str:
    field = _ID_FIELD.get(kind, f"{kind}_id")
    return str(getattr(record, field, "") or getattr(record, "record_id", "") or "")


def _name_key(value: Any) -> str:
    return "".join(str(value or "").casefold().split())


def _natural_key(kind: str, record: Any) -> str | None:
    """Cross-run identity for kinds that re-extract the same real-world object
    under a fresh per-run id: sources by URL, entities by name, images by
    content hash, products by owner+name+model."""
    if kind == "source":
        url = str(getattr(record, "canonical_url", "") or "")
        return f"url:{url}" if url else None
    if kind == "entity":
        name = _name_key(getattr(record, "canonical_name", ""))
        return f"name:{getattr(record, 'entity_type', '')}:{name}" if name else None
    if kind == "image":
        digest = str(getattr(record, "sha256", "") or "")
        return f"sha:{digest}" if digest else None
    if kind == "product":
        name = _name_key(getattr(record, "name", ""))
        if not name:
            return None
        return "prod:{}:{}:{}:{}".format(
            getattr(record, "entity_id", ""), name,
            _name_key(getattr(record, "brand", "")), _name_key(getattr(record, "model", "")),
        )
    return None


def _payload_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_json(left.model_dump(mode="json")) == canonical_json(right.model_dump(mode="json"))
    except Exception:
        return False


_SOURCE_RANK = {
    SourceLevel.SOURCE_A: 4, SourceLevel.SOURCE_B: 3,
    SourceLevel.SOURCE_C: 2, SourceLevel.SOURCE_D: 1,
}


def _source_rank(record: Any) -> int:
    return _SOURCE_RANK.get(getattr(record, "source_level", None), 0)


def _remap_references(kind: str, record: Any, target_id: str, id_map: dict[str, str]) -> Any:
    update: dict[str, Any] = {}
    id_field = _ID_FIELD.get(kind, f"{kind}_id")
    if target_id != _record_id(record, kind):
        update[id_field] = target_id
    for field in _SINGLE_REFS.get(kind, ()):
        value = getattr(record, field, None)
        if value and value in id_map:
            update[field] = id_map[value]
    for field in _LIST_REFS.get(kind, ()):
        values = list(getattr(record, field, None) or [])
        mapped = [id_map.get(value, value) for value in values]
        if mapped != values:
            update[field] = mapped
    if not update:
        return record
    return record.model_copy(update=update)


def merge_evidence(
    unified: EvidenceStore,
    unified_run_id: str,
    version: int,
    *stores: tuple[EvidenceStore, str],
) -> dict[str, int]:
    """Copy records from source runs into the unified run.

    Same-id records that are byte-identical (a run copying its parent's rows)
    deduplicate; same-id records that differ get a fresh sortable id, and every
    reference to the old id is rewritten. Same-object records across runs
    (same source URL / entity name / image hash / product) collapse onto the
    first occurrence so claims never re-bind to a foreign record.
    """
    counts: dict[str, int] = {}
    natural_ids: dict[tuple[str, str], str] = {}
    natural_rank: dict[tuple[str, str], int] = {}
    for store, run_id in stores:
        records_by_kind: dict[str, list[Any]] = {}
        for kind in UNIFIED_KINDS:
            try:
                records_by_kind[kind] = list(store.list(run_id, kind))
            except Exception:
                records_by_kind[kind] = []
        # Pass 1: decide every record's target id and build the id map before
        # any record is written, so forward references (claim -> conflict)
        # resolve no matter the kind order.
        id_map: dict[str, str] = {}
        additions: list[tuple[str, Any, str]] = []
        for kind in _MERGE_ORDER:
            for record in records_by_kind.get(kind, []):
                record_id = _record_id(record, kind)
                if not record_id:
                    continue
                target_id = record_id
                skip = False
                key = _natural_key(kind, record)
                rank = _source_rank(record) if kind == "source" else 0
                if key is not None and key in natural_ids:
                    if kind == "source" and rank > natural_rank.get(key, 0):
                        # One run can declare the same URL twice with different
                        # source_kind, grading it both weak and strong. The URL
                        # must never downgrade: keep the stronger grading as its
                        # own record and re-point the URL so later duplicates
                        # dedup onto the stronger source.
                        if unified.has_record(unified_run_id, kind, record_id):
                            target_id = new_sortable_id(_ID_PREFIX[kind])
                        natural_ids[key] = target_id
                        natural_rank[key] = rank
                    else:
                        target_id, skip = natural_ids[key], True
                elif unified.has_record(unified_run_id, kind, record_id):
                    existing = None
                    try:
                        existing = unified.get(unified_run_id, kind, record_id)
                    except Exception:
                        existing = None
                    if existing is not None and _payload_equal(record, existing):
                        skip = True
                        if key is not None:
                            natural_ids.setdefault(key, record_id)
                            if kind == "source":
                                natural_rank.setdefault(key, rank)
                    else:
                        target_id = new_sortable_id(_ID_PREFIX[kind])
                if target_id != record_id:
                    id_map[record_id] = target_id
                if not skip:
                    additions.append((kind, record, target_id))
                    if key is not None:
                        natural_ids.setdefault(key, target_id)
                        if kind == "source":
                            natural_rank.setdefault(key, rank)
        # Pass 2: write with remapped ids and references.
        for kind, record, target_id in additions:
            try:
                unified.add(unified_run_id, version, kind, _remap_references(kind, record, target_id, id_map))
                counts[kind] = counts.get(kind, 0) + 1
            except Exception:
                continue
    return counts


def _materialize_source_assets(run_dir: Path, source_run_dirs: list[Path]) -> int:
    """Copy archived image bytes from each merged source run into the unified
    run's evidence assets dir.

    ``merge_evidence`` only copies the image RECORDS (metadata) into the unified
    store; the byte files remain under each source run's own
    ``outputs/01_evidence/assets``. At publish time ``local_asset_ref`` is
    resolved against the unified run tree only, so the merged relative refs are
    dangling and every verified image is dropped ("no resolvable
    local_asset_ref") -> 0 product images -> the image gate blocks the run.
    Materializing the bytes keeps the unified frozen snapshot self-contained.
    """
    target_root = run_dir / "outputs" / "01_evidence" / "assets"
    copied = 0
    for source_dir in source_run_dirs:
        try:
            same = source_dir.resolve() == run_dir.resolve()
        except Exception:
            same = False
        if same:
            continue
        source_assets = source_dir / "outputs" / "01_evidence" / "assets"
        if not source_assets.is_dir():
            continue
        for src_file in source_assets.rglob("*"):
            if not src_file.is_file():
                continue
            relative = src_file.relative_to(source_assets)
            dest = target_root / relative
            try:
                if dest.exists() and dest.stat().st_size == src_file.stat().st_size:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src_file, dest)
                copied += 1
            except Exception:
                continue
    return copied


def publish_unified(
    *,
    workdir: Path,
    enterprise_run_id: str,
    findings: list[CrossDomainFinding],
    sub_artifact_refs: list[str],
    recovery_run_ids: list[str] | None = None,
    market_evidence_store: EvidenceStore | None = None,
    market_run_id: str | None = None,
    publishers: dict | None = None,
) -> dict[str, Any]:
    """Merge -> validate -> freeze -> artifact-publish -> QA surface (§37)."""
    from enterprise_energy_research.artifacts.publisher import ArtifactPublicationService
    from enterprise_energy_research.automation.executor import default_publishers
    from enterprise_energy_research.domain.ids import new_sortable_id
    from enterprise_energy_research.evidence.store import canonical_json
    from enterprise_energy_research.release.audit import ArtifactConsistencyAuditor

    run_dir = Path(workdir) / enterprise_run_id
    enterprise_store = EvidenceStore(run_dir / "evidence.sqlite3")
    try:
        enterprise_run = enterprise_store.get_run(enterprise_run_id)
    except Exception as exc:
        return {"status": "BLOCKED", "diagnostics": [f"enterprise run unavailable: {exc}"[:300]]}
    version = enterprise_run.evidence_version
    unified_run_id = f"{enterprise_run_id}-unified"
    unified_path = run_dir / "unified_evidence.sqlite3"
    if unified_path.exists():
        unified_path.unlink()
    unified = EvidenceStore(unified_path)
    unified.create_run(RunManifest(
        run_id=unified_run_id,
        request_id=enterprise_run.request_id,
        status=RunStatus.RUNNING,
        canonical_entity_id=enterprise_run.canonical_entity_id,
        config_hash=enterprise_run.config_hash,
        code_version=enterprise_run.code_version,
        model_gateway=enterprise_run.model_gateway,
        evidence_version=version,
    ))
    sources: list[tuple[EvidenceStore, str]] = [(enterprise_store, enterprise_run_id)]
    source_run_dirs: list[Path] = [run_dir]
    # Recovery rounds produced their own run stores; merge them so the unified
    # freeze contains everything the agent evaluated, not just the first pass.
    for recovery_run_id in recovery_run_ids or []:
        if recovery_run_id and recovery_run_id != enterprise_run_id:
            recovery_store = EvidenceStore(Path(workdir) / recovery_run_id / "evidence.sqlite3")
            sources.append((recovery_store, recovery_run_id))
            source_run_dirs.append(Path(workdir) / recovery_run_id)
    if market_evidence_store is not None and market_run_id:
        sources.append((market_evidence_store, market_run_id))
    merged = merge_evidence(unified, unified_run_id, version, *sources)

    detection = None
    detection_path = run_dir / "product_detection.json"
    if detection_path.is_file():
        try:
            from enterprise_energy_research.domain.models import ProductDetection
            detection = ProductDetection.model_validate_json(detection_path.read_text(encoding="utf-8"))
        except Exception:
            detection = None

    state = ResearchState(run_id=unified_run_id, request_id=enterprise_run.request_id, status=RunStatus.RUNNING)
    final_state, manifest = Phase2Runner(unified).finalize_evidence(
        state,
        output_dir=run_dir / "outputs" / "01_evidence",
        product_detection=detection,
    )
    if final_state.freeze_id is None or manifest is None:
        return {
            "status": "BLOCKED",
            "diagnostics": ["unified validation blocked: " + "; ".join(final_state.blocking_findings)],
            "merged": merged,
        }

    bundle = FreezeService(unified).load_bundle(final_state.freeze_id)
    # §36: findings are attached to the frozen bundle so publishers render the
    # enterprise-market chapters; they reference frozen claim ids only.
    bundle.cross_domain_findings = list(findings)
    # §37: overseas deliverables are validated sub-artifacts, referenced not
    # re-published.
    manifest.sub_artifact_refs = list(sub_artifact_refs)
    # Persist the updated manifest (finalize_evidence inserted the original).
    with unified.connect() as connection:
        connection.execute(
            "UPDATE artifact_manifests SET payload = ? WHERE artifact_manifest_id = ?",
            (canonical_json(manifest), manifest.artifact_manifest_id),
        )

    # Bring the archived image bytes from every merged source run into the
    # unified run so local_asset_ref resolves during publication (records were
    # merged but their asset files were not).
    _materialize_source_assets(run_dir, source_run_dirs)

    results = ArtifactPublicationService(publishers if publishers is not None else default_publishers()).publish(
        bundle, manifest, run_dir / "outputs" / "artifacts"
    )
    audit = ArtifactConsistencyAuditor().audit(bundle, manifest, results)
    review_reasons = [f"{finding.code}: {finding.message}" for finding in audit.findings]

    qa_status = "unknown"
    qa_fail_findings: list[str] = []
    for qa_file in (run_dir / "outputs" / "artifacts").rglob("publication_qa_report.json"):
        try:
            report = json.loads(qa_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        file_status = str(report.get("status", "unknown"))
        if file_status == "fail":
            qa_status = "fail"
        elif qa_status == "unknown":
            qa_status = file_status
        for finding in report.get("findings", []):
            if str(finding.get("severity", "")).lower() not in {"error", "blocker"}:
                continue
            code = str(finding.get("code") or "publication_failure")
            message = str(finding.get("message") or code)
            entry = f"{code}: {message}"
            if entry not in qa_fail_findings:
                qa_fail_findings.append(entry)
    # Hard content gates (main-body character count, depth, image coverage)
    # live in the consulting-narrative validation report; their FAIL checks
    # must reach the mission layer so thin-evidence BLOCKED runs are
    # diagnosable instead of opaque.
    for validation_file in (run_dir / "outputs" / "artifacts").rglob("consulting_narrative_validation.json"):
        try:
            payload = json.loads(validation_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for check in payload.get("checks", []):
            if str(check.get("status", "")).upper() != "FAIL":
                continue
            entry = f"{check.get('code')}: {check.get('message')}"
            if entry not in qa_fail_findings:
                qa_fail_findings.append(entry)
    review_reasons = review_reasons + [
        reason for reason in qa_fail_findings if reason not in review_reasons
    ]

    status = "BLOCKED" if qa_status == "fail" else "OK"
    diagnostics = []
    if status == "BLOCKED":
        diagnostics.append(
            "publication QA fail; blocking gates: "
            + "; ".join(qa_fail_findings[:6] or review_reasons[:3])
        )
    return {
        "status": status,
        "run_id": unified_run_id,
        "freeze_id": final_state.freeze_id,
        "artifacts": sorted(
            {str(result.path) for result in results if result.path} | set(sub_artifact_refs)
        ),
        "merged": merged,
        "review_reasons": review_reasons,
        "qa_status": qa_status,
        "findings_count": len(findings),
        "diagnostics": diagnostics,
    }
