from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

from validate_word_delivery import package_media_hashes
from figure_production import automated_visual_qa, enforce_figure_type_quota, visual_family
from render_figure_from_spec import infer_figure_type


SCRIPT_DIR = Path(__file__).resolve().parent


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], check=True)


def main() -> int:
    routing_cases = [
        ({"figure_type": "auto", "visual_intent": "composition", "encoding": {"category": "name", "value": "v"}}, "donut"),
        ({"figure_type": "bar", "title": "Sensitivity tornado", "encoding": {"category": "name", "value": "v"}}, "diverging-bar"),
        ({"figure_type": "auto", "encoding": {"date": "date", "label": "event"}}, "timeline"),
        ({"figure_type": "bar", "role": "decision", "encoding": {"category": "name", "value": "v"}}, "lollipop"),
    ]
    for spec, expected in routing_cases:
        actual = infer_figure_type(spec, [{"name": "A", "v": "1", "date": "2026", "event": "Launch"}])
        if actual != expected:
            raise AssertionError(f"Semantic routing failed: expected {expected}, got {actual}")
    if len({visual_family(name) for name in ("bar", "ranking-bar", "grouped-bar", "lollipop", "dot-plot")}) != 1:
        raise AssertionError("Visually similar single-axis comparison grammars were not grouped")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    qa_fig, qa_ax = plt.subplots(figsize=(6.2, 4.0))
    qa_ax.plot([0, 1], [0, 1])
    qa_ax.set_xlabel("Deterministic QA")
    visual_report = automated_visual_qa(qa_fig)
    plt.close(qa_fig)
    if visual_report["status"] != "passed" or not visual_report["text_only_model_safe"]:
        raise AssertionError(f"Deterministic text-only visual QA failed: {visual_report}")
    with tempfile.TemporaryDirectory(prefix="figure_delivery_regression_") as temp_dir:
        root = Path(temp_dir)
        quota_dir = root / "quota_fixture"
        quota_dir.mkdir()
        for index in (1, 2):
            (quota_dir / f"fig{index}_line.theme.json").write_text(
                json.dumps({"figure_contract": {"figure_type": "trend-line"}}),
                encoding="utf-8",
            )
        try:
            enforce_figure_type_quota(quota_dir, "line")
        except ValueError as exc:
            if "at most 2" not in str(exc):
                raise
        else:
            raise AssertionError("Third chart of the same canonical type was not blocked")
        write_csv(
            root / "01_Market_Scan.csv",
            ["metric", "year_period", "raw_value", "currency", "market_segment"],
            [
                {"metric": "market_size", "year_period": year, "raw_value": value, "currency": "EUR m", "market_segment": "fixture"}
                for year, value in [(2024, 100), (2025, 118), (2026, 139)]
            ],
        )
        write_csv(
            root / "04_Product_Parameters.csv",
            ["exact_model", "brand", "parameter_name"],
            [
                {"exact_model": model, "brand": model[0], "parameter_name": parameter}
                for model, parameter in [("A1", "capacity"), ("A1", "power"), ("B2", "capacity"), ("B2", "pv")]
            ],
        )
        write_csv(
            root / "05_Pricing_Channel.csv",
            ["exact_model", "brand", "channel"],
            [
                {"exact_model": model, "brand": model[0], "channel": channel}
                for model, channel in [("A1", "retail"), ("A1", "direct"), ("B2", "retail"), ("C3", "installer")]
            ],
        )
        write_csv(
            root / "08_Review_Coding.csv",
            ["theme", "frequency_count"],
            [
                {"theme": "installation", "frequency_count": 18},
                {"theme": "noise", "frequency_count": 11},
                {"theme": "app", "frequency_count": 8},
                {"theme": "support", "frequency_count": 5},
            ],
        )
        write_csv(
            root / "09_Integrated_Matrix.csv",
            ["exact_model", "brand", "capacity_kwh", "price", "power_kw", "pv_input_w", "user_pain_score"],
            [
                {"exact_model": "A1", "brand": "A", "capacity_kwh": 2.0, "price": 1200, "power_kw": 2.4, "pv_input_w": 800, "user_pain_score": 0.72},
                {"exact_model": "B2", "brand": "B", "capacity_kwh": 3.0, "price": 1550, "power_kw": 3.0, "pv_input_w": 1000, "user_pain_score": 0.61},
                {"exact_model": "C3", "brand": "C", "capacity_kwh": 1.5, "price": 980, "power_kw": 1.8, "pv_input_w": 600, "user_pain_score": 0.84},
            ],
        )
        chart_names = [
            "market_trend",
            "price_capacity_scatter",
            "parameter_availability_heatmap",
            "channel_coverage_heatmap",
            "pain_point_pareto",
            "capability_radar",
        ]
        claims = {
            name: {"core_claim": f"Confirmed fixture claim for {name}.", "claim_confirmed": True}
            for name in chart_names
        }
        (root / "claims.json").write_text(json.dumps(claims, indent=2), encoding="utf-8")
        run(
            str(SCRIPT_DIR / "render_charts.py"),
            "--project-dir",
            str(root),
            "--claim-registry",
            "claims.json",
            "--mode",
            "final",
        )
        manifests = sorted((root / "deliverables/charts").glob("*.theme.json"))
        if len(manifests) != 6:
            raise AssertionError(f"Expected six market manifests, got {len(manifests)}")
        for manifest in manifests:
            run(
                str(SCRIPT_DIR / "register_figure_delivery.py"),
                str(manifest),
                "--project-dir",
                str(root),
                "--confirm-visual-inspected",
            )
        run(
            str(SCRIPT_DIR / "validate_figure_delivery.py"),
            str(root / "deliverables/charts"),
            "--project-dir",
            str(root),
            "--mode",
            "final",
        )

        write_csv(
            root / "14_Simulated_Modeling_Data.csv",
            ["parameter_value", "model_result", "lower", "upper"],
            [
                {"parameter_value": value, "model_result": result, "lower": result - 2, "upper": result + 2}
                for value, result in [(-10, 91), (-5, 94), (0, 96), (5, 95), (10, 92)]
            ],
        )
        modeling_spec = {
            "figure_id": "model_sensitivity",
            "title": "Model sensitivity",
            "figure_class": "modeling",
            "figure_type": "sensitivity",
            "archetype": "single-evidence-chart",
            "role": "robustness",
            "core_claim": "The calibrated model remains stable under a plus or minus ten percent perturbation.",
            "claim_confirmed": True,
            "panel_map": {"a": "Sensitivity of the calibrated result to the tested parameter."},
            "source_data": "14_Simulated_Modeling_Data.csv",
            "data_provenance": "simulated",
            "simulation": {
                "method": "bounded deterministic scenario simulation calibrated to observed endpoints",
                "seed": 20260809,
                "assumptions": ["monotonic response around the calibrated optimum"],
                "calibration_sources": ["fixture-observed-endpoints"],
            },
            "statistics": {
                "metric_definition": "normalized model score",
                "variability_definition": "scenario lower and upper bounds",
                "baseline_definition": "zero-percent perturbation",
            },
            "encoding": {
                "x": "parameter_value",
                "series": ["model_result"],
                "lower": {"model_result": "lower"},
                "upper": {"model_result": "upper"},
                "xlabel": "Parameter perturbation (%)",
                "ylabel": "Model result",
            },
            "figsize": [6.1417, 4.2],
            "dpi": 300,
            "minimum_font_size_pt": 8,
            "report_placement": {
                "section_heading": "十、经济性、数学模型与敏感性",
                "caption": "Model sensitivity",
                "source_note": "Data source: 14_Simulated_Modeling_Data.csv.",
            },
            "output_stem": "deliverables/charts/fig7_model_sensitivity",
        }
        spec_path = root / "modeling_figure_spec.json"
        spec_path.write_text(json.dumps(modeling_spec, indent=2), encoding="utf-8")
        run(
            str(SCRIPT_DIR / "render_figure_from_spec.py"),
            "--project-dir",
            str(root),
            "--spec",
            str(spec_path),
            "--mode",
            "final",
        )
        model_manifest = root / "deliverables/charts/fig7_model_sensitivity.theme.json"
        run(
            str(SCRIPT_DIR / "register_figure_delivery.py"),
            str(model_manifest),
            "--project-dir",
            str(root),
            "--confirm-visual-inspected",
        )
        run(
            str(SCRIPT_DIR / "validate_figure_delivery.py"),
            str(model_manifest),
            "--project-dir",
            str(root),
            "--mode",
            "final",
        )

        template = SCRIPT_DIR.parent / "assets/templates/word/energy_market_research_report_template.docx"
        narrative_docx = root / "narrative_complete.docx"
        doc = Document(template)
        paragraph_counts = {
            "四、市场规模、细分、产业链与增长情景": 1,
            "六、产品系统架构、工程参数与区域合规": 1,
            "七、竞争格局、玩家分类与精确型号对标": 2,
            "八、定价、渠道、安装与服务网络": 1,
            "九、原始评论、用户痛点与购买驱动": 1,
            "十、经济性、数学模型与敏感性": 1,
        }
        for heading in list(doc.paragraphs):
            count = paragraph_counts.get(heading.text.strip(), 0)
            anchor = heading._p
            for index in range(count):
                new_element = OxmlElement("w:p")
                anchor.addnext(new_element)
                paragraph = Paragraph(new_element, heading._parent)
                paragraph.style = doc.styles["Normal"]
                paragraph.add_run(
                    f"Fixture analytical paragraph {index + 1}: "
                    + "This evidence-backed paragraph is intentionally long enough to carry a unique figure claim and its inline reference. " * 2
                )
                anchor = new_element
        doc.save(narrative_docx)
        integrated_docx = root / "narrative_with_figures.docx"
        run(
            str(SCRIPT_DIR / "insert_approved_figures.py"),
            str(narrative_docx),
            "--charts-dir",
            str(root / "deliverables/charts"),
            "--out",
            str(integrated_docx),
            "--mode",
            "final",
        )
        integrated = Document(integrated_docx)
        if len(integrated.inline_shapes) != 7:
            raise AssertionError(f"Expected seven embedded figures, got {len(integrated.inline_shapes)}")
        media_hashes = package_media_hashes(integrated_docx)
        for manifest_path in sorted((root / "deliverables/charts").glob("fig*.theme.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            png_hash = manifest["outputs"]["png"]["sha256"]
            if png_hash not in media_hashes:
                raise AssertionError(f"Approved PNG was not embedded unchanged: {manifest_path.name}")
    print("Figure delivery regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
