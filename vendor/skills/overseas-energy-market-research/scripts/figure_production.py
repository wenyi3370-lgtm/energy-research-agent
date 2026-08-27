from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from kami_broker_chart_theme import (
    THEME_ID,
    apply_kami_broker_theme,
    apply_mixed_text_fonts,
    style_axes,
)


FIGURE_PIPELINE_ID = "embedded-figure-production-v1"
OWNER_BY_CLASS = {
    "market-insight": "embedded-market-figure-v1",
    "modeling": "embedded-modeling-figure-v1",
}
ALLOWED_ARCHETYPES = {
    "quantitative-grid",
    "schematic-led-composite",
    "image-plate-quant",
    "asymmetric-mixed-modality",
    "single-evidence-chart",
}
ALLOWED_ROLES = {
    "discovery",
    "mechanism",
    "validation",
    "comparison",
    "robustness",
    "decision",
}
BAR_FIGURE_TYPES = {"bar", "ranking-bar", "grouped-bar", "diverging-bar"}
FIGURE_TYPE_LIMIT = 2
VISUAL_FAMILY_LIMIT = 4
FIGURE_TYPE_ALIASES = {
    "trend-line": "line",
    "bar_line": "line",
    "scatter-positioning": "scatter",
    "coverage-heatmap": "heatmap",
    "evaluation-ranking": "pareto",
    "evaluation-comparison": "radar",
}
VISUAL_FAMILY_BY_TYPE = {
    "bar": "single-axis-comparison",
    "ranking-bar": "single-axis-comparison",
    "grouped-bar": "single-axis-comparison",
    "lollipop": "single-axis-comparison",
    "dot-plot": "single-axis-comparison",
    "diverging-bar": "variance-and-risk",
    "risk-tiles": "variance-and-risk",
    "risk-matrix": "variance-and-risk",
    "line": "time-and-change",
    "timeline": "time-and-change",
    "scenario-range": "scenario-and-uncertainty",
    "waterfall": "scenario-and-uncertainty",
    "donut": "composition",
    "funnel": "composition",
    "pareto": "frequency-and-priority",
    "heatmap": "matrix",
    "radar": "matrix",
    "scatter": "positioning",
    "bubble-ranking": "positioning",
    "kpi-cards": "information-design",
    "scorecards": "information-design",
    "decision-cards": "information-design",
    "rating-tiles": "information-design",
}
CLAIM_SENTINELS = ("[AI-DRAFT", "[MODELER INPUT NEEDED", "<<<HUMAN>>>")


def canonical_figure_type(value: object) -> str:
    figure_type = str(value or "").strip().lower()
    return FIGURE_TYPE_ALIASES.get(figure_type, figure_type)


def visual_family(value: object) -> str:
    figure_type = canonical_figure_type(value)
    return VISUAL_FAMILY_BY_TYPE.get(figure_type, figure_type or "unknown")


def enforce_figure_type_quota(
    output_dir: str | Path,
    figure_type: str,
    *,
    current_manifest: str | Path | None = None,
    limit: int = FIGURE_TYPE_LIMIT,
) -> None:
    """Block a third chart with the same visual grammar in a formal set."""
    target = canonical_figure_type(figure_type)
    current = Path(current_manifest).resolve() if current_manifest else None
    matches = []
    for manifest_path in Path(output_dir).resolve().glob("fig*.theme.json"):
        if current is not None and manifest_path.resolve() == current:
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        existing = canonical_figure_type((data.get("figure_contract") or {}).get("figure_type"))
        if existing == target:
            matches.append(manifest_path.name)
    if len(matches) >= limit:
        raise ValueError(
            f"Figure type quota exceeded for {target!r}: already {len(matches)} formal figures "
            f"({', '.join(matches[:limit])}); each type may appear at most {limit} times. "
            "Choose a different evidence relationship and visual grammar."
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stored_path(path: Path, project_dir: Path | None) -> str:
    resolved = path.resolve()
    if project_dir is not None:
        try:
            return str(resolved.relative_to(project_dir.resolve()))
        except ValueError:
            pass
    return str(resolved)


def png_metadata(path: Path) -> dict[str, float | int | None]:
    width = height = None
    dpi_x = dpi_y = None
    with path.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Not a PNG file: {path}")
        while True:
            raw_length = handle.read(4)
            if len(raw_length) != 4:
                break
            length = struct.unpack(">I", raw_length)[0]
            kind = handle.read(4)
            payload = handle.read(length)
            handle.read(4)
            if kind == b"IHDR":
                width, height = struct.unpack(">II", payload[:8])
            elif kind == b"pHYs" and len(payload) >= 9:
                x_ppm, y_ppm, unit = struct.unpack(">IIB", payload[:9])
                if unit == 1:
                    dpi_x = x_ppm * 0.0254
                    dpi_y = y_ppm * 0.0254
            elif kind == b"IEND":
                break
    return {
        "width_px": width,
        "height_px": height,
        "dpi_x": round(dpi_x, 2) if dpi_x is not None else None,
        "dpi_y": round(dpi_y, 2) if dpi_y is not None else None,
    }


def svg_metadata(path: Path) -> dict[str, object]:
    root = ElementTree.parse(path).getroot()
    texts = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "text"]
    font_markers = 0
    for node in texts:
        serialized = ElementTree.tostring(node, encoding="unicode")
        if "font-family" in serialized or re.search(r"(?:^|;)\s*font\s*:", serialized):
            font_markers += 1
    return {
        "editable_text_nodes": len(texts),
        "text_nodes_with_font": font_markers,
        "width": root.attrib.get("width", ""),
        "height": root.attrib.get("height", ""),
        "view_box": root.attrib.get("viewBox", ""),
    }


def _visible_text_artists(fig) -> list:
    artists = []
    seen: set[int] = set()
    for ax in fig.get_axes():
        candidates = [
            ax.title,
            ax.xaxis.label,
            ax.yaxis.label,
            *ax.texts,
            *ax.get_xticklabels(),
            *ax.get_yticklabels(),
        ]
        legend = ax.get_legend()
        if legend is not None:
            candidates.extend(legend.get_texts())
        for artist in candidates:
            if id(artist) in seen or not artist.get_visible() or not (artist.get_text() or "").strip():
                continue
            seen.add(id(artist))
            artists.append(artist)
    return artists


def mechanical_render_check(fig, *, min_font_size_pt: float = 7.0) -> dict[str, object]:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    tight_bbox = fig.get_tightbbox(renderer)
    issues: list[dict[str, object]] = []
    text_count = 0
    min_seen: float | None = None
    for artist in _visible_text_artists(fig):
        text_count += 1
        size = float(artist.get_fontsize())
        min_seen = size if min_seen is None else min(min_seen, size)
        if size + 1e-6 < min_font_size_pt:
            issues.append(
                {
                    "kind": "font_too_small",
                    "text": (artist.get_text() or "")[:80],
                    "font_size_pt": round(size, 2),
                    "minimum_pt": min_font_size_pt,
                }
            )
        bbox = artist.get_window_extent(renderer=renderer)
        if not all(map(lambda value: value == value and abs(value) != float("inf"), bbox.extents)):
            issues.append({"kind": "invalid_text_bbox", "text": (artist.get_text() or "")[:80]})
    if tight_bbox.width <= 0 or tight_bbox.height <= 0:
        issues.append({"kind": "invalid_tight_bbox"})
    return {
        "status": "passed" if not issues else "failed",
        "minimum_font_size_pt": min_font_size_pt,
        "minimum_observed_font_size_pt": round(min_seen, 2) if min_seen is not None else None,
        "text_artist_count": text_count,
        "issues": issues,
    }


def automated_visual_qa(fig) -> dict[str, object]:
    """Deterministic geometry QA for models that cannot inspect images.

    This does not pretend that a text-only model has vision. It checks the
    rendered canvas itself: text overflow, material text collisions, invalid
    canvas geometry, excessive label density and degenerate aspect ratios.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    issues: list[dict[str, object]] = []
    boxes = []
    hidden_tick_ids = {
        id(tick)
        for ax in fig.get_axes()
        if not ax.axison
        for tick in (*ax.get_xticklabels(), *ax.get_yticklabels())
    }
    for artist in _visible_text_artists(fig):
        if id(artist) in hidden_tick_ids:
            continue
        text = (artist.get_text() or "").strip()
        if not text:
            continue
        bbox = artist.get_window_extent(renderer=renderer)
        if bbox.width <= 0 or bbox.height <= 0:
            continue
        overflow = max(canvas.x0 - bbox.x0, canvas.y0 - bbox.y0, bbox.x1 - canvas.x1, bbox.y1 - canvas.y1, 0)
        # Small tick-label overhang is normal and is retained by bbox_inches=tight.
        # Material overflow remains a hard failure.
        # SVG/PNG are saved with bbox_inches=tight, which deliberately retains
        # ordinary tick-label overhang. Extreme overflow remains a failure.
        if overflow > 80:
            issues.append({"kind": "text_out_of_bounds", "text": text[:80], "overflow_px": round(overflow, 1)})
        boxes.append((artist, text, bbox))
    # Only count substantial collisions. Tiny edge contacts and artists on
    # different axes are ignored to avoid false positives around tick labels.
    collisions = []
    for index, (left_artist, left_text, left) in enumerate(boxes):
        left_axes = getattr(left_artist, "axes", None)
        for right_artist, right_text, right in boxes[index + 1 :]:
            if left_axes is not getattr(right_artist, "axes", None):
                continue
            overlap_w = min(left.x1, right.x1) - max(left.x0, right.x0)
            overlap_h = min(left.y1, right.y1) - max(left.y0, right.y0)
            if overlap_w <= 3 or overlap_h <= 3:
                continue
            overlap_area = overlap_w * overlap_h
            smaller = min(left.width * left.height, right.width * right.height)
            if overlap_area / max(1.0, smaller) >= 0.28:
                collisions.append({"left": left_text[:50], "right": right_text[:50]})
    if collisions:
        issues.append({"kind": "material_text_overlap", "count": len(collisions), "examples": collisions[:5]})
    width, height = fig.get_size_inches()
    ratio = width / max(height, 1e-6)
    if ratio < 1.05 or ratio > 2.4:
        issues.append({"kind": "degenerate_aspect_ratio", "ratio": round(ratio, 3)})
    if len(boxes) > 45:
        issues.append({"kind": "excessive_text_density", "text_artist_count": len(boxes), "maximum": 45})
    return {
        "status": "passed" if not issues else "failed",
        "deterministic": True,
        "text_only_model_safe": not issues,
        "text_artist_count": len(boxes),
        "material_text_overlap_count": len(collisions),
        "issues": issues,
    }


def _validate_contract(
    *,
    figure_id: str,
    core_claim: str,
    claim_confirmed: bool,
    figure_class: str,
    archetype: str,
    role: str,
    panel_map: dict[str, str],
    data_provenance: str,
    simulation: dict[str, object] | None,
    final: bool,
) -> None:
    if not figure_id.strip():
        raise ValueError("figure_id is required")
    if figure_class not in OWNER_BY_CLASS:
        raise ValueError("figure_class must be market-insight or modeling")
    if archetype not in ALLOWED_ARCHETYPES:
        raise ValueError(f"Unsupported figure archetype: {archetype}")
    if role not in ALLOWED_ROLES:
        raise ValueError(f"Unsupported figure role: {role}")
    if not core_claim.strip():
        raise ValueError("Every figure requires a one-sentence core claim")
    if not panel_map or any(not str(value).strip() for value in panel_map.values()):
        raise ValueError("Every figure requires a non-empty panel map")
    if final and (not claim_confirmed or any(token in core_claim for token in CLAIM_SENTINELS)):
        raise ValueError("Final figures require a confirmed core claim without decision sentinels")
    if data_provenance not in {"observed", "calculated", "simulated"}:
        raise ValueError("data_provenance must be observed, calculated, or simulated")
    if figure_class == "market-insight" and data_provenance == "simulated":
        raise ValueError("Market-insight figures may not fill market evidence gaps with simulated data")
    if data_provenance == "simulated":
        required = {"method", "seed", "assumptions", "calibration_sources"}
        missing = sorted(required - set(simulation or {}))
        if missing:
            raise ValueError("Simulated modeling figures require: " + ", ".join(missing))


def save_figure_bundle(
    fig,
    output_stem: str | Path,
    *,
    project_dir: str | Path | None,
    figure_id: str,
    title: str,
    figure_class: str,
    figure_type: str,
    archetype: str,
    role: str,
    core_claim: str,
    claim_confirmed: bool,
    panel_map: dict[str, str],
    source_data_paths: Iterable[str | Path],
    data_provenance: str,
    statistics: dict[str, object] | None = None,
    simulation: dict[str, object] | None = None,
    report_placement: dict[str, object] | None = None,
    generator_script: str | Path | None = None,
    dpi: int = 300,
    min_font_size_pt: float = 8.0,
    final: bool = False,
) -> Path:
    _validate_contract(
        figure_id=figure_id,
        core_claim=core_claim,
        claim_confirmed=claim_confirmed,
        figure_class=figure_class,
        archetype=archetype,
        role=role,
        panel_map=panel_map,
        data_provenance=data_provenance,
        simulation=simulation,
        final=final,
    )
    if dpi < 300:
        raise ValueError("Formal figure PNG output must be at least 300 dpi")
    placement = report_placement or {}
    if final and not all(str(placement.get(key) or "").strip() for key in ("section_heading", "caption", "source_note")):
        raise ValueError("Final figures require section_heading, caption, and source_note placement metadata")
    root = Path(project_dir).resolve() if project_dir is not None else None
    sources = [Path(path).expanduser().resolve() for path in source_data_paths]
    if not sources:
        raise ValueError("Every figure requires at least one source-data file")
    missing_sources = [str(path) for path in sources if not path.exists()]
    if missing_sources:
        raise FileNotFoundError("Missing figure source data: " + ", ".join(missing_sources))

    apply_kami_broker_theme()
    fig.set_facecolor("white")
    for ax in fig.get_axes():
        ax.set_facecolor("white")
        style_axes(ax)
    apply_mixed_text_fonts(fig)
    render_check = mechanical_render_check(fig, min_font_size_pt=min_font_size_pt)
    if render_check["status"] != "passed":
        raise ValueError("Figure mechanical render check failed: " + json.dumps(render_check["issues"], ensure_ascii=False))
    visual_qa = automated_visual_qa(fig)
    if final and visual_qa["status"] != "passed":
        raise ValueError("Figure automated visual QA failed: " + json.dumps(visual_qa["issues"], ensure_ascii=False))

    stem = Path(output_stem).expanduser().resolve().with_suffix("")
    if final and not re.match(r"^fig\d+_", stem.name, flags=re.IGNORECASE):
        raise ValueError("Final figure filenames must follow figN_*.svg/png naming")
    stem.parent.mkdir(parents=True, exist_ok=True)
    svg_path = stem.with_suffix(".svg")
    png_path = stem.with_suffix(".png")
    manifest_path = stem.with_suffix(".theme.json")
    if final:
        enforce_figure_type_quota(
            stem.parent,
            figure_type,
            current_manifest=manifest_path,
        )
        target_family = visual_family(figure_type)
        family_matches = []
        for existing_path in stem.parent.glob("fig*.theme.json"):
            if existing_path.resolve() == manifest_path.resolve():
                continue
            try:
                existing_data = json.loads(existing_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            existing_type = (existing_data.get("figure_contract") or {}).get("figure_type")
            if visual_family(existing_type) == target_family:
                family_matches.append(existing_path.name)
        if len(family_matches) >= VISUAL_FAMILY_LIMIT:
            raise ValueError(
                f"Visual-family quota exceeded for {target_family!r}: already {len(family_matches)} formal figures "
                f"({', '.join(family_matches[:VISUAL_FAMILY_LIMIT])}); visually similar grammars may appear at most "
                f"{VISUAL_FAMILY_LIMIT} times. Choose a genuinely different relationship and layout."
            )
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor="white", transparent=False)

    svg_info = svg_metadata(svg_path)
    png_info = png_metadata(png_path)
    if svg_info["editable_text_nodes"] <= 0:
        raise ValueError(f"SVG contains no editable text nodes: {svg_path}")
    if svg_info["text_nodes_with_font"] <= 0:
        raise ValueError(f"SVG text has no explicit font styling: {svg_path}")
    if min(png_info.get("dpi_x") or 0, png_info.get("dpi_y") or 0) < 295:
        raise ValueError(f"PNG DPI metadata is below the 300-dpi contract: {png_info}")

    script_path = Path(generator_script).resolve() if generator_script else Path(__file__).resolve()
    manifest = {
        "schema_version": 1,
        "figure_pipeline_id": FIGURE_PIPELINE_ID,
        "theme_id": THEME_ID,
        "figure_id": figure_id,
        "title": title,
        "figure_owner": OWNER_BY_CLASS[figure_class],
        "figure_class": figure_class,
        "backend": "python",
        "figure_contract": {
            "core_claim": core_claim,
            "claim_confirmed": bool(claim_confirmed),
            "figure_type": figure_type,
            "visual_family": visual_family(figure_type),
            "archetype": archetype,
            "role": role,
            "panel_map": panel_map,
            "statistics": statistics or {},
            "reviewer_risks": [],
            "semantic_selection": {
                "relationship_driven": True,
                "generic_bar": figure_type == "bar",
            },
        },
        "data_provenance": data_provenance,
        "simulation": simulation or {},
        "source_data": [
            {"path": stored_path(path, root), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in sources
        ],
        "generator": {
            "path": stored_path(script_path, root),
            "sha256": sha256(script_path),
        },
        "figure_size_inches": [round(float(value), 4) for value in fig.get_size_inches()],
        "outputs": {
            "svg": {
                "path": stored_path(svg_path, root),
                "sha256": sha256(svg_path),
                **svg_info,
            },
            "png": {
                "path": stored_path(png_path, root),
                "sha256": sha256(png_path),
                **png_info,
            },
        },
        "qa": {
            "mechanical_render_check": render_check,
            "automated_visual_qa": visual_qa,
            "svg_editable_text": True,
            "png_minimum_dpi": 300,
            "visual_inspection": {
                "status": "not_run",
                "inspector_confirmed": False,
                "issues": [],
            },
        },
        "word_placement": {
            "layout": "inline",
            "paragraph_style": "Figure Image",
            "alignment": "center",
            "max_width_cm": 15.6,
            **placement,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _resolve_record_path(raw_path: object, manifest_path: Path, project_dir: Path | None) -> Path:
    path = Path(str(raw_path or ""))
    if path.is_absolute():
        return path
    if project_dir is not None:
        candidate = project_dir / path
        if candidate.exists():
            return candidate
    return manifest_path.parent / path


def validate_figure_manifest(
    manifest_path: str | Path,
    *,
    project_dir: str | Path | None = None,
    final: bool = True,
) -> list[dict[str, str]]:
    path = Path(manifest_path).resolve()
    root = Path(project_dir).resolve() if project_dir is not None else None
    issues: list[dict[str, str]] = []

    def add(level: str, field: str, message: str) -> None:
        issues.append({"level": level, "field": field, "message": message})

    if not path.exists():
        return [{"level": "fail", "field": "manifest", "message": f"Missing figure manifest: {path}"}]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return [{"level": "fail", "field": "manifest", "message": f"Invalid JSON: {exc}"}]

    if manifest.get("figure_pipeline_id") != FIGURE_PIPELINE_ID:
        add("fail", "figure_pipeline_id", f"Expected {FIGURE_PIPELINE_ID}")
    figure_class = manifest.get("figure_class")
    if figure_class not in OWNER_BY_CLASS:
        add("fail", "figure_class", "Expected market-insight or modeling")
    elif manifest.get("figure_owner") != OWNER_BY_CLASS[figure_class]:
        add("fail", "figure_owner", f"Expected {OWNER_BY_CLASS[figure_class]}")
    if manifest.get("backend") != "python":
        add("fail", "backend", "Embedded figure backend must be python")
    if manifest.get("theme_id") != THEME_ID:
        add("fail", "theme_id", f"Expected {THEME_ID}")

    contract = manifest.get("figure_contract") or {}
    claim = str(contract.get("core_claim") or "")
    confirmed = bool(contract.get("claim_confirmed"))
    if not claim:
        add("fail", "figure_contract.core_claim", "Core claim is required")
    if final and (not confirmed or any(token in claim for token in CLAIM_SENTINELS)):
        add("fail", "figure_contract.claim_confirmed", "Final figures require a confirmed claim")
    if contract.get("archetype") not in ALLOWED_ARCHETYPES:
        add("fail", "figure_contract.archetype", "Unsupported or missing archetype")
    if contract.get("role") not in ALLOWED_ROLES:
        add("fail", "figure_contract.role", "Unsupported or missing role")
    if not contract.get("panel_map"):
        add("fail", "figure_contract.panel_map", "Panel map is required")
    placement = manifest.get("word_placement") or {}
    if final:
        for key in ("section_heading", "caption", "source_note"):
            if not str(placement.get(key) or "").strip():
                add("fail", f"word_placement.{key}", "Required for final report placement")

    provenance = manifest.get("data_provenance")
    if figure_class == "market-insight" and provenance == "simulated":
        add("fail", "data_provenance", "Market evidence gaps cannot be filled with simulated data")
    if provenance == "simulated":
        simulation = manifest.get("simulation") or {}
        for key in ("method", "seed", "assumptions", "calibration_sources"):
            if key not in simulation:
                add("fail", f"simulation.{key}", "Required for realistic simulated modeling data")

    for index, source in enumerate(manifest.get("source_data") or []):
        source_path = _resolve_record_path(source.get("path"), path, root)
        if not source_path.exists():
            add("fail", f"source_data[{index}].path", f"Missing source data: {source_path}")
        elif sha256(source_path) != source.get("sha256"):
            add("fail", f"source_data[{index}].sha256", "Source-data hash mismatch")
    if not manifest.get("source_data"):
        add("fail", "source_data", "At least one source-data file is required")

    generator = manifest.get("generator") or {}
    generator_path = _resolve_record_path(generator.get("path"), path, root)
    if not generator_path.exists():
        add("fail", "generator.path", f"Missing generator script: {generator_path}")
    elif sha256(generator_path) != generator.get("sha256"):
        add("fail", "generator.sha256", "Generator-script hash mismatch")

    outputs = manifest.get("outputs") or {}
    for kind in ("svg", "png"):
        record = outputs.get(kind) or {}
        output_path = _resolve_record_path(record.get("path"), path, root)
        if not output_path.exists():
            add("fail", f"outputs.{kind}.path", f"Missing {kind.upper()} output: {output_path}")
            continue
        if sha256(output_path) != record.get("sha256"):
            add("fail", f"outputs.{kind}.sha256", f"{kind.upper()} hash mismatch")
        try:
            metadata = svg_metadata(output_path) if kind == "svg" else png_metadata(output_path)
            if kind == "svg" and metadata["editable_text_nodes"] <= 0:
                add("fail", "outputs.svg.editable_text_nodes", "SVG text is not editable")
            if kind == "png" and min(metadata.get("dpi_x") or 0, metadata.get("dpi_y") or 0) < 295:
                add("fail", "outputs.png.dpi", "PNG is below the 300-dpi contract")
        except Exception as exc:
            add("fail", f"outputs.{kind}.metadata", str(exc))
        if final and not re.match(r"^fig\d+_", output_path.stem, flags=re.IGNORECASE):
            add("fail", f"outputs.{kind}.path", "Final figure filename must follow figN_* naming")

    mechanical = ((manifest.get("qa") or {}).get("mechanical_render_check") or {})
    if mechanical.get("status") != "passed" or mechanical.get("issues"):
        add("fail", "qa.mechanical_render_check", "Mechanical render check did not pass")
    visual = ((manifest.get("qa") or {}).get("visual_inspection") or {})
    automated = ((manifest.get("qa") or {}).get("automated_visual_qa") or {})
    human_passed = visual.get("status") == "passed" and visual.get("inspector_confirmed")
    automated_passed = (
        automated.get("status") == "passed"
        and automated.get("deterministic") is True
        and automated.get("text_only_model_safe") is True
        and not automated.get("issues")
    )
    if final and not (human_passed or automated_passed):
        add("fail", "qa.visual_qa", "Final figure requires passed human inspection or deterministic text-only visual QA")
    return issues
