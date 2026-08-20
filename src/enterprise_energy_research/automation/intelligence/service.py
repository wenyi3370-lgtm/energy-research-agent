"""战略情报服务：采集 → 评分 → 去重 → 简报 → 发布飞书（每日一次）。"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ...adapters.base import SearchAdapter
from ...gateway.base import ModelGateway
from ..db import AutomationDatabase, TaskRepository
from ..feishu.base import FeishuAdapter
from .collector import IntelligenceCollector
from .models import DailyBrief
from .scorer import deduplicate, score_item, select_top

logger = logging.getLogger("enterprise_energy_research.automation.intelligence")

JUDGMENT_PROMPT = (
    "你是企业战略情报分析助手。基于今天的 {count} 条情报（标题与事实如下），"
    "用 30-50 字写一段「今日判断」：总结最重要的行业信号（趋势而非新闻堆砌），"
    "面向储能/V2G 设备制造企业的董事长，直接输出 JSON 字符串（字段 judgment），"
    "不要任何前缀。\n"
    "{items}"
)


class IntelligenceService:
    """One daily briefing per calendar date (idempotent via intelligence_runs)."""

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

    def run_daily(self, brief_date: date | None = None) -> DailyBrief | None:
        """采集+加工+发布当日情报；同日重复调用直接返回已有简报。"""
        brief_date = brief_date or date.today()
        if self.is_paused():
            logger.info("intelligence is paused; daily run skipped for %s", brief_date)
            return None
        if self._already_published(brief_date):
            logger.info("intelligence for %s already published today; skip", brief_date)
            return self._load_published(brief_date)
        if self.gateway is None:
            raise RuntimeError("intelligence requires an LLM gateway (EER_DEEPSEEK_API_KEY)")
        collector = IntelligenceCollector(self.adapters, self.gateway)
        raw_items = collector.collect()
        if not raw_items:
            logger.warning("no intelligence items collected for %s", brief_date)
        scored = sorted((score_item(item, brief_date) for item in raw_items), key=lambda i: i.score, reverse=True)
        unique = deduplicate(scored)
        selected = select_top(unique)
        brief = DailyBrief(
            brief_date=brief_date,
            items=selected,
            sources=list(dict.fromkeys(item.source_name for item in selected if item.source_name)),
            breaking_count=sum(1 for item in selected if item.is_breaking),
        )
        brief.judgment = self._judgment(brief)
        brief.watch_list = self._watch_list(brief)
        self._persist(brief)
        self._publish(brief)
        return brief

    # -- internals ----------------------------------------------------------

    def _judgment(self, brief: DailyBrief) -> str:
        if not brief.items:
            return "今日暂无明显改变行业格局的重大V2G或储能事件，值得持续关注的动态见下方条目。"
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
        import json

        return DailyBrief.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _persist(self, brief: DailyBrief) -> None:
        import json

        self._brief_path(brief.brief_date).write_text(
            json.dumps(brief.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
