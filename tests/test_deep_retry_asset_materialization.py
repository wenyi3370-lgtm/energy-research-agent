"""Deep-research (t3) carried-over image byte materialization.

Production runs archive image bytes under ``run_dir/outputs/01_evidence/assets``
while publication resolves ``local_asset_ref`` only against the CURRENT publish
tree. Continuing such a run via deep_retry must copy the historical bytes into
the new output dir, otherwise every carried-over verified image dangles and the
product-image gate blocks publication (same failure class fixed for the
unified t1 publication by ``_materialize_source_assets``).
"""

from pathlib import Path

from enterprise_energy_research.domain.models import ImageEvidence
from enterprise_energy_research.research.deep_retry import (
    _materialize_source_image_assets,
)
from enterprise_energy_research.research.normalizer import NormalizedEvidence


def _image(image_id: str, reference: str | None) -> ImageEvidence:
    return ImageEvidence(
        image_id=image_id,
        source_url="https://official.example.com/products",
        source_page_url="https://official.example.com/products",
        source_id="SOURCE-TEST",
        source_domain="official.example.com",
        image_type="product",
        sha256="0" * 64,
        phash="f" * 16,
        width=640,
        height=480,
        mime_type="image/png",
        confidence=0.9,
        local_asset_ref=reference,
    )


def _write_assets(root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        path = root / "assets" / "images" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bytes-of-" + name.encode())


def test_materializes_production_layout_bytes(tmp_path: Path) -> None:
    previous_run = tmp_path / "previous_run"
    store_path = previous_run / "evidence.sqlite3"
    _write_assets(previous_run / "outputs" / "01_evidence", ("a.png", "b.png"))
    output_dir = tmp_path / "current_run"
    output_dir.mkdir()
    evidence = NormalizedEvidence()
    evidence.images = [
        _image("IMAGE-A", "assets/images/a.png"),
        _image("IMAGE-B", "assets/images/b.png"),
    ]

    summary = _materialize_source_image_assets(evidence, output_dir, store_path)

    assert summary == {"copied": 2, "resolved": 2, "unresolved": 0}
    assert (output_dir / "assets" / "images" / "a.png").read_bytes() == b"bytes-of-a.png"
    assert (output_dir / "assets" / "images" / "b.png").read_bytes() == b"bytes-of-b.png"
    # Refs keep their original relative form; publish-tree resolution finds them.
    assert [image.local_asset_ref for image in evidence.images] == [
        "assets/images/a.png",
        "assets/images/b.png",
    ]


def test_materialization_is_idempotent(tmp_path: Path) -> None:
    previous_run = tmp_path / "previous_run"
    _write_assets(previous_run / "outputs" / "01_evidence", ("a.png",))
    output_dir = tmp_path / "current_run"
    output_dir.mkdir()
    evidence = NormalizedEvidence()
    evidence.images = [_image("IMAGE-A", "assets/images/a.png")]

    first = _materialize_source_image_assets(evidence, output_dir, previous_run / "evidence.sqlite3")
    second = _materialize_source_image_assets(evidence, output_dir, previous_run / "evidence.sqlite3")

    assert first["copied"] == 1
    assert second == {"copied": 0, "resolved": 1, "unresolved": 0}


def test_earlier_deep_round_layout_and_existing_files(tmp_path: Path) -> None:
    # An earlier deep-research round archives directly into its own output dir
    # (no outputs/01_evidence layer).
    previous_store = tmp_path / "previous" / "evidence_fixed.sqlite3"
    _write_assets(tmp_path / "previous", ("c.png",))
    output_dir = tmp_path / "current_run"
    (output_dir / "assets" / "images").mkdir(parents=True)
    (output_dir / "assets" / "images" / "d.png").write_bytes(b"already-here")
    evidence = NormalizedEvidence()
    evidence.images = [
        _image("IMAGE-C", "assets/images/c.png"),
        _image("IMAGE-D", "assets/images/d.png"),
    ]

    summary = _materialize_source_image_assets(evidence, output_dir, previous_store)

    assert summary == {"copied": 1, "resolved": 2, "unresolved": 0}
    assert (output_dir / "assets" / "images" / "c.png").is_file()


def test_unresolvable_and_absolute_refs_are_preserved(tmp_path: Path) -> None:
    output_dir = tmp_path / "current_run"
    output_dir.mkdir()
    absolute = tmp_path / "elsewhere" / "e.png"
    absolute.parent.mkdir()
    absolute.write_bytes(b"absolute-bytes")
    evidence = NormalizedEvidence()
    evidence.images = [
        _image("IMAGE-MISSING", "assets/images/missing.png"),
        _image("IMAGE-ABS", str(absolute)),
        _image("IMAGE-NOREF", None),
    ]

    summary = _materialize_source_image_assets(
        evidence, output_dir, tmp_path / "nowhere" / "evidence.sqlite3",
    )

    assert summary == {"copied": 0, "resolved": 0, "unresolved": 1}
    assert [image.local_asset_ref for image in evidence.images] == [
        "assets/images/missing.png",
        str(absolute),
        None,
    ]
