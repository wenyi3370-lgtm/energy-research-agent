"""战略情报服务：采集 → 评分 → 去重 → 简报 → 发布飞书（每日一次）。"""

from __future__ import annotations

import logging
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ...adapters.base import SearchAdapter
from ...gateway.base import ModelGateway
from ..db import AutomationDatabase, TaskRepository
from ..feishu.base import FeishuAdapter
from .collector import IntelligenceCollector
from .freshness import (
    PRIMARY_WINDOW,
    RECOVERY_WINDOW,
    UPDATE_WINDOW,
    apply_freshness_gate,
    are_same_event,
    content_sha256,
    normalize_current_time,
)
from .models import DailyBrief, IntelligenceItem, RawIntelligenceItem
from .scorer import deduplicate, score_item, select_top
from ...research.recall import RecallAudit

logger = logging.getLogger("enterprise_energy_research.automation.intelligence")

DAILY_CLAIM_STARTED = "STARTED"
DAILY_CLAIM_RUNNING = "ALREADY_RUNNING"
DAILY_CLAIM_PUBLISHED = "ALREADY_PUBLISHED"
DAILY_RUN_LOCK_STALE_SECONDS = 3 * 60 * 60

JUDGMENT_PROMPT = (
    "你是企业战略情报分析助手。基于今天的 {count} 条情报（标题与事实如下），"
    "用 30-50 字写一段「今日判断」：总结最重要的行业信号（趋势而非新闻堆砌），"
    "面向储能/V2G 设备制造企业的董事长，直接输出 JSON 字符串（字段 judgment），"
    "不要任何前缀。\n"
    "{items}"
)


class IntelligenceService:
    """One daily briefing per date via an atomic in-flight lock and result marker."""

    def __init__(
        self,
        db: AutomationDatabase,
        workdir: Path,
        adapters: dict[str, SearchAdapter],
        gateway: ModelGateway | None,
        notifier: FeishuAdapter | None = None,
        receiver: str = "",
    ) -> None:
        self.db = db
        self.workdir = Path(workdir)
        self.adapters = adapters
        self.gateway = gateway
        self.notifier = notifier
        self.receiver = receiver

    def run_daily(
        self,
        brief_date: date | None = None,
        *,
        current_time: datetime | None = None,
        _lock_token: str | None = None,
    ) -> DailyBrief | None:
        """采集+加工+发布当日情报；原子日锁确保同日最多一个执行者。"""
        current_time = normalize_current_time(current_time)
        brief_date = brief_date or current_time.date()
        lock_token = _lock_token
        if lock_token is None:
            if self.is_paused():
                logger.info("intelligence is paused; daily run skipped for %s", brief_date)
                return None
            claim, lock_token = self.claim_daily(brief_date, current_time=current_time)
            if claim == DAILY_CLAIM_PUBLISHED:
                logger.info("intelligence for %s already published today; skip", brief_date)
                return self._load_published(brief_date)
            if claim == DAILY_CLAIM_RUNNING:
                logger.info("intelligence for %s is already running; skip duplicate trigger", brief_date)
                return None
        try:
            if self.is_paused():
                logger.info("intelligence was paused after claim; daily run skipped for %s", brief_date)
                return None
            if lock_token is None or not self._owns_daily_lock(brief_date, lock_token):
                logger.warning("daily intelligence lock ownership lost for %s; abort", brief_date)
                return None
            return self._run_daily_claimed(brief_date, current_time)
        finally:
            if lock_token is not None:
                self._release_daily_lock(brief_date, lock_token)

    def _run_daily_claimed(self, brief_date: date, current_time: datetime) -> DailyBrief:
        """Execute a run only after the caller owns the date-scoped lock."""
        if self.gateway is None:
            raise RuntimeError("intelligence requires an LLM gateway (EER_DEEPSEEK_API_KEY)")
        history = self._load_freshness_history()
        collector = IntelligenceCollector(self.adapters, self.gateway)
        raw_items = collector.collect(
            current_time=current_time,
            update_targets=self._update_targets(history, current_time),
        )
        collection_failures = list(collector.extraction_failures)
        if collector.extraction_attempt_count and collector.extraction_success_count == 0:
            collection_status = "FAILED"
        elif collection_failures:
            collection_status = "DEGRADED"
        else:
            collection_status = "OK"
        if not raw_items:
            logger.warning(
                "no intelligence items collected for %s; collection_status=%s failures=%d",
                brief_date, collection_status, len(collection_failures),
            )
        gate = apply_freshness_gate(raw_items, history=history, current_time=current_time)
        recent_items = gate.accepted
        freshness_rejections = gate.rejected
        if freshness_rejections:
            logger.info(
                "intelligence freshness gate rejected %d/%d candidates",
                len(freshness_rejections), len(raw_items),
            )
        scored = sorted(
            (score_item(item, current_time) for item in recent_items),
            key=lambda i: i.score,
            reverse=True,
        )
        unique = deduplicate(scored)
        selected = select_top(unique)
        recall_result = collector.recall_result
        if recall_result is not None:
            funnel = recall_result.funnel
            funnel.candidate_items = len(raw_items)
            funnel.freshness_accepted = len(recent_items)
            funnel.freshness_rejected = len(freshness_rejections)
            funnel.same_event_deduped = max(0, len(scored) - len(unique))
            funnel.in_scope_items = len(unique)
            funnel.final_selected = len(selected)
            funnel.unknown_publication_time_count = sum(
                1 for item in recent_items if item.published_at_iso is None
            )
            funnel.secondary_source_count = sum(1 for item in recent_items if not item.is_original_source)
            funnel.original_source_count = sum(1 for item in recent_items if item.is_original_source)
        brief = DailyBrief(
            brief_date=brief_date,
            items=selected,
            sources=list(dict.fromkeys(item.source_name for item in selected if item.source_name)),
            updated_at=current_time,
            window_start=current_time - RECOVERY_WINDOW,
            window_end=current_time,
            report_cutoff_time=current_time,
            primary_window_start=current_time - PRIMARY_WINDOW,
            recovery_window_start=current_time - RECOVERY_WINDOW,
            update_window_start=current_time - UPDATE_WINDOW,
            candidate_count=len(raw_items),
            freshness_rejected_count=len(freshness_rejections),
            freshness_rejection_reasons=freshness_rejections,
            collection_status=collection_status,
            coverage_complete=False,
            recall_status=recall_result.status.value if recall_result is not None else "PARTIAL_SOURCE_COVERAGE",
            recall_metrics=recall_result.funnel.model_dump(mode="json") if recall_result is not None else {},
            extraction_attempt_count=collector.extraction_attempt_count,
            extraction_failure_count=len(collection_failures),
            collection_failure_reasons=collection_failures[:50],
            breaking_count=sum(1 for item in selected if item.is_breaking),
        )
        brief.judgment = self._judgment(brief)
        brief.watch_list = self._watch_list(brief)
        self._persist(brief)
        self._persist_freshness_audit(brief, gate.evaluated)
        self._persist_freshness_ledger(gate.evaluated)
        if recall_result is not None:
            RecallAudit.write(
                recall_result,
                self.workdir / "intelligence" / "search-recall-audit",
                f"{brief_date:%Y-%m-%d}",
            )
        self._publish(brief)
        return brief

    # -- internals ----------------------------------------------------------

    def _judgment(self, brief: DailyBrief) -> str:
        if not brief.items:
            if brief.collection_status == "FAILED":
                return "今日情报采集链路失败，无法确认是否存在新增信息；系统已记录故障，禁止将本次结果解释为无新增。"
            if brief.collection_status == "DEGRADED":
                return "今日部分来源采集或解析失败，暂未形成可发布情报；本次结果不能等同于确认无新增。"
            return "截至当前时间，未发现符合 NEW/UPDATED 标准的V2G及储能重大新增信息。"
        from ...gateway.base import ModelRequest

        listing = "\n".join(f"- {item.title}：{item.fact}" for item in brief.items)
        try:
            response = self.gateway.complete(ModelRequest(
                purpose="intelligence_judgment",
                messages=[{"role": "user", "content": JUDGMENT_PROMPT.format(count=len(brief.items), items=listing)}],
                temperature=0.4,
                max_tokens=120,
            ))
            content = (response.content or "").strip()
            if content.startswith("{"):
                import json as _json

                try:
                    content = _json.loads(content).get("judgment", content)
                except Exception:  # noqa: BLE001
                    pass
            return content[:80]
        except Exception as exc:  # noqa: BLE001 - judgment is best-effort
            logger.warning("judgment generation failed: %s", str(exc)[:120])
            return "今日行业信号以高评分条目为主，详见下列情报。"

    def _watch_list(self, brief: DailyBrief) -> list[str]:
        items = brief.items[:3]
        watch: list[str] = []
        for item in items:
            if item.category == "政策监管":
                watch.append(f"跟踪{item.entity or '相关机构'}近期政策落地与试点进展")
            elif item.category in ("重大项目", "市场与价格"):
                watch.append(f"关注{item.entity or '相关项目'}招标/价格动态对自身报价的影响")
            elif item.category == "竞争对手":
                watch.append(f"核查{item.entity or '竞品'}新品价格与核心参数")
            else:
                watch.append(f"跟踪{item.title[:24]}")
        return watch[:3]

    def _publish(self, brief: DailyBrief) -> None:
        if self.notifier is None or not self.notifier.available():
            logger.info("no feishu notifier configured; brief saved locally")
            return
        text = brief.render_text()
        from ..feishu.base import FeishuMessage

        delivery = self.notifier.send(FeishuMessage(receiver=self.receiver, text=text))
        if not delivery.delivered:
            logger.warning("brief publish to feishu failed: %s", delivery.diagnostics)
        for item in brief.items:
            if item.is_breaking:
                breaking = self.notifier.send(FeishuMessage(
                    receiver=self.receiver, text=brief.render_breaking(item)
                ))
                if not breaking.delivered:
                    logger.warning("breaking alert publish failed: %s", breaking.diagnostics)

    # -- pause / resume（一键停止推送开关） ------------------------------------

    def _pause_path(self) -> Path:
        path = self.workdir / "intelligence"
        path.mkdir(parents=True, exist_ok=True)
        return path / "PAUSED"

    def is_paused(self) -> bool:
        return self._pause_path().is_file()

    def pause(self) -> bool:
        """暂停每日情报推送（按钮开关）；暂停期间定时触发会被拦截。"""
        self._pause_path().touch()
        return True

    def resume(self) -> bool:
        """恢复每日情报推送。"""
        path = self._pause_path()
        if path.is_file():
            path.unlink()
        return True

    # -- exactly-once daily execution --------------------------------------

    def claim_daily(
        self, brief_date: date, *, current_time: datetime | None = None
    ) -> tuple[str, str | None]:
        """Atomically reserve one daily run across threads/processes.

        The result file is the durable PUBLISHED marker.  The lock file is an
        in-flight marker created with O_EXCL, so two HTTP requests cannot both
        enter collection before the result exists.
        """
        current_time = normalize_current_time(current_time)
        if self._already_published(brief_date):
            return DAILY_CLAIM_PUBLISHED, None
        path = self._daily_lock_path(brief_date)
        for attempt in range(2):
            token = uuid.uuid4().hex
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if attempt == 0 and self._discard_stale_daily_lock(path):
                    continue
                return DAILY_CLAIM_RUNNING, None
            payload = {
                "token": token,
                "started_at": current_time.isoformat(),
                "pid": os.getpid(),
            }
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            # A previous run may have published between our first file check
            # and O_EXCL creation.  In that case the result wins and this
            # reservation is released without executing again.
            if self._already_published(brief_date):
                self._release_daily_lock(brief_date, token)
                return DAILY_CLAIM_PUBLISHED, None
            return DAILY_CLAIM_STARTED, token
        return DAILY_CLAIM_RUNNING, None

    def daily_state(
        self, brief_date: date | None = None, *, current_time: datetime | None = None
    ) -> dict[str, Any]:
        current_time = normalize_current_time(current_time)
        brief_date = brief_date or current_time.date()
        lock_path = self._daily_lock_path(brief_date)
        running = lock_path.is_file() and not self._daily_lock_is_stale(lock_path)
        return {
            "paused": self.is_paused(),
            "date": brief_date.isoformat(),
            "running": running,
            "published_today": self._already_published(brief_date),
        }

    def _daily_lock_path(self, brief_date: date) -> Path:
        path = self.workdir / "intelligence" / "run-locks"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{brief_date:%Y-%m-%d}.lock"

    @staticmethod
    def _daily_lock_is_stale(path: Path) -> bool:
        try:
            return time.time() - path.stat().st_mtime > DAILY_RUN_LOCK_STALE_SECONDS
        except FileNotFoundError:
            return False

    def _discard_stale_daily_lock(self, path: Path) -> bool:
        if not self._daily_lock_is_stale(path):
            return False
        try:
            path.unlink()
            logger.warning("removed stale daily intelligence lock: %s", path.name)
            return True
        except FileNotFoundError:
            return True

    def _owns_daily_lock(self, brief_date: date, token: str) -> bool:
        path = self._daily_lock_path(brief_date)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return payload.get("token") == token

    def _release_daily_lock(self, brief_date: date, token: str) -> None:
        path = self._daily_lock_path(brief_date)
        if not self._owns_daily_lock(brief_date, token):
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    # -- persistence --------------------------------------------------------

    def _brief_path(self, brief_date: date) -> Path:
        path = self.workdir / "intelligence"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{brief_date:%Y-%m-%d}.json"

    def _already_published(self, brief_date: date) -> bool:
        return self._brief_path(brief_date).is_file()

    def _load_published(self, brief_date: date) -> DailyBrief | None:
        path = self._brief_path(brief_date)
        if not path.is_file():
            return None
        return DailyBrief.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _persist(self, brief: DailyBrief) -> None:
        self._brief_path(brief.brief_date).write_text(
            json.dumps(brief.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _freshness_ledger_path(self) -> Path:
        path = self.workdir / "intelligence"
        path.mkdir(parents=True, exist_ok=True)
        return path / "freshness-ledger.json"

    def _load_freshness_history(self) -> list[RawIntelligenceItem]:
        history: list[RawIntelligenceItem] = []
        intelligence_dir = self.workdir / "intelligence"
        if intelligence_dir.is_dir():
            for path in sorted(intelligence_dir.glob("????-??-??.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    for item in payload.get("items", []):
                        history.append(IntelligenceItem.model_validate(item))
                except Exception as exc:  # noqa: BLE001 - one legacy file must not block a run
                    logger.warning("cannot load intelligence history %s: %s", path.name, str(exc)[:120])
        ledger = self._freshness_ledger_path()
        if ledger.is_file():
            try:
                payload = json.loads(ledger.read_text(encoding="utf-8"))
                history.extend(
                    RawIntelligenceItem.model_validate(item)
                    for item in payload.get("items", [])
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("cannot load freshness ledger: %s", str(exc)[:120])
        return history

    @staticmethod
    def _update_targets(
        history: list[RawIntelligenceItem], current_time: datetime
    ) -> list[RawIntelligenceItem]:
        allowed_categories = {"政策监管", "重大项目", "竞争对手", "市场与价格", "技术与产品"}
        targets: list[RawIntelligenceItem] = []
        for item in reversed(history):
            if item.category not in allowed_categories:
                continue
            reference = item.updated_at_iso or item.published_at_iso or item.crawl_at or item.first_seen_at
            if reference is None:
                continue
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=current_time.tzinfo)
            if not current_time - UPDATE_WINDOW <= reference <= current_time:
                continue
            if any(are_same_event(item, existing) for existing in targets):
                continue
            targets.append(item)
            if len(targets) >= 12:
                break
        return targets

    def _persist_freshness_audit(
        self,
        brief: DailyBrief,
        evaluated: list[RawIntelligenceItem],
    ) -> None:
        path = self.workdir / "intelligence" / "freshness-audit"
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"{brief.brief_date:%Y-%m-%d}.json"
        target.write_text(json.dumps({
            "schema_version": "1.0",
            "report_cutoff_time": brief.report_cutoff_time.isoformat() if brief.report_cutoff_time else None,
            "primary_window_start": brief.primary_window_start.isoformat() if brief.primary_window_start else None,
            "recovery_window_start": brief.recovery_window_start.isoformat() if brief.recovery_window_start else None,
            "update_window_start": brief.update_window_start.isoformat() if brief.update_window_start else None,
            "collection_status": brief.collection_status,
            "extraction_attempt_count": brief.extraction_attempt_count,
            "extraction_failure_count": brief.extraction_failure_count,
            "collection_failure_reasons": brief.collection_failure_reasons,
            "candidates": [item.model_dump(mode="json") for item in evaluated],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _persist_freshness_ledger(self, evaluated: list[RawIntelligenceItem]) -> None:
        existing: list[RawIntelligenceItem] = []
        path = self._freshness_ledger_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                existing = [RawIntelligenceItem.model_validate(item) for item in data.get("items", [])]
            except Exception as exc:  # noqa: BLE001
                logger.warning("cannot merge freshness ledger; rebuilding: %s", str(exc)[:120])
        for item in evaluated:
            update_hash = content_sha256(item.update_facts) if item.update_facts else ""
            duplicate = next((
                old for old in existing
                if are_same_event(item, old)
                and item.content_hash == old.content_hash
                and (not update_hash or content_sha256(old.update_facts) == update_hash)
            ), None)
            if duplicate is None:
                existing.append(item)
        existing.sort(
            key=lambda item: (
                item.crawl_at or item.first_seen_at
            ).timestamp() if (item.crawl_at or item.first_seen_at) is not None else 0.0,
            reverse=True,
        )
        existing = existing[:2000]
        path.write_text(json.dumps({
            "schema_version": "1.0",
            "items": [item.model_dump(mode="json") for item in existing],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
