from __future__ import annotations

import hashlib
import io
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import ImageEvidence


FetchImage = Callable[[str, str], tuple[bytes, str | None]]


@dataclass(slots=True)
class ImageArchiveResult:
    images: list[ImageEvidence]
    archived_image_ids: list[str] = field(default_factory=list)
    failed_image_ids: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        attempted = len(self.archived_image_ids) + len(self.failed_image_ids)
        return len(self.archived_image_ids) / attempted if attempted else 1.0


class ImageAssetArchiver:
    """Archive already-verified image URLs as deterministic local evidence assets.

    Downloads run CONCURRENTLY (each verified image is an independent HTTP
    fetch) so a batch of failing CDN URLs cannot stall the run for tens of
    minutes; failures are counted and recorded, never silent.
    """

    MIME_EXTENSIONS = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }

    def __init__(self, *, max_bytes: int = 15_000_000, timeout_seconds: int = 12, fetcher: FetchImage | None = None, workers: int = 6) -> None:
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.fetcher = fetcher or self._fetch_direct
        self.workers = workers

    def archive(self, images: list[ImageEvidence], evidence_root: Path) -> ImageArchiveResult:
        asset_dir = evidence_root / "assets" / "images"
        asset_dir.mkdir(parents=True, exist_ok=True)
        updated: list[ImageEvidence] = []
        archived: list[str] = []
        failed: list[str] = []
        diagnostics: list[str] = []
        lock = __import__("threading").Lock()

        def fetch_one(image: ImageEvidence) -> tuple[ImageEvidence, str | None]:
            try:
                payload, response_type = self.fetcher(str(image.source_url), str(image.source_page_url))
                if not payload or len(payload) > self.max_bytes:
                    raise ValueError(f"image byte size is outside the allowed range: {len(payload)}")
                digest = hashlib.sha256(payload).hexdigest()
                if digest.lower() != image.sha256.lower():
                    raise ValueError(f"SHA-256 mismatch: expected {image.sha256}, got {digest}")
                width, height, decoded_mime = self._decode(payload)
                expected_mime = image.mime_type.lower().split(";", 1)[0].strip()
                response_mime = (response_type or "").lower().split(";", 1)[0].strip()
                if decoded_mime != expected_mime:
                    raise ValueError(f"decoded MIME mismatch: expected {expected_mime}, got {decoded_mime}")
                if response_mime and not response_mime.startswith("image/"):
                    raise ValueError(f"response is not an image: {response_mime}")
                if (width, height) != (image.width, image.height):
                    raise ValueError(f"dimension mismatch: expected {image.width}x{image.height}, got {width}x{height}")

                safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", image.image_id).strip("-") or "image"
                extension = self.MIME_EXTENSIONS[decoded_mime]
                target = asset_dir / f"{safe_id}-{digest[:12]}{extension}"
                if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    temporary = target.with_suffix(target.suffix + ".tmp")
                    temporary.write_bytes(payload)
                    temporary.replace(target)
                local_ref = target.relative_to(evidence_root).as_posix()
                return image.model_copy(update={"local_asset_ref": local_ref}), None
            except Exception as exc:  # noqa: BLE001
                return image.model_copy(update={"local_asset_ref": None}), f"{type(exc).__name__}: {exc}"

        def worker(image: ImageEvidence) -> None:
            outcome, error = fetch_one(image)
            with lock:
                updated.append(outcome)
                if outcome.local_asset_ref:
                    archived.append(outcome.image_id)
                else:
                    failed.append(outcome.image_id)
                    if error:
                        diagnostics.append(f"{image.image_id}: {error}")

        with __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            pool.map(
                worker,
                [image for image in images if image.verification_status == VerificationStatus.VERIFIED],
            )
        # Non-verified images pass through untouched.
        unverified = [image for image in images if image.verification_status != VerificationStatus.VERIFIED]
        updated = unverified + updated
        for image_id in failed:
            diagnostics.append(f"{image_id}: archive failed (see telemetry image_download_failures)")
        return ImageArchiveResult(
            images=updated,
            archived_image_ids=archived,
            failed_image_ids=failed,
            diagnostics=diagnostics,
        )

    def _fetch_direct(self, url: str, referer: str) -> tuple[bytes, str | None]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SEVC-Evidence-Archiver/1.0)",
                "Referer": referer,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        # Exact image-asset retrieval is not search. Bypass a broken machine proxy
        # rather than silently changing the approved discovery/search provider.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=self.timeout_seconds) as response:
            payload = response.read(self.max_bytes + 1)
            return payload, response.headers.get("Content-Type")

    @classmethod
    def _decode(cls, payload: bytes) -> tuple[int, int, str]:
        with Image.open(io.BytesIO(payload)) as decoded:
            decoded.verify()
        with Image.open(io.BytesIO(payload)) as decoded:
            width, height = decoded.size
            format_name = (decoded.format or "").upper()
        mime = Image.MIME.get(format_name)
        if mime not in cls.MIME_EXTENSIONS:
            raise ValueError(f"unsupported decoded image format: {format_name or 'unknown'}")
        return width, height, mime
