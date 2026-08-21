"""Kimi WebBridge Image Discovery (P0-15/P0-16) and usage telemetry (P0-14).

Discovery reads real image DOM (src/srcset/lazy attributes/picture/background)
through the browser bridge's ``evaluate`` command — accessibility snapshots
are never treated as image discovery. Candidates keep their page context and
bind to entity/factory/product so a product image stays a product image.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ImageEvidence

# Mirrors the browser-side SKIP filter (decorative chrome is never evidence);
# the Python-side copy guarantees the same behavior for non-JS discovery paths.
DECORATIVE_URL_RE = re.compile(
    r"(icon|avatar|btn|qrcode|weixin|wxpay|share|loading|spinner|arrow|emoji|favicon|logo_\d+|\.ico)",
    re.IGNORECASE,
)
MIN_DECORATIVE_PX = 80  # images below 80x80 are icons/thumbnails, not evidence

IMAGE_DISCOVERY_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  // decorative chrome (icons, avatars, QR codes, spinners) is never evidence
  const SKIP = /(icon|avatar|btn|qrcode|weixin|wxpay|share|loading|spinner|arrow|emoji|favicon|logo_\d+|\.ico)/i;
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return u || ''; } };
  const push = (url, el, srcAttr) => {
    if (!url || seen.has(url)) return;
    if (SKIP.test(url)) return;
    const w = el.naturalWidth || 0, h = el.naturalHeight || 0;
    if (w && h && w < 80 && h < 80) return;  // icons/thumbnails below 80px
    seen.add(url);
    let link = null;
    try { link = el.closest ? el.closest('a') : null; } catch (e) {}
    let surrounding = '';
    try { surrounding = ((el.parentElement && el.parentElement.textContent) || '').trim().slice(0, 200); } catch (e) {}
    out.push({
      url: abs(url), src_attr: srcAttr,
      alt: (el.alt || '').trim(), title: (el.title || '').trim(),
      surrounding_text: surrounding,
      link_target: link ? abs(link.getAttribute('href') || '') : '',
      width: w, height: h
    });
  };
  document.querySelectorAll('img').forEach(el => {
    const srcset = el.getAttribute('srcset') || el.getAttribute('data-srcset');
    if (srcset) srcset.split(',').forEach(part => { const u = part.trim().split(/\s+/)[0]; push(u, el, 'srcset'); });
    ['src', 'data-src', 'lazy-src', 'data-original', 'data-lazy-src', 'data-url'].forEach(attr => {
      const v = el.getAttribute(attr);
      if (v) push(v, el, attr);
    });
  });
  document.querySelectorAll('picture source').forEach(el => {
    const srcset = el.getAttribute('srcset') || el.getAttribute('data-srcset');
    if (srcset) srcset.split(',').forEach(part => { const u = part.trim().split(/\s+/)[0]; push(u, el, 'picture/source'); });
  });
  document.querySelectorAll('[style]').forEach(el => {
    const m = (el.getAttribute('style') || '').match(/background(?:-image)?\s*:\s*url\(["']?([^"')]+)["']?\)/);
    if (m) push(m[1], el, 'background-image');
  });
  return { page_title: document.title, page_url: location.href, images: out.slice(0, 24) };
})()
"""

IMAGE_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("logo", ("logo", "标识", "商标")),
    ("headquarters", ("总部", "总部大楼", "headquarters")),
    ("production_line", ("生产线", "产线", "assembly line")),
    ("factory", ("工厂", "厂区", "生产基地", "plant")),
    ("product", ("产品", "型号", "设备外观")),
    ("certificate", ("证书", "认证", "certificate")),
    ("project", ("项目现场", "工程项目", "交付项目")),
    ("location", ("园区", "区位", "地图")),
)

# URL path hints, applied AFTER contextual keywords; "icon" maps to "other"
# because decorative chrome is never report evidence.
URL_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("logo", ("/logo", "logo-", "brand", "标志")),
    ("icon", ("icon", "avatar", "btn", "qrcode", "favicon")),
    ("product", ("/product", "product-", "goods")),
    ("factory", ("/factory", "factory-", "plant")),
    ("certificate", ("cert", "certificate")),
    ("location", ("map", "地图", "园区")),
)


class KimiUsageTelemetry(BaseModel):
    """Per-run Kimi/bridge and image-pipeline telemetry (P0-14/P0-16).

    ``images == 0`` must be explainable: was Kimi down, did it not browse,
    did browsing find nothing, did the validator reject, or did downloads fail?
    """

    kimi_status: str = "UNKNOWN"  # AVAILABLE | BLOCKED | UNKNOWN
    kimi_available: bool = False
    kimi_queries: int = 0
    kimi_pages_visited: int = 0
    kimi_target_pages_visited: int = 0
    kimi_product_pages: int = 0
    kimi_factory_pages: int = 0
    kimi_image_pages: int = 0
    kimi_dom_inspections: int = 0
    image_discovery_status: str = "NOT_RUN"  # OK | BLOCKED | NOT_RUN | EMPTY
    reason: str | None = None
    image_candidates_found: int = 0
    image_candidates_verified: int = 0
    images_archived: int = 0
    images_rejected: int = 0
    image_download_failures: int = 0


class ImageCandidate(BaseModel):
    candidate_id: str
    url: str
    src_attribute: str | None = None
    alt: str | None = None
    title: str | None = None
    surrounding_text: str | None = None
    link_target: str | None = None
    page_title: str | None = None
    page_url: str
    width: int = 0
    height: int = 0
    image_type: str = "other"
    page_kind: str | None = None
    entity_key: str | None = None
    factory_key: str | None = None
    product_key: str | None = None
    source_kind: str = "official_company"
    publisher: str | None = None


class KimiImageDiscovery:
    """Discover image candidates on real target pages via Kimi WebBridge.

    AnySearch finds candidate pages; Kimi opens the REAL target page and its
    DOM is inspected with ``evaluate`` — never only a search-result page.
    """

    def __init__(self, adapter, telemetry: KimiUsageTelemetry | None = None) -> None:
        self.adapter = adapter
        self.telemetry = telemetry or KimiUsageTelemetry()

    def discover(self, pages: list[dict]) -> list[ImageCandidate]:
        """Visit pages and return image candidates with page context.

        Each page dict: {url, kind: "product"|"factory"|"image"|"page",
        entity_key, factory_key, product_key, source_kind, publisher}.
        """
        health = self.adapter.health()
        self.telemetry.kimi_available = health.available
        if not health.available:
            self.telemetry.kimi_status = "BLOCKED"
            self.telemetry.image_discovery_status = "BLOCKED"
            self.telemetry.reason = "browser daemon/extension unavailable: " + "; ".join(health.diagnostics)
            return []
        self.telemetry.kimi_status = "AVAILABLE"
        candidates: list[ImageCandidate] = []
        for page in pages:
            url = page.get("url")
            if not url:
                continue
            kind = page.get("kind", "page")
            try:
                self.adapter.navigate_to(url, new_tab=True)
            except Exception as exc:  # noqa: BLE001 - surface as telemetry, never silently
                self.telemetry.image_discovery_status = "BLOCKED"
                self.telemetry.reason = f"navigation failed for {url}: {type(exc).__name__}"
                continue
            self.telemetry.kimi_pages_visited += 1
            self.telemetry.kimi_target_pages_visited += 1
            if kind == "product":
                self.telemetry.kimi_product_pages += 1
            elif kind == "factory":
                self.telemetry.kimi_factory_pages += 1
            elif kind == "image":
                self.telemetry.kimi_image_pages += 1
            try:
                payload = self.adapter.evaluate(IMAGE_DISCOVERY_JS)
            except Exception as exc:  # noqa: BLE001
                self.telemetry.image_discovery_status = "BLOCKED"
                self.telemetry.reason = f"DOM extraction failed for {url}: {type(exc).__name__}"
                continue
            self.telemetry.kimi_dom_inspections += 1
            page_title = str(payload.get("page_title") or "")
            page_url = str(payload.get("page_url") or url)
            for raw in payload.get("images") or []:
                url = str(raw.get("url") or "")
                width = int(raw.get("width") or 0)
                height = int(raw.get("height") or 0)
                if DECORATIVE_URL_RE.search(url):
                    continue
                if width and height and width < MIN_DECORATIVE_PX and height < MIN_DECORATIVE_PX:
                    continue
                candidate = ImageCandidate(
                    candidate_id=new_sortable_id("IMG"),
                    url=str(raw.get("url") or ""),
                    src_attribute=str(raw.get("src_attr") or ""),
                    alt=str(raw.get("alt") or "") or None,
                    title=str(raw.get("title") or "") or None,
                    surrounding_text=str(raw.get("surrounding_text") or "") or None,
                    link_target=str(raw.get("link_target") or "") or None,
                    page_title=page_title or None,
                    page_url=page_url,
                    width=int(raw.get("width") or 0),
                    height=int(raw.get("height") or 0),
                    image_type=self._classify(raw, page_title, kind),
                    page_kind=kind,
                    entity_key=page.get("entity_key"),
                    factory_key=page.get("factory_key"),
                    product_key=page.get("product_key"),
                    source_kind=page.get("source_kind", "official_company"),
                    publisher=page.get("publisher"),
                )
                if candidate.url:
                    candidates.append(candidate)
        self.telemetry.image_candidates_found = len(candidates)
        self.telemetry.image_discovery_status = "OK" if candidates else "EMPTY"
        return candidates

    @staticmethod
    def _classify(raw: dict, page_title: str, page_kind: str) -> str:
        """Context keywords first, then URL hints, then size heuristics;
        the page-kind fallback only runs when nothing else said otherwise."""
        alt = str(raw.get("alt") or "").lower()
        title_attr = str(raw.get("title") or "").lower()
        surrounding = str(raw.get("surrounding_text") or "").lower()
        url = str(raw.get("url") or "").lower()
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
        context = " ".join(filter(None, (alt, surrounding, title_attr, page_title or "")))
        for image_type, keywords in IMAGE_TYPE_KEYWORDS:
            if any(keyword.lower() in context for keyword in keywords):
                return image_type
        for image_type, tokens in URL_TYPE_HINTS:
            if any(token in url for token in tokens):
                # decorative chrome is never report evidence
                return "other" if image_type == "icon" else image_type
        # small, roughly square images are logos/icons — never scene photos
        if width and height and max(width, height) <= 120 and abs(width - height) <= 40:
            return "logo"
        if page_kind == "product":
            return "product"
        if page_kind == "factory":
            return "factory"
        return "other"


def average_phash(payload: bytes) -> str:
    """Deterministic 8x8 average hash for duplicate detection."""
    with Image.open(io.BytesIO(payload)) as source:
        frame = source.convert("L").resize((8, 8))
    pixels = list(frame.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


class ImageEvidenceBuilder:
    """Turn discovery candidates into ImageEvidence (hash + dimensions + MIME).

    ImageAssetArchiver keeps its separate job (download/verify/archive). This
    builder owns the discovery -> evidence handoff only.
    """

    MIME_BY_EXTENSION = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
    }

    def __init__(self, fetcher=None, *, max_bytes: int = 15_000_000) -> None:
        self.fetcher = fetcher
        self.max_bytes = max_bytes

    def build(
        self,
        candidate: ImageCandidate,
        *,
        source_id: str,
        entity_id: str | None = None,
        factory_id: str | None = None,
        product_id: str | None = None,
    ) -> ImageEvidence | None:
        try:
            payload = self.fetcher(candidate.url, candidate.page_url) if self.fetcher else None
            if payload is None:
                raise ValueError("no fetcher available")
            if not payload or len(payload) > self.max_bytes:
                raise ValueError(f"invalid byte size: {len(payload)}")
            with Image.open(io.BytesIO(payload)) as decoded:
                decoded.verify()
            with Image.open(io.BytesIO(payload)) as decoded:
                width, height = decoded.size
                mime = Image.MIME.get((decoded.format or "").upper()) or self._mime_from_url(candidate.url)
            if width <= 0 or height <= 0:
                raise ValueError("invalid dimensions")
            return ImageEvidence(
                image_id=candidate.candidate_id,
                entity_id=entity_id,
                factory_id=factory_id,
                product_id=product_id,
                source_url=candidate.url,
                source_page_url=candidate.page_url,
                source_id=source_id,
                source_domain=candidate.page_url.split("/", 2)[2] if "//" in candidate.page_url else "",
                source_title=candidate.page_title,
                image_type=candidate.image_type,  # type: ignore[arg-type]
                sha256=hashlib.sha256(payload).hexdigest(),
                phash=average_phash(payload),
                width=width,
                height=height,
                mime_type=mime,
                alt_text=candidate.alt,
                surrounding_text=candidate.surrounding_text,
                verification_status=VerificationStatus.UNVERIFIED,
                confidence=0.0,
            )
        except Exception:
            return None

    @classmethod
    def _mime_from_url(cls, url: str) -> str:
        for extension, mime in cls.MIME_BY_EXTENSION.items():
            if url.lower().split("?")[0].endswith(extension):
                return mime
        return "image/jpeg"
