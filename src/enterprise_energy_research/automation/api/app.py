"""FastAPI application factory for the automation API (Phase 2).

Exposes the ``ResearchService`` workflow to n8n / Feishu triggers via a
small, stable REST surface:

- ``POST /api/v1/research``            submit a task; execution runs in the
                                       background, so the response returns
                                       the run in QUEUED immediately.
- ``GET  /api/v1/research/{run_id}``   current status summary.
- ``GET  /api/v1/research/{run_id}/result``    full structured result.
- ``GET  /api/v1/research/{run_id}/artifacts`` published artifact manifest.
- ``POST /api/v1/research/{run_id}/retry``     bounded re-queue of FAILED/BLOCKED.
- ``GET  /health``                     liveness + DB connectivity.

All errors are structured as ``{"error": {"type", "message", "run_id"}}``
with stable codes (DUPLICATE_TASK, RUN_NOT_FOUND, INVALID_TRANSITION,
RETRY_EXHAUSTED). Every response carries ``X-Request-ID`` and one log line
per request (no secrets are ever logged).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import text

from enterprise_energy_research.evidence.store import EvidenceStore

from ..contracts import (
    DeepResearchPayload,
    FeedbackPayload,
    FeishuFormPayload,
    NaturalLanguagePrompt,
    ResearchRequest,
    ResearchResult,
)
from ..db import AutomationDatabase, DuplicateTaskError, RunNotFoundError
from ..enums import Priority, ResearchType, TaskStatus
from ..executor import ResearchExecutor, SyntheticKernelExecutor
from ..feishu.notifier import FeishuNotifier
from ..retry import RetryPolicy
from ..review import ReviewPolicy
from ..roi import RoiCalculator
from ..service import ConflictNotFoundError, ConflictResolutionError, ResearchService, RetryExhaustedError
from ..state_machine import InvalidTransitionError

logger = logging.getLogger("enterprise_energy_research.automation.api")

_RUN_ID_IN_PATH = re.compile(r"/api/v1/research/([^/]+)")


class OperationalNotificationMisrouteError(ValueError):
    """An operational scheduler message was sent to the research trigger."""


def _error_response(request: Request, error_type: str, status: int, exc: BaseException) -> JSONResponse:
    match = _RUN_ID_IN_PATH.search(request.url.path)
    run_id = match.group(1) if match else None
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "type": error_type,
                "message": str(exc),
                "run_id": run_id,
            }
        },
    )


def _make_error_handler(error_type: str, status: int):
    """Build an exception handler that emits the structured error body."""

    def handler(request: Request, exc: BaseException) -> JSONResponse:
        return _error_response(request, error_type, status, exc)

    return handler


def _register_error_handlers(app: FastAPI) -> None:
    """Map domain exceptions onto structured 4xx responses."""
    app.add_exception_handler(DuplicateTaskError, _make_error_handler("DUPLICATE_TASK", 409))
    app.add_exception_handler(RunNotFoundError, _make_error_handler("RUN_NOT_FOUND", 404))
    app.add_exception_handler(
        InvalidTransitionError, _make_error_handler("INVALID_TRANSITION", 409)
    )
    app.add_exception_handler(
        RetryExhaustedError, _make_error_handler("RETRY_EXHAUSTED", 409)
    )
    app.add_exception_handler(
        ConflictNotFoundError, _make_error_handler("CONFLICT_NOT_FOUND", 404)
    )
    app.add_exception_handler(
        ConflictResolutionError, _make_error_handler("CONFLICT_RESOLUTION_INVALID", 409)
    )
    app.add_exception_handler(
        OperationalNotificationMisrouteError,
        _make_error_handler("OPERATIONAL_NOTIFICATION_MISROUTED", 422),
    )


def _version() -> str:
    try:
        return metadata.version("enterprise-energy-research")
    except metadata.PackageNotFoundError:
        from ... import __version__
        return __version__


# 门户页模板与静态资源随源码打包进镜像（Dockerfile COPY src ./src），
# editable 安装下 __file__ 即 /app/src 内的真实路径。
_PORTAL_DIR = Path(__file__).with_name("portal")
_PORTAL_HTML = (_PORTAL_DIR / "portal.html").read_text(encoding="utf-8")


def _default_executor() -> ResearchExecutor:
    """Pick the run executor from ``EER_AUTOMATION_EXECUTOR``.

    - ``synthetic`` (default): offline synthetic kernel; zero config, works
      out of the box, good for demos/CI.
    - ``orchestrating``: real research pipeline (planner -> search ->
      extract -> phase3). Requires search adapters + an LLM gateway; any
      missing piece fails closed (BLOCKED), never guesses.
    """
    mode = os.environ.get("EER_AUTOMATION_EXECUTOR", "synthetic")
    if mode == "orchestrating":
        from ...gateway import LiteLLMModelGateway
        from ...settings import Settings
        from ..orchestration import OrchestratingExecutor

        return OrchestratingExecutor.from_environment(
            gateway=LiteLLMModelGateway(Settings())
        )
    return SyntheticKernelExecutor()


def _parse_natural_request(prompt: str, gateway) -> NaturalResearchRequest:
    """Use the LLM gateway to map free-form Chinese to structured research fields."""
    from ..contracts import NaturalResearchRequest
    from ...gateway.base import StructuredRequest

    if gateway is None:
        return _keyword_parse(prompt)
    extraction_prompt = (
        "你是企业调研任务解析器。把用户的研究需求解析为 JSON 对象，字段："
        "company（公司名）、country（国家）、region（地区）、product（产品）、"
        "research_type（枚举：market_entry/market_monitor/competitor_analysis/"
        "policy_regulation/company_profile/product_research/channel_research/other）、"
        "topics（主题列表）、priority（low/normal/high/urgent）、notes（补充说明）。"
        "没有的信息留空或给默认值，不要编造。\n用户需求："
        f"{prompt}"
    )
    try:
        return gateway.structured(StructuredRequest[NaturalResearchRequest](
            purpose="natural_research_parsing",
            messages=[{"role": "user", "content": extraction_prompt}],
            response_model=NaturalResearchRequest,
            temperature=0.0,
            metadata={"purpose": "research-parsing"},
        ))
    except Exception:  # noqa: BLE001 - fall back to keyword rules
        return _keyword_parse(prompt)


def _keyword_parse(prompt: str) -> NaturalResearchRequest:
    """关键词兜底：识别常见公司名/国家/产品词（LLM 不可用时）。"""
    import re

    company_match = re.search(r"(?:调研|调查|研究|分析)?([\u4e00-\u9fa5A-Za-z0-9]{2,20}?(?:公司|集团|科技|能源|股份|有限|制造))", prompt)
    research_type = ResearchType.OTHER
    if "竞品" in prompt or "竞争对手" in prompt:
        research_type = ResearchType.COMPETITOR_ANALYSIS
    elif "政策" in prompt or "法规" in prompt:
        research_type = ResearchType.POLICY_REGULATION
    elif "市场进入" in prompt or "进入" in prompt:
        research_type = ResearchType.MARKET_ENTRY
    elif "监测" in prompt:
        research_type = ResearchType.MARKET_MONITOR
    elif "产品" in prompt:
        research_type = ResearchType.PRODUCT_RESEARCH
    elif "公司" in prompt or "企业" in prompt or "画像" in prompt:
        research_type = ResearchType.COMPANY_PROFILE
    return NaturalResearchRequest(
        company=company_match.group(1) if company_match else None,
        research_type=research_type,
        topics=[" ".join(item) for item in re.findall(r"[\u4e00-\u9fa5]{2,8}(?:、|和|以及|,|，|与)?", prompt) if item.strip()][:5],
        notes=prompt,
    )


def _project_root() -> Path:
    """Locate the repository root regardless of install layout.

    The wheel layout (``/app/src/enterprise_energy_research/...``) differs
    from the host editable layout (``<repo>/src/enterprise_energy_research/...``);
    walk up until the directory holding ``config/`` is found.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "config" / "review_policy.yaml").is_file():
            return parent
    return Path(__file__).resolve().parents[3]


def _scan_live_acceptance(query: str) -> list[dict]:
    """Locate live-acceptance runs (build/live_acceptance/*) by company name.

    The host repo is mounted at EER_SKILL_ROOT inside the container, so the
    deep-research endpoint can continue historical live surveys the same way
    it continues automation runs.
    """
    skill_root = Path(os.environ.get("EER_SKILL_ROOT", "/skill"))
    base = skill_root / "build" / "live_acceptance"
    if not base.is_dir() or not (query or "").strip():
        return []
    normalized = query.strip().lower()
    matches: list[dict] = []
    for run_dir in sorted(base.iterdir(), reverse=True):
        summary_path = run_dir / "acceptance_summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        company = ""
        profile = summary.get("C_company_profile") or {}
        if isinstance(profile, dict):
            company = str(profile.get("company_name") or "")
        run_id = ""
        manifest_path = run_dir / "01_evidence" / "run_manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                run_id = str(manifest.get("run_id") or "")
            except (OSError, json.JSONDecodeError):
                run_id = ""
        has_evidence = any(run_dir.glob("evidence_fixed*.sqlite3"))
        if not has_evidence:
            continue
        haystack = f"{company} {run_dir.name} {run_id}".lower()
        if normalized not in haystack:
            continue
        matches.append({
            "run_id": run_id,
            "task_id": "",
            "label": f"{company or run_dir.name}（live 调查）",
            "company": company,
            "status": summary.get("run_status") or "COMPLETED",
            "created_at": None,
            "run_dir": str(run_dir),
        })
    return matches


def create_app(
    database_url: str | None = None,
    executor: ResearchExecutor | None = None,
    workdir: Path | None = None,
    notifier: Any = None,
) -> FastAPI:
    """Build the FastAPI app; all dependencies are injectable for tests.

    ``database_url`` defaults to ``EER_AUTOMATION_DATABASE_URL`` then
    ``sqlite:///./automation.db``; ``workdir`` defaults to
    ``EER_AUTOMATION_WORKDIR`` then ``./automation_work``; ``executor``
    defaults to :class:`SyntheticKernelExecutor` (offline, fixture-based);
    ``notifier`` defaults to the environment-configured Feishu notifier
    (no-op when ``EER_FEISHU_*`` is not set).
    """
    db = AutomationDatabase(
        database_url
        or os.environ.get("EER_AUTOMATION_DATABASE_URL")
        or "sqlite:///./automation.db"
    )
    project_root = _project_root()
    resolved_executor = executor or _default_executor()
    service = ResearchService(
        db=db,
        executor=resolved_executor,
        workdir=Path(workdir or os.environ.get("EER_AUTOMATION_WORKDIR") or "automation_work"),
        review_policy=ReviewPolicy.load(project_root / "config" / "review_policy.yaml"),
        retry_policy=RetryPolicy.load(project_root / "config" / "retry_policy.yaml"),
        notifier=notifier or FeishuNotifier.from_env(),
    )

    app = FastAPI(
        title="Enterprise Energy Research Automation API",
        version=_version(),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.automation_db = db
    _register_error_handlers(app)

    def _intelligence_service():
        """共享情报服务实例（含推送暂停开关）。"""
        from ..intelligence import IntelligenceService

        return IntelligenceService(
            db=db,
            workdir=service.workdir,
            adapters=resolved_executor.adapters if hasattr(resolved_executor, "adapters") else {},
            gateway=resolved_executor.wrapped_gateway.inner
            if getattr(resolved_executor, "wrapped_gateway", None) else None,
            notifier=service.notifier.adapter if service.notifier and service.notifier.adapter else None,
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request request_id=%s run_id=%s path=%s status=%d latency_ms=%.1f",
            request_id,
            _RUN_ID_IN_PATH.search(request.url.path).group(1)
            if _RUN_ID_IN_PATH.search(request.url.path)
            else "-",
            request.url.path,
            response.status_code,
            round((time.perf_counter() - started) * 1000, 1),
        )
        return response

    @app.post("/api/v1/research", status_code=201)
    def submit_research(payload: ResearchRequest, background: BackgroundTasks) -> dict:
        result = service.submit(payload)
        background.add_task(service.execute_run, result.run_id)
        return {
            "run_id": result.run_id,
            "task_id": result.task_id,
            "status": str(result.status),
        }

    # NOTE: 静态路径必须先于 /api/v1/research/{run_id} 注册，否则
    # "lookup" 会被动态路由吞掉（FastAPI 按注册顺序匹配）。
    @app.get("/api/v1/research/lookup")
    def lookup_research(q: str = "") -> dict:
        """按自然语言关键词（公司名/产品/主题）定位任务与 run。

        同时扫描宿主机仓库的 build/live_acceptance（挂载于 EER_SKILL_ROOT），
        因此历史 live 调查（如宁德时代）也能用公司名直接定位；live 调查
        排在前面（它们是最近的深度研究成果）。
        """
        live = _scan_live_acceptance(q)
        live.extend(service.lookup_tasks(q))
        return {"query": q, "matches": live[:8]}

    @app.get("/api/v1/research/{run_id}")
    def get_status(run_id: str) -> ResearchResult:
        return service.get_status(run_id)

    @app.get("/api/v1/research/{run_id}/result")
    def get_result(run_id: str) -> ResearchResult:
        return service.get_result(run_id)

    @app.get("/api/v1/research/{run_id}/artifacts")
    def get_artifacts(run_id: str) -> dict:
        return {
            "run_id": run_id,
            "artifacts": [
                ref.model_dump(mode="json") for ref in service.get_artifacts(run_id)
            ],
        }

    @app.post("/api/v1/research/{run_id}/retry")
    def retry_run(run_id: str, background: BackgroundTasks) -> ResearchResult:
        result = service.retry(run_id)
        background.add_task(service.execute_run, run_id)
        return result

    @app.post("/api/v1/research/{run_id}/feedback", status_code=201)
    def submit_feedback(run_id: str, feedback: FeedbackPayload) -> ResearchResult:
        """Requester feedback; the ROI summary consumes these rows (Phase 11)."""
        return service.submit_feedback(run_id, feedback)

    # -- 继续深度研究（P0 third round）：用户补充/修改需求 → 重新检索 → 重新 Freeze/发布 --
    def _deep_research_status_file(run_dir: Path) -> Path:
        return run_dir / "deep_research_result.json"

    def _run_deep_research(run_id: str, payload: DeepResearchPayload, run_dir: Path) -> None:
        from enterprise_energy_research.research.deep_retry import deep_retry, find_evidence_store

        status_path = _deep_research_status_file(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps({
            "status": "running", "run_id": run_id, "requested_by": payload.requested_by,
            "requirements": payload.requirements,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            search_roots = [
                Path(os.environ.get("EER_SKILL_ROOT", "/skill")) / "build" / "live_acceptance",
                service.workdir,
            ]
            store = None
            if payload.run_dir:
                candidate = Path(payload.run_dir)
                # Host paths (C:/.../<repo>/build/...) translate to the
                # container mount (/skill/build/...) when present.
                if not candidate.exists() and "enterprise-energy-research" in str(candidate):
                    translated = str(candidate)
                    translated = "/skill/" + translated.split("enterprise-energy-research", 1)[1].lstrip("\\/")
                    if Path(translated).is_dir():
                        candidate = Path(translated)
                if candidate.is_dir():
                    fixed = sorted(candidate.glob("evidence_fixed*.sqlite3"))
                    store = EvidenceStore(fixed[-1]) if fixed else None
                    run_dir = candidate
            if store is None:
                store = find_evidence_store(run_id, search_roots)
            if store is None:
                result = {"status": "failed", "run_id": run_id, "reason": f"找不到 run {run_id} 的证据库（run_dir 或 workdir/live_acceptance 均无匹配）"}
            else:
                from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
                from enterprise_energy_research.adapters.kimi_webbridge import KimiWebBridgeSearchAdapter
                from enterprise_energy_research.gateway.http_json_gateway import HttpJsonModelGateway
                from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
                from enterprise_energy_research.settings import Settings
                gateway = HttpJsonModelGateway(Settings())
                archiver = ImageAssetArchiver()
                catalog_pages = None
                company = payload.company or ""
                if "宁德时代" in company or "CATL" in company.upper():
                    catalog_pages = [
                        ("https://www.catl.com/ess/", "储能系统"),
                        ("https://www.catl.com/solution/passengerEV/", "乘用车解决方案"),
                        ("https://www.catl.com/solution/commercialEV/", "商业应用解决方案"),
                        ("https://www.catl.com/solution/recycling/", "循环回收"),
                    ]
                result = deep_retry(
                    store, run_dir,
                    requirements=payload.requirements,
                    company=company,
                    adapters={
                        "anysearch": AnySearchCliAdapter(),
                        "kimi_webbridge": KimiWebBridgeSearchAdapter(session=f"deep-research-{run_id[-6:]}"),
                    },
                    gateway=gateway,
                    fetcher=lambda url, referer: archiver._fetch_direct(url, referer)[0],
                    include_images=payload.include_images,
                    catalog_pages=catalog_pages,
                )
                result["requested_by"] = payload.requested_by
                if payload.save_to_desktop and result.get("published"):
                    desktop_root = Path(os.environ.get("EER_DESKTOP_PATH", "/desktop"))
                    if desktop_root.is_dir():
                        import shutil as _shutil
                        label = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", (result.get("company") or company or run_id)).strip("-")[:40] or "research"
                        target = desktop_root / f"{label}-{datetime.now():%Y%m%d-%H%M}"
                        target.mkdir(parents=True, exist_ok=True)
                        copied = []
                        artifacts_dir = run_dir / "artifacts"
                        if artifacts_dir.is_dir():
                            for name in ("enterprise_research.docx", "enterprise_research_dashboard.html", "enterprise_research.xlsx"):
                                source = artifacts_dir / name
                                if source.is_file():
                                    _shutil.copy2(source, target / name)
                                    copied.append(name)
                            for assets in artifacts_dir.glob("*_assets"):
                                if assets.is_dir():
                                    _shutil.copytree(assets, target / assets.name, dirs_exist_ok=True)
                                    copied.append(assets.name)
                        result["desktop_path"] = str(target)
                        result["desktop_files"] = copied
                # Feishu: text summary + the regenerated artifacts, same as the
                # main pipeline's PUBLISHED notification.  Failures are logged
                # but never break the deep-research result.
                if payload.notify_feishu and result.get("published"):
                    try:
                        notifier = service.notifier
                        if notifier is not None:
                            label = result.get("company") or company or run_id
                            notifier.send_text(
                                f"[深度研究完成] {label}\n"
                                f"需求: {payload.requirements[:120]}\n"
                                f"已验证事实 {result.get('verified_claims_before')} → {result.get('verified_claims_after')} · "
                                f"新数据版本 {result.get('freeze_id') or '-'}\n"
                                "更新后的 Word / HTML / Excel 已随本条消息发送，请查收。"
                            )
                            adapter = getattr(notifier, "adapter", None)
                            send_file = getattr(adapter, "send_file", None)
                            if send_file is not None:
                                for name in ("enterprise_research.docx", "enterprise_research_dashboard.html", "enterprise_research.xlsx"):
                                    path = run_dir / "artifacts" / name
                                    if path.is_file():
                                        send_file("", str(path))
                            result["feishu_notified"] = True
                    except Exception as exc:  # noqa: BLE001 - notification never breaks research
                        logger.warning("deep research feishu notify failed: %s", exc)
                        result["feishu_notified"] = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("deep research failed run_id=%s", run_id)
            result = {
                "status": "failed", "run_id": run_id,
                "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                "requested_by": payload.requested_by,
            }
        status_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @app.post("/api/v1/research/{run_id}/deep-research", status_code=202)
    def deep_research(run_id: str, payload: DeepResearchPayload, background: BackgroundTasks) -> dict:
        """继续深度研究：按用户补充/修改需求补充证据并重新发布 Word/HTML/Excel。"""
        run_dir = Path(payload.run_dir) if payload.run_dir else (service.workdir / run_id)
        background.add_task(_run_deep_research, run_id, payload, run_dir)
        return {
            "run_id": run_id,
            "message": "深度研究已启动：将按需求补充检索、必要时恢复产品图片，并重新生成报告、HTML 与 Excel。",
            "status": "running",
        }

    @app.get("/api/v1/research/{run_id}/deep-research")
    def deep_research_status(run_id: str) -> dict:
        """轮询继续深度研究的进度与结果。"""
        candidates: list[Path] = []
        if (service.workdir / run_id / "deep_research_result.json").is_file():
            candidates.append(service.workdir / run_id / "deep_research_result.json")
        skill_root = Path(os.environ.get("EER_SKILL_ROOT", "/skill"))
        for base in (project_root / "build" / "live_acceptance", skill_root / "build" / "live_acceptance"):
            if not base.is_dir():
                continue
            for path in base.glob("*/deep_research_result.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("run_id") == run_id:
                    candidates.append(path)
        if not candidates:
            raise HTTPException(status_code=404, detail="该 run 尚无深度研究记录")
        newest = max(candidates, key=lambda path: path.stat().st_mtime)
        return json.loads(newest.read_text(encoding="utf-8"))
        return service.submit_feedback(
            run_id,
            submitted_by=feedback.submitted_by,
            adoption_status=feedback.adoption_status,
            user_rating=feedback.user_rating,
            manual_baseline_minutes=feedback.manual_baseline_minutes,
            human_review_minutes=feedback.human_review_minutes,
            human_edit_count=feedback.human_edit_count,
            comment=feedback.comment,
        )

    @app.post("/api/v1/triggers/feishu", status_code=201)
    def feishu_trigger(payload: FeishuFormPayload, background: BackgroundTasks) -> dict:
        """Feishu form / Bitable webhook entry point (Phase 7)."""
        if (
            payload.requested_by.casefold() == "watchdog"
            and payload.research_type == ResearchType.OTHER
            and (payload.company or "").strip().casefold()
            in {"监测通知", "monitor notification"}
        ):
            raise OperationalNotificationMisrouteError(
                "scheduler summaries are operational notifications; use /api/v1/monitor/run"
            )
        result = service.submit(payload.to_research_request())
        background.add_task(service.execute_run, result.run_id)
        return {
            "run_id": result.run_id,
            "task_id": result.task_id,
            "status": str(result.status),
        }

    @app.get("/api/v1/roi/summary")
    def roi_summary() -> dict:
        """Aggregate ROI over collected feedback; empty when no data yet."""
        return RoiCalculator.aggregate(service.roi_rows())

    @app.get("/api/v1/research/{run_id}/conflicts")
    def list_conflicts(run_id: str) -> dict:
        """Evidence conflicts of a run (BLOCKED runs: adjudicate before resume)."""
        return {"run_id": run_id, "conflicts": service.list_conflicts(run_id)}

    @app.post("/api/v1/research/prepare", status_code=201)
    def prepare_research(payload: ResearchRequest) -> dict:
        """企业调研：设置参数后创建任务，停在 QUEUED，等待「开始调查」按钮。

        区别于 ``POST /api/v1/research``（提交即自动执行），此端点仅登记
        任务与首个 run；用户核对参数后调用 ``POST /research/{run_id}/start``
        手动开始。
        """
        session = db.session()
        try:
            from ..db import TaskRepository

            repo = TaskRepository(session)
            if payload.idempotency_key:
                existing = repo.find_by_idempotency_key(payload.idempotency_key)
                if existing is not None:
                    return {"run_id": existing.active_run_id, "task_id": existing.task_id, "status": "EXISTS"}
            if repo.get_task(payload.task_id) is not None:
                raise DuplicateTaskError(f"task_id already exists: {payload.task_id}")
            repo.create_task(payload)
            from ...domain.ids import new_sortable_id

            run_id = new_sortable_id("RUN")
            repo.create_run(run_id, payload)
            repo.update_run_status(run_id, TaskStatus.QUEUED, reason="prepared; waiting for start")
            return {"run_id": run_id, "task_id": payload.task_id, "status": "QUEUED"}
        finally:
            session.close()

    @app.post("/api/v1/research/natural", status_code=201)
    def research_natural(payload: NaturalLanguagePrompt) -> dict:
        """自然语言发起调研：AI 解析参数 → 准备任务（QUEUED，等待「开始调查」）。

        例如：「调研宁德时代的主营业务和生产基地，顺便看看泰国户储市场」。
        解析出的参数随响应返回供确认，然后调用 /research/{run_id}/start。
        """
        parsed = _parse_natural_request(
            payload.prompt,
            resolved_executor.wrapped_gateway.inner
            if getattr(resolved_executor, "wrapped_gateway", None) else None,
        )
        if not (parsed.company or parsed.country or parsed.product):
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail="未能从描述中识别调研对象（公司/国家/产品），请补充说明")
        from ...domain.ids import new_sortable_id

        request = ResearchRequest(
            task_id=new_sortable_id("TASK"),
            idempotency_key=None,
            requested_by=payload.requested_by,
            company=parsed.company,
            country=parsed.country,
            region=parsed.region,
            product=parsed.product,
            research_type=parsed.research_type or ResearchType.OTHER,
            topics=parsed.topics,
            priority=parsed.priority or Priority.NORMAL,
            notes=parsed.notes or payload.prompt,
            language="zh-CN",
        )
        session = db.session()
        try:
            from ..db import TaskRepository

            repo = TaskRepository(session)
            repo.create_task(request)
            run_id = new_sortable_id("RUN")
            repo.create_run(run_id, request)
            repo.update_run_status(run_id, TaskStatus.QUEUED, reason="prepared from natural language; waiting for start")
            return {
                "run_id": run_id,
                "task_id": request.task_id,
                "status": "QUEUED",
                "parsed": parsed.model_dump(mode="json", exclude_none=True),
            }
        finally:
            session.close()

    @app.post("/api/v1/research/{run_id}/start")
    def start_research(run_id: str, background: BackgroundTasks) -> dict:
        """「开始调查」按钮：异步启动已 prepare 的 run。

        真实研究需要 10-20 分钟，端点立即返回；完成/需评审/失败会自动通知
        飞书群。仅允许 QUEUED 状态的 run。
        """
        current = service.get_status(run_id)
        if str(current.status) != "QUEUED":
            from ..state_machine import InvalidTransitionError

            raise InvalidTransitionError(current.status, TaskStatus.RESEARCHING)
        background.add_task(service.execute_run, run_id)
        return {
            "run_id": run_id,
            "task_id": current.task_id,
            "status": "STARTED",
            "message": "调查已开始（后台执行约 10-20 分钟），完成后将自动通知飞书群",
        }

    @app.post("/api/v1/intelligence/daily")
    def intelligence_daily(background: BackgroundTasks) -> dict:
        """触发《V2G & 储能每日情报》采集与发布（每日一次，异步执行）。

        n8n 每天定时调用；同日重复调用返回已发布简报，不会重复采集。
        推送被暂停（PAUSED）时直接返回，不采集不发布。
        情报采集使用当前搜索适配器（anysearch + kimi-webbridge）与 LLM 网关。
        """
        intel = _intelligence_service()
        if intel.is_paused():
            return {"triggered": False, "paused": True, "message": "每日情报推送已暂停"}
        from ..intelligence import current_intelligence_time
        from ..intelligence.service import (
            DAILY_CLAIM_PUBLISHED,
            DAILY_CLAIM_RUNNING,
        )

        current_time = current_intelligence_time()
        claim, lock_token = intel.claim_daily(current_time.date(), current_time=current_time)
        if claim == DAILY_CLAIM_PUBLISHED:
            return {
                "triggered": False,
                "paused": False,
                "already_published": True,
                "running": False,
                "date": current_time.date().isoformat(),
                "message": "今日情报已经发布；同日不会重复采集或推送",
            }
        if claim == DAILY_CLAIM_RUNNING:
            return {
                "triggered": False,
                "paused": False,
                "already_published": False,
                "running": True,
                "date": current_time.date().isoformat(),
                "message": "今日情报正在生成；重复点击不会创建第二个推送任务",
            }
        background.add_task(intel.run_daily, current_time=current_time, _lock_token=lock_token)
        return {
            "triggered": True,
            "paused": False,
            "already_published": False,
            "running": True,
            "date": current_time.date().isoformat(),
            "current_time": current_time.isoformat(),
            "report_cutoff_time": current_time.isoformat(),
            "primary_window_start": (current_time - timedelta(hours=24)).isoformat(),
            "recovery_window_start": (current_time - timedelta(hours=72)).isoformat(),
            "update_window_start": (current_time - timedelta(days=7)).isoformat(),
            "ran_async": True,
        }

    @app.get("/api/v1/intelligence/daily/latest")
    def intelligence_latest() -> dict:
        """最近一份情报日报（不触发采集）。"""
        intel = _intelligence_service()
        from ..intelligence import current_intelligence_time

        brief = intel._load_published(current_intelligence_time().date())
        if brief is None:
            return {"brief_date": None, "message": "今日情报尚未生成；POST /api/v1/intelligence/daily 触发"}
        return brief.model_dump(mode="json")

    @app.post("/api/v1/research/stop-all")
    def stop_all_research() -> dict:
        """一键停止：取消所有排队中或正在执行的调查任务（不可自动重试）。"""
        cancelled = service.cancel_running_runs()
        return {
            "stopped": [
                {"run_id": item.run_id, "task_id": item.task_id, "status": str(item.status)}
                for item in cancelled
            ],
            "count": len(cancelled),
        }

    @app.post("/api/v1/intelligence/pause")
    def intelligence_pause() -> dict:
        """一键停止推送：暂停每日情报（定时触发会被拦截）。"""
        intel = _intelligence_service()
        intel.pause()
        return {"paused": True}

    @app.post("/api/v1/intelligence/resume")
    def intelligence_resume() -> dict:
        """恢复每日情报推送。"""
        intel = _intelligence_service()
        intel.resume()
        return {"paused": False}

    @app.get("/api/v1/intelligence/status")
    def intelligence_status() -> dict:
        """情报推送开关、当日执行和发布状态。"""
        from ..intelligence import current_intelligence_time

        current_time = current_intelligence_time()
        return _intelligence_service().daily_state(current_time=current_time)

    @app.post("/api/v1/maintenance/recover-stale")
    def recover_stale() -> dict:
        """僵尸任务检测：把"研究中超时"的悬挂 run 标记为 FAILED（可重试）。

        典型场景：容器重建杀掉了后台执行进程。本端点立即终止悬挂 run，
        独立的 n8n 故障看门狗每小时执行同样的检查；它不会创建或重试研究。
        """
        recovered = service.recover_stale_runs()
        return {
            "recovered": [
                {"run_id": item.run_id, "task_id": item.task_id, "status": str(item.status)}
                for item in recovered
            ],
            "count": len(recovered),
        }

    @app.post("/api/v1/monitor/run")
    def monitor_run() -> dict:
        """Legacy watchlist endpoint; scheduled research is intentionally disabled.

        Enterprise research must be prepared and started from the local portal.
        Returning a side-effect-free response keeps legacy callers safe without
        silently creating research tasks.
        """
        return {
            "triggered": False,
            "disabled": True,
            "due_count": 0,
            "stale_recovered": 0,
            "ran_async": False,
            "message": "定时研究已禁用；请通过本地网页点击“开始调查”",
        }

    @app.get("/", include_in_schema=False)
    def portal() -> Response:
        """小白引导页：填写参数 → 点「开始调查」→ 跟踪状态。"""
        return Response(content=_PORTAL_HTML, media_type="text/html; charset=utf-8")

    @app.get("/assets/portal-logo.jpg", include_in_schema=False)
    def portal_logo() -> FileResponse:
        """门户页 logo（四川动力电池产业创新中心徽章，随源码打包进镜像）。"""
        return FileResponse(_PORTAL_DIR / "portal_logo.jpg")

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            with db.session() as session:
                session.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "version": app.version})
        except Exception:  # noqa: BLE001 - health must never raise
            return JSONResponse({"status": "error", "version": app.version}, status_code=503)

    return app
