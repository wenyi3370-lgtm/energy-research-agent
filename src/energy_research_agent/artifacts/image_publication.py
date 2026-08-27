"""Image publication (P0 refactor): verified-only image publication.

P0 rule: a photograph publishes as an entity illustration ONLY when it is
bound to a concrete entity (``target_entity_id``) AND pixel-verified
(``visual_verified``), unless it is an editorial image (cover/map) that
carries no entity claim.  Context-only matches are recorded in the
withheld ledger (QA-visible) and never silently promoted.

Selection is ordered by ``publication_priority``; per-chapter caps are
applied by the narrative layer (IMAGE_BUDGETS).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import ArtifactBinding, FrozenResearchBundle, ImageEvidence


TYPE_CHAPTER = {
    "logo": "cover",
    "headquarters": "entity_overview",
    "office": "entity_overview",
    "factory": "factories",
    "workshop": "factories",
    "production_line": "factories",
    "location": "factories",
    "product": "products",
    "product_application": "products",
    "equipment": "factories",
    "certificate": "core_evidence",
    "project": "cooperation",
    "other": "entity_overview",
}

TYPE_LABEL = {
    "logo": "企业标识",
    "office": "办公场景",
    "headquarters": "企业总部",
    "factory": "生产基地",
    "workshop": "生产车间",
    "production_line": "生产线",
    "location": "区位与基地",
    "product": "实体产品",
    "product_application": "产品应用",
    "equipment": "核心设备",
    "certificate": "认证与证书",
    "project": "项目实景",
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
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    visual_verified: bool = False
    verification_method: str = "none"
    publication_priority: int = Field(default=3, ge=1, le=5)


class ImagePublicationManifest(BaseModel):
    schema_version: str = "1.1"
    freeze_id: str
    required_image_ids: list[str] = Field(default_factory=list)
    prepared_images: list[PublicationImage] = Field(default_factory=list)
    withheld_image_ids: list[str] = Field(default_factory=list)
    withheld_reasons: dict[str, str] = Field(default_factory=dict)
    skipped_duplicate_image_ids: list[str] = Field(default_factory=list)
    skipped_exact_duplicate_image_ids: list[str] = Field(default_factory=list)
    skipped_perceptual_duplicate_image_ids: list[str] = Field(default_factory=list)
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


def publication_eligible(image: ImageEvidence) -> tuple[bool, str]:
    """P0 publication gate: entity-bound AND visually verified, or editorial."""
    if image.target_entity_type == "editorial":
        return True, "editorial"
    if image.target_entity_id is None:
        return False, "未绑定目标实体（target_entity_id 为空）"
    if not image.visual_verified:
        return False, f"未通过像素级视觉核验（verification_method={image.verification_method}）"
    return True, "entity-bound and visually verified"


def _candidate_roots(output_root: Path, extra_roots: Iterable[Path] = ()) -> list[Path]:
    roots: list[Path] = [output_root]
    roots.extend(extra_roots)
    roots.extend(output_root.parents)
    expanded: list[Path] = []
    for root in roots:
        # The evidence archiver writes under <evidence_root>/assets/images and
        # production runs use run_dir/outputs/01_evidence as that root, while
        # artifacts publish from run_dir/outputs/artifacts — so the 01_evidence
        # sibling must be reachable from the artifact tree as well.
        expanded.extend([
            root, root / "evidence", root / "freeze", root / "raw",
            root / "01_evidence",
        ])
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
    # The vision gateway returns an audit answer (category / description /
    # confidence).  It is evidence metadata, not reader-facing caption copy.
    # Prefer the frozen entity name and never leak the model questionnaire,
    # Markdown emphasis or confidence discussion into Word/HTML.
    if image.product_id:
        product = next((item for item in bundle.products if item.product_id == image.product_id), None)
        if product:
            return f"{product.name}产品实景"
    if image.factory_id:
        factory = next((item for item in bundle.factories if item.factory_id == image.factory_id), None)
        if factory:
            return f"{factory.name or '生产基地'}实景"
    if image.alt_text:
        return image.alt_text.strip()
    if image.visual_description and not any(token in image.visual_description for token in (
        "图中主体属于", "主体类别", "置信度", "是否能支撑", "客观描述",
    )):
        return re.sub(r"[*_#]+", "", image.visual_description).strip()
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
    withheld_ids: list[str] = []
    withheld_reasons: dict[str, str] = {}
    duplicate_ids: list[str] = []
    exact_duplicate_ids: list[str] = []
    perceptual_duplicate_ids: list[str] = []
    seen_sha256: set[str] = set()
    seen_phashes: list[str] = []
    # stable order: higher editorial priority first; ties keep bundle insertion
    # order so the original record wins dedupe against later copies
    ordered = [image for _, image in sorted(
        enumerate(bound), key=lambda pair: (-pair[1].publication_priority, pair[0]),
    )]
    for image in ordered:
        eligible, reason = publication_eligible(image)
        if not eligible:
            withheld_ids.append(image.image_id)
            withheld_reasons[image.image_id] = reason
            continue
        if image.sha256.lower() in seen_sha256:
            duplicate_ids.append(image.image_id)
            exact_duplicate_ids.append(image.image_id)
            continue
        if any(_phash_distance(image.phash, seen) <= 4 for seen in seen_phashes):
            duplicate_ids.append(image.image_id)
            perceptual_duplicate_ids.append(image.image_id)
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
                source_note=f"图片来源：{image.source_title or image.source_domain}；原始页面：{image.source_page_url}。",
                source_page_url=str(image.source_page_url),
                source_id=image.source_id,
                entity_id=image.entity_id,
                factory_id=image.factory_id,
                product_id=image.product_id,
                sha256=image.sha256,
                phash=image.phash,
                width=image.width,
                height=image.height,
                target_entity_id=image.target_entity_id,
                target_entity_type=image.target_entity_type,
                visual_verified=image.visual_verified,
                verification_method=image.verification_method,
                publication_priority=image.publication_priority,
            ))
            seen_sha256.add(image.sha256.lower())
            seen_phashes.append(image.phash)
        except Exception as exc:
            diagnostics.append(f"{image.image_id}: {type(exc).__name__}: {exc}")
    manifest = ImagePublicationManifest(
        freeze_id=bundle.freeze.freeze_id,
        required_image_ids=[image.image_id for image in bound],
        prepared_images=prepared,
        withheld_image_ids=withheld_ids,
        withheld_reasons=withheld_reasons,
        skipped_duplicate_image_ids=duplicate_ids,
        skipped_exact_duplicate_image_ids=exact_duplicate_ids,
        skipped_perceptual_duplicate_image_ids=perceptual_duplicate_ids,
        diagnostics=diagnostics,
    )
    write_image_evidence_manifests(bundle.images, output_root)
    write_image_publication_manifest(manifest, output_root)
    return manifest


def _phash_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return max(len(str(left)), len(str(right)))


def write_image_evidence_manifests(images: list[ImageEvidence], output_root: Path) -> tuple[Path, Path]:
    """Write discovery and verified-evidence ledgers before publication selection."""
    output_root.mkdir(parents=True, exist_ok=True)
    fields = (
        "image_id", "entity_id", "factory_id", "product_id", "image_type", "source_url",
        "source_page_url", "source_title", "retrieved_at", "mime_type", "width", "height",
        "sha256", "phash", "local_asset_ref", "verification_status",
        "target_entity_type", "target_entity_id", "visual_verified", "semantic_score",
        "visual_description", "publication_priority", "verification_method",
    )

    def item(image: ImageEvidence) -> dict:
        payload = image.model_dump(mode="json")
        return {field: payload.get(field) for field in fields}

    discovery = output_root / "image_discovery_manifest.json"
    evidence = output_root / "image_evidence_manifest.json"
    discovery.write_text(json.dumps({"schema_version": "1.0", "images": [item(image) for image in images]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verified = [image for image in images if image.verification_status == VerificationStatus.VERIFIED]
    evidence.write_text(json.dumps({"schema_version": "1.0", "images": [item(image) for image in verified]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return discovery, evidence


def write_image_publication_manifest(manifest: ImagePublicationManifest, output_root: Path) -> Path:
    path = output_root / "image_publication_manifest.json"
    path.write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
