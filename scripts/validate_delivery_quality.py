from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_energy_research.validation.delivery_quality import inspect_word_depth  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate enterprise-research delivery depth")
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--min-characters", type=int, default=15_000)
    parser.add_argument("--min-pages", type=int, default=30)
    parser.add_argument("--min-heading-1", type=int, default=13)
    parser.add_argument("--min-figures", type=int, default=13)
    parser.add_argument("--visual-manifest", type=Path)
    args = parser.parse_args()
    result = inspect_word_depth(
        args.docx,
        rendered_pdf=args.pdf,
        min_characters=args.min_characters,
        min_pages=args.min_pages,
        min_heading_1=args.min_heading_1,
        min_figures=args.min_figures,
        visual_manifest=args.visual_manifest,
    )
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
