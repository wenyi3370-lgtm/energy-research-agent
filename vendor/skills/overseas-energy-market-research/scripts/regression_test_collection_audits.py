# -*- coding: utf-8 -*-
"""Regression: generate_collection_audits.py project configuration (v1.2.6).

Covers the CHANGELOG v1.2.6 fixes that turned cross-project hardcoding into
frozen-snapshot `generator_overrides`:

1. registry market / created_date come from the frozen policy snapshot
   (template default = legacy Spain behavior; project override = e.g. Australia),
2. `tech_keywords` override re-classifies 04_Product_Parameters rows between
   the technology_performance and product_parameters pools,
3. an empty round segment (pool shortage) prints a [WARN] diagnostic instead
   of silently writing an empty count-evidence audit,
4. `--overrides` merge semantics in upgrade_collection_policy._merge_overrides
   (top-level replace + nested dict merge).

Run:  python regression_test_collection_audits.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from collection_quantity_policy import (  # noqa: E402
    POLICY_PATH,
    freeze_current_policy,
    freeze_policy_dict,
    load_policy,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[list[str]]) -> None:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(fieldnames)
    for r in rows:
        w.writerow(r)
    path.write_text("\ufeff" + out.getvalue(), encoding="utf-8")



TASK_FIELDS = ["task_id", "stage", "platform", "market", "language", "goal_family",
               "collection_goal", "target_geography", "target_brand", "exact_model",
               "identifier_type", "identifier_value", "starting_url_or_query", "required_tool",
               "source_tier", "planned_fields", "completion_contract", "target_unique_sources",
               "target_records", "source_type_count", "platform_count", "primary_source_count",
               "critical_claim_count", "dual_sourced_claim_count", "remaining_high_priority_count",
               "no_new_high_priority_batches", "count_evidence_refs", "platform_limit_evidence",
               "quantity_exception_type", "quantity_exception_refs", "round", "round_goal",
               "output_file", "raw_capture_path", "saturation_evidence", "status", "notes"]


def task_row(tid: str, rnd: int, round_goal: str, *, family: str = "market_size_and_demand",
             model: str = "", target_sources: str = "2", target_records: str = "2") -> list[str]:
    base = {f: "" for f in TASK_FIELDS}
    base.update({
        "task_id": tid, "stage": "4", "platform": "web", "market": "Australia",
        "language": "en", "goal_family": family,
        "collection_goal": "family_collection", "target_geography": "Australia",
        "exact_model": model,
        "starting_url_or_query": "query", "required_tool": "anysearch",
        "source_tier": "tier1", "planned_fields": "metric", "completion_contract": "contract",
        "target_unique_sources": target_sources, "target_records": target_records,
        "round": str(rnd), "round_goal": round_goal,
        "output_file": "evidence.csv", "raw_capture_path": "raw_capture/round%s" % rnd,
        "saturation_evidence": "R%s done" % rnd, "status": "pending",
    })
    return [base[f] for f in TASK_FIELDS]


def _make_project(tmp: Path) -> Path:
    """Scaffold a minimal research project directory."""
    project = tmp / "proj"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.mkdir(exist_ok=True)
    # 00_Source_Ledger.csv — two sources
    _write_csv(
        project / "00_Source_Ledger.csv",
        ["source_id", "source_type", "platform_id", "publisher_group", "source_url",
         "root_domain", "canonical_source_id", "source_relation_type", "verification_status",
         "reliability_tier", "collection_tool", "evidence_item", "value_class",
         "source_title", "publisher", "local_file_path", "access_date", "data_type",
         "global_region", "country", "province_state", "city_site", "evidence_row_ids"],
        [
            ["S001", "official_regulator", "s001.gov", "gov", "https://s001.gov/x",
             "s001.gov", "S001", "original", "verified", "tier1", "anysearch",
             "reg data", "observed", "T", "T", "", "2026-08-12", "stats",
             "Oceania", "Australia", "", "", "01_Market_Scan.csv#2"],
            ["S002", "independent_media", "s002.media", "media", "https://s002.media/y",
             "s002.media", "S002", "original", "verified", "tier3", "anysearch",
             "media", "observed", "T", "T", "", "2026-08-12", "stats",
             "Oceania", "Australia", "", "", "01_Market_Scan.csv#3"],
        ],
    )
    # 02_Web_Collection_Tasks.csv — one family, R1/R2/R3 tasks
    _write_csv(
        project / "02_Web_Collection_Tasks.csv",
        ['task_id', 'stage', 'platform', 'market', 'language', 'goal_family', 'collection_goal', 'target_geography', 'target_brand', 'exact_model', 'identifier_type', 'identifier_value', 'starting_url_or_query', 'required_tool', 'source_tier', 'planned_fields', 'completion_contract', 'target_unique_sources', 'target_records', 'source_type_count', 'platform_count', 'primary_source_count', 'critical_claim_count', 'dual_sourced_claim_count', 'remaining_high_priority_count', 'no_new_high_priority_batches', 'count_evidence_refs', 'platform_limit_evidence', 'quantity_exception_type', 'quantity_exception_refs', 'round', 'round_goal', 'output_file', 'raw_capture_path', 'saturation_evidence', 'status', 'notes'],
        [task_row("T-1", 1, "coverage", family="market_size_and_demand", target_records="2"),
         task_row("T-2", 2, "depth", family="market_size_and_demand", target_records="2"),
         task_row("T-3", 3, "triangulate", family="market_size_and_demand", target_records="2"),
         task_row("T-4", 1, "coverage", family="technology_performance", model="Model X",
                  target_sources="4", target_records="4"),
         task_row("T-5", 2, "depth", family="technology_performance", model="Model X",
                  target_sources="8", target_records="8"),
         task_row("T-6", 3, "triangulate", family="technology_performance", model="Model X",
                  target_sources="2", target_records="2")],
    )
    # 01_Market_Scan.csv — two rows (two sources), one more row from S002
    _write_csv(
        project / "01_Market_Scan.csv",
        ["record_id", "value_class", "global_region", "country", "market_segment",
         "metric", "year_period", "raw_value", "source_id", "source_url",
         "access_date", "verification_status", "notes"],
        [
            ["R1", "observed", "Oceania", "Australia", "market size", "TAM",
             "2025", "100", "S001", "https://s001.gov/x", "2026-08-12", "verified", ""],
            ["R2", "observed", "Oceania", "Australia", "market size", "SAM",
             "2025", "80", "S002", "https://s002.media/y", "2026-08-12", "verified", ""],
            ["R3", "observed", "Oceania", "Australia", "market size", "SOM",
             "2025", "50", "S002", "https://s002.media/y", "2026-08-12", "verified", ""],
        ],
    )
    # 04_Product_Parameters.csv — one "效率" row (tech by default) + one "电压" row
    _write_csv(
        project / "04_Product_Parameters.csv",
        ["parameter_id", "brand", "exact_model", "parameter_group", "parameter_name",
         "raw_value", "unit", "source_priority", "source_url", "local_file_path",
         "local_file_location", "access_or_extraction_date", "identifier",
         "verification_status", "web_source_reason", "notes", "source_id"],
        [
            ["PAR-1", "B", "Model X", "technology", "效率", "95%", "%", "official web",
             "https://s001.gov/x", "", "", "2026-08-12", "Model X", "verified",
             "no local file", "", "S001"],
            ["PAR-2", "B", "Model X", "product", "电压", "750", "V", "official web",
             "https://s002.media/y", "", "", "2026-08-12", "Model X", "verified",
             "no local file", "", "S002"],
        ],
    )
    # minimal 02_Competitor_List / 05..08 tables (empty)
    for name in ("02_Competitor_List.csv", "03_Model_Identifier_Check.csv", "05_Pricing_Channel.csv",
                 "06_Channel_Service.csv", "07_Raw_Reviews.csv", "08_Review_Coding.csv"):
        _write_csv(project / name, ["col"], [])
    return project


def _write_manifest(project: Path, fields: dict) -> None:
    manifest = {"region": "Australia", "category": "v2g"}
    manifest.update(fields)
    (project / "project_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _run_generator(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "generate_collection_audits.py"), "--project-dir", str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _registry_market(project: Path) -> list[str]:
    path = project / "15_Collection_Record_Registry.csv"
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    return [r.get("market", "") for r in rows]


def test_default_template_behavior(tmp: Path) -> None:
    project = _make_project(tmp / "test_default_template_behavior")
    fields = freeze_current_policy(project, "2026-08-12T00:00:00")
    _write_manifest(project, fields)
    result = _run_generator(project)
    assert result.returncode == 0, result.stdout + result.stderr
    markets = _registry_market(project)
    assert markets, "registry should have rows"
    assert all(m == "Spain" for m in markets), f"default market should be Spain, got {set(markets)}"
    reg = (project / "15_Collection_Record_Registry.csv").read_text(encoding="utf-8-sig")
    assert "2026-01-01" in reg, "default created_date should be 2026-01-01"
    print("  [PASS] default template behavior (market=Spain, created_date=2026-01-01)")


def test_project_override_market(tmp: Path) -> None:
    project = _make_project(tmp / "test_project_override_market")
    template = load_policy(POLICY_PATH)
    merged = dict(template)
    merged["generator_overrides"] = {
        **dict(template.get("generator_overrides") or {}),
        "market": "Australia",
        "created_date": "2026-08-12",
    }
    fields = freeze_policy_dict(project, merged, "2026-08-12T00:00:00")
    _write_manifest(project, fields)
    result = _run_generator(project)
    assert result.returncode == 0, result.stdout + result.stderr
    markets = _registry_market(project)
    assert markets and all(m == "Australia" for m in markets), f"expected Australia, got {set(markets)}"
    reg = (project / "15_Collection_Record_Registry.csv").read_text(encoding="utf-8-sig")
    assert "2026-08-12" in reg, "created_date should come from overrides"
    print("  [PASS] project override (market=Australia, created_date=2026-08-12)")


def test_tech_keywords_override(tmp: Path) -> None:
    project = _make_project(tmp / "test_tech_keywords_override")
    template = load_policy(POLICY_PATH)
    merged = dict(template)
    merged["generator_overrides"] = {
        **dict(template.get("generator_overrides") or {}),
        # empty tech keywords -> 04 rows all go to product_parameters;
        # market override combined to prove multi-key overrides coexist
        "tech_keywords": [],
        "market": "Australia",
    }
    fields = freeze_policy_dict(project, merged, "2026-08-12T00:00:00")
    _write_manifest(project, fields)
    result = _run_generator(project)
    assert result.returncode == 0, result.stdout + result.stderr
    # TEC pool has a single "效率" row but R2/R3 floors need 8/2 more rows:
    # the generator must print a [WARN] for the empty segments instead of
    # silently writing empty audits (v1.2.6 diagnostics).
    assert "[WARN]" in (result.stdout + result.stderr), "empty segment should warn"
    # registry stays consistent (market from overrides)
    markets = _registry_market(project)
    assert markets and all(m == "Australia" for m in markets)
    print("  [PASS] tech_keywords override + empty-segment [WARN] diagnostic")


def test_merge_overrides_semantics(tmp: Path) -> None:
    from upgrade_collection_policy import _merge_overrides

    template = load_policy(POLICY_PATH)
    overrides_file = tmp / "ov.yaml"
    overrides_file.write_text(
        "market: Australia\n"
        "domain_to_source_id:\n"
        "  new.host.example: S099\n"
        "  solar.huawei.com: S100\n",
        encoding="utf-8",
    )
    merged = _merge_overrides(template, str(overrides_file))
    ov = merged["generator_overrides"]
    assert ov["market"] == "Australia"
    assert ov["domain_to_source_id"]["new.host.example"] == "S099"
    assert ov["domain_to_source_id"]["solar.huawei.com"] == "S100", "nested key should be replaced"
    assert ov["domain_to_source_id"]["eurostat.eu"] == "S010", "unlisted nested keys preserved"
    assert "tech_keywords" in ov, "unlisted top-level keys preserved"
    print("  [PASS] _merge_overrides semantics (top-level replace + nested merge)")


def main() -> int:
    print("Collection audit generator regression (v1.2.6):")
    tmp = Path(tempfile.mkdtemp(prefix="gca_reg_"))
    try:
        test_default_template_behavior(tmp)
        test_project_override_market(tmp)
        test_tech_keywords_override(tmp)
        test_merge_overrides_semantics(tmp)
    finally:
        # frozen policy snapshots are read-only on Windows
        for root_dir, _, files in os.walk(tmp):
            for name in files:
                try:
                    os.chmod(Path(root_dir) / name, 0o666)
                except OSError:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)
    print("Collection audit generator regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
