from __future__ import annotations

from enterprise_energy_research.evidence.store import EvidenceStore

from .normalizer import NormalizedEvidence


class EvidenceIngestor:
    ORDER = (
        "entity", "factory", "product", "edge", "source", "retrieval", "claim",
        "conflict", "gap", "image", "energy_profile", "solution",
    )
    ATTR_BY_KIND = {
        "entity": "entities", "factory": "factories", "product": "products", "edge": "edges",
        "source": "sources", "retrieval": "retrievals", "claim": "claims",
        "conflict": "conflicts", "gap": "gaps", "image": "images",
        "energy_profile": "energy_profiles", "solution": "solutions",
    }

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def ingest(self, run_id: str, evidence_version: int, evidence: NormalizedEvidence) -> None:
        for kind in self.ORDER:
            for record in getattr(evidence, self.ATTR_BY_KIND[kind]):
                self.store.add(run_id, evidence_version, kind, record)

