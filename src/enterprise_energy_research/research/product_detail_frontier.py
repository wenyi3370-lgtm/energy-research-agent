"""Persistent, bounded execution for product-detail research.

The frontier is deliberately upstream of evidence normalization.  It only
discovers, fetches and checkpoints pages; it never creates conclusions or
recommendations.  SQLite gives each run restart-safe queue semantics while a
bounded worker pool guarantees that page lifecycles are closed per task.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from enterprise_energy_research.adapters.base import SearchRequest


QueueStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED"]

TRACKING_PARAMETERS = {
    "gclid", "dclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "yclid",
    "spm", "from", "ref", "referrer", "source", "campaign",
}
TRACKING_PREFIXES = ("utm_", "trk_", "tracking_")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str, *, canonical_url: str | None = None) -> str:
    """Return a stable HTTP(S) URL key suitable for crawl deduplication."""

    candidate = (canonical_url or url or "").strip()
    if not candidate:
        raise ValueError("URL must not be empty")
    if "://" not in candidate:
        candidate = "https://" + candidate.lstrip("/")
    parts = urlsplit(candidate)
    scheme = (parts.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {scheme}")
    host = (parts.hostname or "").lower().strip(".")
    if not host:
        raise ValueError(f"URL has no host: {url}")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    port = parts.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    clean_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered in TRACKING_PARAMETERS or lowered.startswith(TRACKING_PREFIXES):
            continue
        clean_query.append((key, value))
    query = urlencode(sorted(clean_query, key=lambda row: (row[0].casefold(), row[1])), doseq=True)
    # Fragments are navigation hints, not different evidence pages.
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass(frozen=True)
class ProductDetailTask:
    task_id: int
    url: str
    normalized_url: str
    source_page: str
    discovered_at: str
    status: QueueStatus
    attempt_count: int
    last_attempt_at: str | None = None
    error: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductDetailPageResult:
    task: ProductDetailTask
    final_url: str
    title: str
    text: str
    discovered_urls: list[str] = field(default_factory=list)
    discovered_images: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PersistentProductDetailQueue:
    """SQLite-backed queue with unique normalized URLs and crash recovery."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        self.recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS product_detail_queue (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL UNIQUE,
                    source_page TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    error TEXT,
                    checkpoint TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_product_queue_status ON product_detail_queue(status, task_id)")

    def enqueue(
        self,
        url: str,
        *,
        source_page: str,
        canonical_url: str | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> bool:
        normalized = normalize_url(url, canonical_url=canonical_url)
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO product_detail_queue
                (url, normalized_url, source_page, discovered_at, status, checkpoint, updated_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (url, normalized, source_page, now, json.dumps(checkpoint or {}, ensure_ascii=False), now),
            )
            return cursor.rowcount == 1

    def recover_interrupted(self) -> int:
        """Return crashed RUNNING tasks to PENDING without touching successes."""
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE product_detail_queue
                SET status='PENDING', error=COALESCE(error, 'interrupted before completion'), updated_at=?
                WHERE status='RUNNING'
                """,
                (now,),
            )
            return cursor.rowcount

    def claim_next(self, *, max_attempts: int = 3) -> ProductDetailTask | None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM product_detail_queue
                WHERE status IN ('PENDING','FAILED') AND attempt_count < ?
                ORDER BY task_id LIMIT 1
                """,
                (max_attempts,),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            now = utc_now()
            connection.execute(
                """
                UPDATE product_detail_queue
                SET status='RUNNING', attempt_count=attempt_count+1,
                    last_attempt_at=?, error=NULL, updated_at=?
                WHERE task_id=?
                """,
                (now, now, row["task_id"]),
            )
            connection.execute("COMMIT")
            refreshed = dict(row)
            refreshed.update(status="RUNNING", attempt_count=int(row["attempt_count"]) + 1, last_attempt_at=now, error=None)
            return self._task(refreshed)

    def checkpoint(self, task_id: int, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE product_detail_queue SET checkpoint=?, updated_at=? WHERE task_id=?",
                (json.dumps(payload, ensure_ascii=False), utc_now(), task_id),
            )

    def finish(self, task_id: int, status: QueueStatus, *, error: str | None = None, checkpoint: dict[str, Any] | None = None) -> None:
        if status not in {"SUCCESS", "FAILED", "SKIPPED"}:
            raise ValueError(f"terminal queue status required, got {status}")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE product_detail_queue
                SET status=?, error=?, checkpoint=COALESCE(?, checkpoint), updated_at=?
                WHERE task_id=?
                """,
                (status, error, json.dumps(checkpoint, ensure_ascii=False) if checkpoint is not None else None, utc_now(), task_id),
            )

    def get(self, normalized_url: str) -> ProductDetailTask | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM product_detail_queue WHERE normalized_url=?", (normalized_url,),
            ).fetchone()
        return self._task(row) if row is not None else None

    def list(self, status: QueueStatus | None = None) -> list[ProductDetailTask]:
        with self._connect() as connection:
            if status:
                rows = connection.execute("SELECT * FROM product_detail_queue WHERE status=? ORDER BY task_id", (status,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM product_detail_queue ORDER BY task_id").fetchall()
        return [self._task(row) for row in rows]

    @staticmethod
    def _task(row: sqlite3.Row | dict[str, Any]) -> ProductDetailTask:
        payload = dict(row)
        checkpoint = payload.get("checkpoint") or "{}"
        if isinstance(checkpoint, str):
            try:
                checkpoint = json.loads(checkpoint)
            except json.JSONDecodeError:
                checkpoint = {}
        return ProductDetailTask(
            task_id=int(payload["task_id"]), url=str(payload["url"]),
            normalized_url=str(payload["normalized_url"]), source_page=str(payload["source_page"]),
            discovered_at=str(payload["discovered_at"]), status=payload["status"],
            attempt_count=int(payload["attempt_count"]), last_attempt_at=payload.get("last_attempt_at"),
            error=payload.get("error"), checkpoint=checkpoint,
        )


class ProductDetailFrontier(PersistentProductDetailQueue):
    """Named research-frontier boundary used by planners and executors.

    Queue persistence remains in the parent; this facade makes it explicit
    that detail discovery is a crawl frontier and not a report generator.
    """

    def run(
        self, browser_factory: Callable[[], "ProductDetailBrowser"], *,
        max_workers: int = 3, limit: int | None = None, max_attempts: int = 3,
        on_result: Callable[[ProductDetailPageResult], None] | None = None,
    ) -> tuple[list[ProductDetailPageResult], "BrowserExecutionMetrics"]:
        pool = BoundedBrowserWorkerPool(
            self, browser_factory, max_workers=max_workers,
            max_attempts=max_attempts, on_result=on_result,
        )
        return pool.run(limit=limit), pool.metrics


class ProductDetailBrowser(Protocol):
    execution_lock: threading.RLock | None

    def open_page(self, url: str) -> Any: ...
    def wait_and_extract(self, page: Any) -> dict[str, Any]: ...
    def close_page(self, page: Any) -> None: ...


@dataclass
class BrowserExecutionMetrics:
    configured_max_workers: int
    active_pages: int = 0
    max_active_pages: int = 0
    opened_pages: int = 0
    closed_pages: int = 0
    succeeded: int = 0
    failed: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def opened(self) -> None:
        with self._lock:
            self.active_pages += 1
            self.opened_pages += 1
            self.max_active_pages = max(self.max_active_pages, self.active_pages)

    def closed(self) -> None:
        with self._lock:
            self.active_pages = max(0, self.active_pages - 1)
            self.closed_pages += 1


class BoundedBrowserWorkerPool:
    """Process a persistent frontier with a hard 1..4 page-worker ceiling."""

    def __init__(
        self,
        queue: PersistentProductDetailQueue,
        browser_factory: Callable[[], ProductDetailBrowser],
        *,
        max_workers: int = 3,
        max_attempts: int = 3,
        on_result: Callable[[ProductDetailPageResult], None] | None = None,
    ) -> None:
        if not 1 <= max_workers <= 4:
            raise ValueError("browser max_workers must be between 1 and 4")
        self.queue = queue
        self.browser_factory = browser_factory
        self.max_workers = max_workers
        self.max_attempts = max_attempts
        self.on_result = on_result
        self.metrics = BrowserExecutionMetrics(configured_max_workers=max_workers)

    def run(self, *, limit: int | None = None) -> list[ProductDetailPageResult]:
        tasks: list[ProductDetailTask] = []
        while limit is None or len(tasks) < limit:
            task = self.queue.claim_next(max_attempts=self.max_attempts)
            if task is None:
                break
            tasks.append(task)
        results: list[ProductDetailPageResult] = []
        if not tasks:
            return results
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks)), thread_name_prefix="product-detail") as pool:
            futures = [pool.submit(self._process, task) for task in tasks]
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)
        results.sort(key=lambda item: item.task.task_id)
        return results

    def _process(self, task: ProductDetailTask) -> ProductDetailPageResult | None:
        browser = self.browser_factory()
        page = None
        execution_lock = getattr(browser, "execution_lock", None)
        guard = execution_lock if execution_lock is not None else nullcontext()
        try:
            with guard:
                try:
                    page = browser.open_page(task.normalized_url)
                    self.metrics.opened()
                    self.queue.checkpoint(task.task_id, {**task.checkpoint, "stage": "OPENED", "opened_at": utc_now()})
                    payload = browser.wait_and_extract(page) or {}
                    result = ProductDetailPageResult(
                        task=task,
                        final_url=str(payload.get("final_url") or task.normalized_url),
                        title=str(payload.get("title") or ""),
                        text=str(payload.get("text") or ""),
                        discovered_urls=[str(item) for item in payload.get("discovered_urls", []) if item],
                        discovered_images=list(payload.get("discovered_images", [])),
                        metadata=dict(payload.get("metadata") or {}),
                    )
                    checkpoint = {
                        **task.checkpoint,
                        "stage": "SAVED",
                        "saved_at": utc_now(),
                        "final_url": result.final_url,
                        "title": result.title,
                        "text": result.text,
                        "discovered_urls": result.discovered_urls,
                        "discovered_images": result.discovered_images,
                        "metadata": result.metadata,
                    }
                    self.queue.finish(task.task_id, "SUCCESS", checkpoint=checkpoint)
                    for discovered in result.discovered_urls:
                        try:
                            self.queue.enqueue(discovered, source_page=result.final_url, checkpoint=task.checkpoint)
                        except ValueError:
                            continue
                    if self.on_result is not None:
                        self.on_result(result)
                    with self.metrics._lock:
                        self.metrics.succeeded += 1
                    return result
                except Exception as exc:  # noqa: BLE001 - task failure is persisted, pool continues
                    self.queue.finish(task.task_id, "FAILED", error=f"{type(exc).__name__}: {exc}")
                    with self.metrics._lock:
                        self.metrics.failed += 1
                    return None
                finally:
                    if page is not None:
                        try:
                            browser.close_page(page)
                        finally:
                            self.metrics.closed()
        except Exception as exc:  # lock/context failure must also be persisted
            self.queue.finish(task.task_id, "FAILED", error=f"{type(exc).__name__}: {exc}")
            with self.metrics._lock:
                self.metrics.failed += 1
            return None


class KimiProductDetailBrowser:
    """Kimi WebBridge implementation with an atomic current-tab lifecycle."""

    DETAIL_JS = r"""
(() => {
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return ''; } };
  const urls = [];
  const images = [];
  const seen = new Set();
  document.querySelectorAll('a[href]').forEach(a => {
    const u = abs(a.getAttribute('href') || '');
    if (!u || !u.startsWith(location.origin) || seen.has(u)) return;
    const label = ((a.textContent || '') + ' ' + u).trim();
    if (!/product|products|detail|solution|spec|pdf|系列|型号|详情|参数|规格/i.test(label)) return;
    seen.add(u); urls.push(u);
  });
  document.querySelectorAll('img').forEach(img => {
    const src = abs(img.currentSrc || img.src || img.getAttribute('data-src') || '');
    if (src) images.push({url: src, alt: img.alt || '', width: img.naturalWidth || 0, height: img.naturalHeight || 0});
  });
  return {discovered_urls: urls.slice(0, 30), discovered_images: images.slice(0, 80)};
})()
"""

    def __init__(self, adapter: Any, execution_lock: threading.RLock | None = None) -> None:
        self.adapter = adapter
        self.execution_lock = execution_lock or threading.RLock()

    def open_page(self, url: str) -> dict[str, Any]:
        if not hasattr(self.adapter, "navigate_to"):
            return {"url": url, "tab_id": None, "legacy_search": True}
        navigation = self.adapter.navigate_to(url, new_tab=True)
        return {"url": str(navigation.get("url") or url), "tab_id": navigation.get("tabId")}

    def wait_and_extract(self, page: dict[str, Any]) -> dict[str, Any]:
        if page.get("legacy_search"):
            envelope = self.adapter.search(SearchRequest(
                query_id=f"PRODUCT-DETAIL-{abs(hash(page['url']))}", query=page["url"],
                entity_id="product-detail", purpose="product detail page",
                requires_browser=True, metadata={"url": page["url"]},
                topic="products", expected_fields=["model", "parameter_name"],
            ))
            hit = envelope.hits[0] if envelope.hits else None
            return {
                "final_url": str((hit.final_url if hit else None) or page["url"]),
                "title": str((hit.title if hit else None) or ""),
                "text": str((hit.text if hit else None) or ""),
                "metadata": {"legacy_search": True},
            }
        self.adapter._command("find_tab", {"url": page["url"], "active": False})
        snapshot = self.adapter._command("snapshot", {})
        discovered = self.adapter.evaluate(self.DETAIL_JS)
        return {
            "final_url": str(snapshot.get("url") or page["url"]),
            "title": str(snapshot.get("title") or ""),
            "text": str(snapshot.get("tree") or ""),
            "discovered_urls": (discovered or {}).get("discovered_urls") or [],
            "discovered_images": (discovered or {}).get("discovered_images") or [],
            "metadata": {"tab_id": page.get("tab_id")},
        }

    def close_page(self, page: dict[str, Any]) -> None:
        if page.get("legacy_search"):
            return
        try:
            self.adapter._command("find_tab", {"url": page["url"], "active": False})
        finally:
            self.adapter._command("close_tab", {})
