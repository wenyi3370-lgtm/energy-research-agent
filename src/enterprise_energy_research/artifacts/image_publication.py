from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle, ImageEvidence


TYPE_CHAPTER = {
    "logo": "cover",
    "office": "entity_overview",
    "factory": "factories",
    "production_line": "factories",
    "location": "factories",
    "product": "products",
    "certificate": "core_evidence",
    "other": "entity_overview",
}

TYPE_LABEL = {
    "logo": "企业标识",
    "office": "办公场景",
    "factory": "生产基地",
    "production_line": "生产线",
    "location": "区位与基地",
    "product": "实体产品",
    "certificate": "认证与证书",
    "other": "企业图片证据",
}


class PublicationImage(BaseModel):
    image_id: str
    image_type: str
    chapter_key: str
    publication_path: str
    caption: str
    source_note: str
    source_page_url: str
    source_id: str
    entity_id: str | None = None
    factory_id: str | None = None
    product_id: str | None = None
    sha256: str
    phash: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    normalized_mime_type: str = "image/png"


class ImagePublicationManifest(BaseModel):
    schema_version: str = "1.0"
    freeze_id: str
    required_image_ids: list[str] = Field(default_factory=list)
    prepared_images: list[PublicationImage] = Field(default_factory=list)
    skipped_duplicate_image_ids: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    artifact_selections: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def prepared_image_ids(self) -> list[str]:
        return [image.image_id for image in self.prepared_images]

    def by_chapter(self) -> dict[str, list[PublicationImage]]:
        grouped: dict[str, list[PublicationImage]] = defaultdict(list)
        for image in self.prepared_images:
            grouped[image.chapter_key].append(image)
        return dict(grouped)


def _candidate_roots(output_root: Path, extra_roots: Iterable[Path] = ()) -> list[Path]:
    roots: list[Path] = [output_root]
    roots.extend(extra_roots)
    roots.extend(output_root.parents)
    expanded: list[Path] = []
    for root in roots:
        expanded.extend([root, root / "evidence", root / "freeze", root / "raw"])
    unique: list[Path] = []
    for root in expanded:
        resolved = root.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_archived_image(image: ImageEvidence, output_root: Path, extra_roots: Iterable[Path] = ()) -> Path | None:
    if not image.local_asset_ref:
        return None
    reference = Path(image.local_asset_ref)
    if reference.is_absolute():
        return reference if reference.is_file() else None
    for root in _candidate_roots(output_root, extra_roots):
        candidate = (root / reference).resolve()
        if candidate.is_file():
            return candidate
    return None


def _decoded_metadata(path: Path) -> tuple[int, int, str]:
    with Image.open(path) as opened:
        opened.verify()
    with Image.open(path) as opened:
        width, height = opened.size
        mime = Image.MIME.get((opened.format or "").upper(), "")
    return width, height, mime


def _caption(image: ImageEvidence, bundle: FrozenResearchBundle) -> str:
    if image.alt_text:
        return image.alt_text.strip()
    if image.product_id:
        product = next((item for item in bundle.products if item.product_id == image.product_id), None)
        if product:
            return f"{product.name}产品实景"
    if image.factory_id:
        factory = next((item for item in bundle.factories if item.factory_id == image.factory_id), None)
        if factory:
            return f"{factory.name or '生产基地'}实景"
    return TYPE_LABEL.get(image.image_type, "企业图片证据")


def prepare_publication_images(
    bundle: FrozenResearchBundle,
    binding: ArtifactBinding,
    output_root: Path,
    *,
    extra_search_roots: Iterable[Path] = (),
) -> ImagePublicationManifest:
    output_root.mkdir(parents=True, exist_ok=True)
    image_dir = output_root / "evidence_images"
    image_dir.mkdir(parents=True, exist_ok=True)
    bound = [
        image for image in bundle.images
        if image.image_id in binding.image_ids and image.verification_status == VerificationStatus.VERIFIED
    ]
    diagnostics: list[str] = []
    prepared: list[PublicationImage] = []
    duplicate_ids: list[str] = []
    seen_phashes: set[str] = set()
    for image in bound:
        if image.phash in seen_phashes:
            duplicate_ids.append(image.image_id)
            continue
        source = resolve_archived_image(image, output_root, extra_search_roots)
        if source is None:
            diagnostics.append(f"{image.image_id}: verified image has no resolvable local_asset_ref")
            continue
        try:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest.lower() != image.sha256.lower():
                raise ValueError(f"SHA-256 mismatch: expected {image.sha256}, got {digest}")
            width, height, decoded_mime = _decoded_metadata(source)
            expected_mime = image.mime_type.lower().split(";", 1)[0].strip()
            if (width, height) != (image.width, image.height):
                raise ValueError(f"dimension mismatch: expected {image.width}x{image.height}, got {width}x{height}")
            if decoded_mime != expected_mime:
                raise ValueError(f"decoded MIME mismatch: expected {expected_mime}, got {decoded_mime}")
            safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", image.image_id).strip("-") or "image"
            target = image_dir / f"{safe_id}-{digest[:12]}.png"
            with Image.open(source) as opened:
                normalized = ImageOps.exif_transpose(opened)
                if normalized.mode not in {"RGB", "RGBA"}:
                    normalized = normalized.convert("RGBA" if "transparency" in normalized.info else "RGB")
                normalized.save(target, format="PNG", dpi=(300, 300), optimize=True)
            chapter_key = TYPE_CHAPTER.get(image.image_type, "entity_overview")
            prepared.append(PublicationImage(
                image_id=image.image_id,
                image_type=image.image_type,
                chapter_key=chapter_key,
                publication_path=target.relative_to(output_root).as_posix(),
                caption=_caption(image, bundle),
                source_note=f"图片来源：{image.source_title or image.source_domain}；原始页面：{image.source_page_url}；图片证据：{image.image_id}。",
                source_page_url=str(image.source_page_url),
                source_id=image.source_id,
                entity_id=image.entity_id,
                factory_id=image.factory_id,
                product_id=image.product_id,
                sha256=image.sha256,
                phash=image.phash,
                width=image.width,
                height=image.height,
            ))
            seen_phashes.add(image.phash)
        except Exception as exc:
            diagnostics.append(f"{image.image_id}: {type(exc).__name__}: {exc}")
    manifest = ImagePublicationManifest(
        freeze_id=bundle.freeze.freeze_id,
        required_image_ids=[image.image_id for image in bound],
        prepared_images=prepared,
        skipped_duplicate_image_ids=duplicate_ids,
        diagnostics=diagnostics,
    )
    write_image_publication_manifest(manifest, output_root)
    return manifest


def write_image_publication_manifest(manifest: ImagePublicationManifest, output_root: Path) -> Path:
    path = output_root / "image_publication_manifest.json"
    path.write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
