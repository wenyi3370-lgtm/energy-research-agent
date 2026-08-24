from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from enterprise_energy_research.adapters.base import AdapterHealth, ArtifactResult
from enterprise_energy_research.artifacts.image_publication import (
    PublicationImage,
    prepare_publication_images,
    write_image_publication_manifest,
)
from enterprise_energy_research.artifacts.narrative import NarrativeBuilder
from enterprise_energy_research.artifacts.presentation_contract import build_presentation_contract
from enterprise_energy_research.artifacts.visuals import write_visual_manifest
from enterprise_energy_research.domain.enums import ArtifactType
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle
from enterprise_energy_research.vendor import embedded_skill_root


class PptMasterFrozenPublisher:
    """Adapter boundary for PPT Master.

    It prepares a deterministic 17-slide brief from the freeze. A configured executor owns
    SVG generation, preview, quality checking and PPTX export according to PPT Master's gates.
    """

    name = "ppt_master"
    artifact_type = ArtifactType.PPT

    def __init__(self, executor: Callable[[Path, Path], Path] | None = None, skill_root: Path | None = None) -> None:
        self.executor = executor
        self.skill_root = skill_root or embedded_skill_root("ppt-master")

    def health(self) -> AdapterHealth:
        required = (
            self.skill_root / "SKILL.md",
            self.skill_root / "scripts" / "svg_quality_checker.py",
            self.skill_root / "scripts" / "finalize_svg.py",
            self.skill_root / "scripts" / "svg_to_pptx.py",
            self.skill_root / "templates" / "design_spec_reference.md",
        )
        missing = [str(path.relative_to(self.skill_root)) for path in required if not path.is_file()]
        if missing:
            return AdapterHealth(
                name=self.name, available=False, version="embedded",
                diagnostics=["Embedded PPT Master resources are incomplete: " + ", ".join(missing)],
            )
        if self.executor is None:
            return AdapterHealth(
                name=self.name, available=False, version="embedded",
                diagnostics=["Embedded PPT Master is complete; generation still requires its blocking confirmation and render gates"],
            )
        return AdapterHealth(name=self.name, available=True, version="embedded")

    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult:
        if binding.type != self.artifact_type:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=["PPT publisher received a non-PPT binding"],
            )
        project_dir = output_path.parent / f"{output_path.stem}_ppt_master_project"
        project_dir.mkdir(parents=True, exist_ok=True)
        image_manifest = prepare_publication_images(
            bundle, binding, project_dir, extra_search_roots=[output_path.parent]
        )
        prepared_ids = set(image_manifest.prepared_image_ids)
        duplicate_ids = set(image_manifest.skipped_duplicate_image_ids)
        missing_image_ids = sorted(set(image_manifest.required_image_ids) - prepared_ids - duplicate_ids)
        fixture_mode = bundle.run_manifest.model_gateway.get("mode") in {
            "fixture", "recorded-fixture", "recorded-fixture-only",
        }
        brief_path = project_dir / "frozen_brief.json"
        brief = self.build_brief(bundle, binding, image_manifest.prepared_images)
        selected_ppt_image_ids = brief["presentation_evidence_map"]["required_verified_image_ids"]
        image_manifest = image_manifest.model_copy(update={"artifact_selections": {"ppt": selected_ppt_image_ids}})
        write_image_publication_manifest(image_manifest, project_dir)
        brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        narrative = NarrativeBuilder().build(bundle)
        write_visual_manifest(narrative.visual_manifest(), project_dir / "visual_manifest.json")
        (project_dir / "storyline.json").write_text(
            json.dumps({"freeze_id": bundle.freeze.freeze_id, "slides": brief["slides"]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (project_dir / "presentation_evidence_map.json").write_text(
            json.dumps(brief["presentation_evidence_map"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if missing_image_ids and not fixture_mode:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=[
                    "Verified evidence images are not publication-ready: " + ", ".join(missing_image_ids),
                    *image_manifest.diagnostics,
                    f"Frozen brief retained at {brief_path}",
                ],
                used_claim_ids=list(binding.claim_ids), used_image_ids=selected_ppt_image_ids,
            )
        health = self.health()
        if not health.available:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=[*health.diagnostics, f"Frozen brief retained at {brief_path}"],
                used_claim_ids=list(binding.claim_ids), used_image_ids=selected_ppt_image_ids,
            )
        produced = self.executor(project_dir, output_path)
        if produced.resolve() != output_path.resolve() or not output_path.is_file():
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=["PPT Master executor did not produce the requested PPTX"],
            )
        return ArtifactResult(
            adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
            path=output_path, content_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
            used_claim_ids=list(binding.claim_ids), used_image_ids=selected_ppt_image_ids, status="published",
        )

    @staticmethod
    def build_brief(
        bundle: FrozenResearchBundle,
        binding: ArtifactBinding,
        publication_images: list[PublicationImage] | None = None,
    ) -> dict[str, Any]:
        entity = next((x for x in bundle.entities if x.entity_id == bundle.run_manifest.canonical_entity_id), bundle.entities[0])
        claims = {x.claim_id: x.model_dump(mode="json") for x in bundle.claims if x.claim_id in binding.claim_ids}
        images = {x.image_id: x.model_dump(mode="json") for x in bundle.images if x.image_id in binding.image_ids}
        slide_specs, evidence_map = build_presentation_contract(bundle, binding, publication_images)
        return {
            "schema_version": "1.0",
            "freeze_id": bundle.freeze.freeze_id,
            "root_hash": bundle.freeze.root_hash,
            "canonical_entity": entity.model_dump(mode="json"),
            "design_direction": {
                "canvas": "16:9",
                "style": "answer-first top-consulting with restrained SEVC corporate identity",
                "cover": "deep navy-purple technology cover; left text and right verified hero image, or approved light typographic fallback",
                "body": "white consulting canvas, black text, thin rules, restrained purple/cobalt/cool-gray accents",
                "palette": ["#FFFFFF", "#000000", "#21122B", "#6F2B86", "#2563EB", "#6B7280", "#F4F1F5"],
                "title_font": "Georgia / Microsoft YaHei",
                "body_font": "Arial / Microsoft YaHei",
                "default_slide_count": 17,
                "image_policy": "verified images only; never synthesize or replace evidence images",
                "evidence_image_policy": "insert normalized local evidence images in their mapped chapters; preserve charts and add captions/sources",
                "chart_theme": "sevc-kami-broker-v2",
                "canvas_px": [1280, 720],
                "dense_page_columns_px": [290, 520, 290],
            },
            "quality_contract": {
                "formal_route": "embedded-pptmaster-svg-v1",
                "storyline_and_evidence_map_required": True,
                "answer_first_titles_required": True,
                "visual_element_required_on_every_slide": True,
                "source_date_bias_footer_required_on_substantive_slides": True,
                "minimum_layout_families": 4,
                "maximum_consecutive_same_layout": 2,
                "minimum_chart_font_pt": 8,
                "maximum_geometry_overlap_pt": 3,
                "token_aware_wrap_required": True,
                "kpi_unit_and_page_number_must_not_wrap": True,
                "minimum_effective_canvas_coverage_ratio": 0.6667,
                "all_selected_verified_images_must_be_embedded": True,
                "image_caption_and_source_required": True,
                "image_semantic_crop_prohibited": True,
                "minimum_visual_fix_and_full_rerender_cycles": 1,
                "all_slides_rendered_and_inspected": True,
                "contact_sheet_required": True,
                "prohibited": [
                    "text-only slides", "repetitive card grids", "emoji", "decorative color icons",
                    "unbound data graphics", "overflow", "clipping", "placeholder text",
                    "wrapped KPI units", "wrapped page numbers", "three consecutive identical layouts",
                ],
            },
            "slides": slide_specs,
            "presentation_evidence_map": evidence_map,
            "image_publication_manifest": "image_publication_manifest.json",
            "entities": [x.model_dump(mode="json") for x in bundle.entities],
            "factories": [x.model_dump(mode="json") for x in bundle.factories],
            "products": [x.model_dump(mode="json") for x in bundle.products],
            "claims": claims,
            "images": images,
            "energy_profiles": [x.model_dump(mode="json") for x in bundle.energy_profiles],
            "solutions": [x.model_dump(mode="json") for x in bundle.solutions],
            "gaps": [x.model_dump(mode="json") for x in bundle.gaps],
            "sources": [x.model_dump(mode="json") for x in bundle.sources],
        }
