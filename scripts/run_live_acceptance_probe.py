from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
from enterprise_energy_research.adapters.base import SearchRequest


DIRECTORIES = (
    "01_evidence", "02_research_quality", "03_visual_assets", "04_word",
    "05_excel", "06_html", "07_validation",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fail-closed live discovery probe for acceptance readiness")
    parser.add_argument("company")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in DIRECTORIES:
        (args.output / name).mkdir(parents=True, exist_ok=True)
    adapter = AnySearchCliAdapter()
    requests = [
        SearchRequest(query_id="LIVE-R1-IDENTITY", query=f'"{args.company}" 官网 年报 公司简介', entity_id="LIVE", purpose="R1 official identity discovery", max_results=3),
        SearchRequest(query_id="LIVE-R1-CATALOG", query=f'"{args.company}" 官网 产品中心 产品目录 型号', entity_id="LIVE", purpose="R1 official catalog discovery", max_results=3),
        SearchRequest(query_id="LIVE-R1-ENERGY", query=f'"{args.company}" 能耗 光伏 储能 绿色工厂 环评', entity_id="LIVE", purpose="R1 energy evidence discovery", max_results=3),
    ]
    envelopes = [adapter.search(request) for request in requests]
    hits = []
    for envelope in envelopes:
        for hit in envelope.hits:
            hits.append({
                "query_id": envelope.query_id, "requested_url": hit.requested_url, "final_url": hit.final_url,
                "title": hit.title, "status": hit.status, "retrieved_at": hit.retrieved_at,
                "text_preview": (hit.text or "")[:4000], "metadata": hit.metadata,
            })
    (args.output / "01_evidence" / "live_search_hits.json").write_text(json.dumps({"company": args.company, "hits": hits}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    domains = {urlparse(str(item["final_url"])).netloc for item in hits if item.get("final_url")}
    saturation = {
        "status": "BLOCKED", "completed_rounds": ["R1_DISCOVERY_PROBE"],
        "missing_rounds": ["R1_FULL_COVERAGE", "R2_GAP_DRIVEN_DEPTH", "R3_TRIANGULATION"],
        "findings": ["Discovery hits are not VERIFIED evidence", "No LLM extraction/evidence validation/freeze was authorized or configured for this probe"],
    }
    quality = {
        "schema_version": "1.0", "goal_coverage": 0.0, "source_diversity": len(domains),
        "official_source_ratio": 0.0, "verified_claim_ratio": 0.0, "triangulated_claim_ratio": 0.0,
        "catalog_coverage": 0.0, "parameter_coverage": 0.0, "image_coverage": 0.0,
        "critical_gap_count": 1, "conflict_count": 0, "saturation_status": "BLOCKED",
        "diagnostics": saturation["findings"],
    }
    (args.output / "02_research_quality" / "saturation_report.json").write_text(json.dumps(saturation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "02_research_quality" / "research_quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "company": args.company, "status": "BLOCKED", "acceptance_level": "LIVE_DISCOVERY_PROBE_ONLY",
        "search_calls": len(envelopes), "search_statuses": [item.status for item in envelopes],
        "discovered_urls": len(hits), "unique_domains": len(domains), "verified_claims": 0,
        "word_pages": 0, "visuals": 0, "images": 0, "artifact_consistency": "NOT_RUN",
        "missing_outputs": ["FrozenResearchBundle", "formal Word", "formal Excel", "unified HTML", "rendered visual QA", "cross-artifact consistency"],
        "diagnostics": [message for envelope in envelopes for message in envelope.diagnostics],
    }
    (args.output / "07_validation" / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "07_validation" / "artifact_consistency_report.json").write_text(json.dumps({"status": "BLOCKED", "reason": "No frozen artifacts were produced by the discovery-only probe"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
