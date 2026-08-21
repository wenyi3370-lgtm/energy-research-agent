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

import logging
import os
import re
import time
import uuid
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from ..contracts import (
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


_PORTAL_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>企业研究助手</title><style>
body{font-family:"Microsoft YaHei",sans-serif;background:#f7f8fa;margin:0;color:#111}
.wrap{max-width:720px;margin:0 auto;padding:32px 20px 60px}
h1{color:#1B365D;font-size:24px;margin:0 0 6px}
.sub{color:#6B7280;font-size:13px;margin-bottom:26px}
.card{background:#fff;border:1px solid #d9e2ec;border-radius:12px;padding:22px;margin-bottom:18px}
.card h2{font-size:15px;color:#1B365D;margin:0 0 14px}
label{display:block;font-size:13px;color:#374151;margin:10px 0 4px}
input,select,textarea{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid #d9e2ec;border-radius:8px;font-size:14px;font-family:inherit}
textarea{min-height:70px}
button{margin-top:16px;background:#1B365D;color:#fff;border:0;border-radius:8px;padding:11px 22px;font-size:15px;cursor:pointer}
button:disabled{background:#9ca3af;cursor:not-allowed}
#status{margin-top:14px;font-size:13px;white-space:pre-wrap;line-height:1.7;color:#111}
#status .ok{color:#047857}#status .warn{color:#b45309}
.actions a{display:inline-block;margin:4px 8px 0 0;color:#1B365D;font-size:13px}
.link{color:#1B365D;font-size:13px}
</style></head><body><div class="wrap">
<h1>企业研究助手</h1>
<div class="sub">填写调研对象与范围 → 点「开始调查」。企业研究仅由本页按钮启动，不会定时自动运行；明确失败会立即终止并通知飞书，悬挂任务由故障看门狗自动终止。</div>
<div class="card"><h2>① 用一句话描述调研需求</h2>
<label>例如：「调研宁德时代的主营业务和生产基地」或「研究泰国户用储能市场进入机会」</label>
<textarea id="prompt" placeholder="用自然语言描述你的调研需求…"></textarea>
<button id="parseBtn">解析需求并准备任务</button>
<div id="status"></div>
<div id="parsedCard" style="display:none;margin-top:14px;background:#f7f8fa;border:1px solid #d9e2ec;border-radius:8px;padding:12px">
<label>已准备的任务参数（如需修改，请返回上方重新描述或填写）</label>
<div id="parsedFields"></div>
<button id="startBtn" disabled>▶ 开始调查</button>
</div>
</div>
<div class="card"><h2>② 精确填写（可选，替代自然语言）</h2>
<div class="sub" style="margin-bottom:6px">想逐项指定时使用：</div>
<label>公司名称（选填）</label><input id="company" placeholder="例如：宁德时代">
<label>国家 / 地区（选填）</label><input id="country" placeholder="例如：Thailand">
<label>产品（选填）</label><input id="product" placeholder="例如：Residential BESS">
<label>研究类型</label><select id="rtype">
<option value="company_profile">公司画像</option><option value="market_entry">市场进入</option>
<option value="market_monitor">市场监测</option><option value="competitor_analysis">竞品分析</option>
<option value="policy_regulation">政策法规</option><option value="product_research">产品研究</option>
<option value="channel_research">渠道研究</option><option value="other">其他</option></select>
<label>关注主题（逗号分隔）</label><textarea id="topics" placeholder="主营业务, 生产基地, 产品线"></textarea>
<button id="prepareBtn">用以上参数准备任务</button>
</div>
<div class="card"><h2>调查结果</h2>
<div class="sub">故障看门狗每小时检查一次：仅终止超过 120 分钟无进展的调查并通知飞书，不创建任务、不自动重试。</div>
<div id="runStatus"></div>
<div class="actions" id="links" style="display:none">
<a href="/docs" class="link">高级操作面板（评审/裁决/反馈）</a>
<a href="#" id="viewResult" class="link">查看结果</a>
</div>
<button id="stopAllBtn" style="background:#b91c1c;margin-top:18px">⏹ 停止全部调查任务</button>
<div id="stopAllStatus"></div>
</div>
<div class="card"><h2>每日情报（V2G & 储能日报）</h2>
<button id="intelBtn">立即生成今日情报并推送</button>
<button id="pauseBtn" style="background:#b91c1c;margin-left:8px">⏹ 停止推送</button>
<button id="resumeBtn" style="background:#047857;margin-left:8px;display:none">▶ 恢复推送</button>
<div id="intelStatus"></div>
</div>
<div class="card"><h2>依赖与部署</h2>
<div class="sub" style="margin-bottom:8px">
<b>依赖：</b>Docker Desktop（唯一必需）＋ DeepSeek API Key（真实抽取）＋ 可选飞书应用（通知）/ Kimi WebBridge（深度调研）。Python 无需安装。<br><br>
<b>部署：</b>复制 <code>.env.example</code> 为 <code>.env</code> 并填入密钥 → <code>docker compose up -d --build</code> → 打开本页。企业研究只在本页点击「开始调查」后运行；n8n 仅保留每日情报 10:00（北京时间）和纯故障看门狗。看门狗不会发起研究；日报可在本页暂停或恢复。<br><br>
<b>文档：</b><a href="/docs" class="link">API 操作面板</a> ｜ README.md（仓库根）｜ docs/automation/（架构/Runbook/配置清单）
</div>
</div>
</div>
<script>
let currentRun = null;
let currentParsed = null;
async function call(method, path, body) {
  const resp = await fetch(path, {method, headers: {'Content-Type':'application/json'},
    body: body ? JSON.stringify(body) : undefined});
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((data.error && data.error.message) || (data.detail && JSON.stringify(data.detail)) || ('HTTP ' + resp.status));
  return data;
}
function renderParsed(parsed) {
  const labels = {company:'公司', country:'国家', region:'地区', product:'产品', research_type:'研究类型', topics:'主题', priority:'优先级'};
  currentParsed = parsed;
  const box = document.getElementById('parsedFields');
  box.innerHTML = '';
  for (const [key, label] of Object.entries(labels)) {
    const value = parsed[key];
    const text = Array.isArray(value) ? (value || []).join(', ') : (value || '');
    box.insertAdjacentHTML('beforeend', '<label>' + label + '</label><input data-k="' + key + '" value="' + text.replace(/"/g, '&quot;') + '">');
  }
  box.querySelectorAll('input').forEach(input => input.readOnly = true);
  document.getElementById('parsedCard').style.display = 'block';
  document.getElementById('startBtn').disabled = false;
}
document.getElementById('parseBtn').onclick = async () => {
  const out = document.getElementById('status');
  out.className = ''; out.textContent = '正在解析需求（AI 理解你的描述）…';
  const prompt = document.getElementById('prompt').value.trim();
  if (prompt.length < 4) { out.innerHTML = '<span class="warn">请先输入调研需求</span>'; return; }
  try {
    const data = await call('POST', '/api/v1/research/natural', {prompt, requested_by: 'portal-user'});
    currentRun = data.run_id;
    out.innerHTML = '<span class="ok">✅ 已准备任务：' + data.run_id + '</span>';
    renderParsed(data.parsed || {});
  } catch (e) { out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>'; }
};
document.getElementById('prepareBtn').onclick = async () => {
  const out = document.getElementById('status');
  out.className = ''; out.textContent = '正在准备任务…';
  const body = {task_id: 'TASK-' + Date.now(), requested_by: 'portal-user',
    company: document.getElementById('company').value || null,
    country: document.getElementById('country').value || null,
    product: document.getElementById('product').value || null,
    research_type: document.getElementById('rtype').value,
    topics: document.getElementById('topics').value.split(/[,，]/).map(s => s.trim()).filter(Boolean)};
  try {
    const data = await call('POST', '/api/v1/research/prepare', body);
    currentRun = data.run_id;
    out.innerHTML = '<span class="ok">✅ 任务已准备：' + data.run_id + '</span>';
    renderParsed({company: body.company, country: body.country, product: body.product,
      research_type: body.research_type, topics: body.topics, priority: 'normal'});
  } catch (e) { out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>'; }
};
document.getElementById('startBtn').onclick = async () => {
  const out = document.getElementById('runStatus');
  const button = document.getElementById('startBtn');
  if (!currentRun) { out.innerHTML = '<span class="warn">❌ 请先准备任务</span>'; return; }
  button.disabled = true;
  out.textContent = '正在启动调查…';
  try {
    const data = await call('POST', '/api/v1/research/' + currentRun + '/start', null);
    out.innerHTML = '<span class="ok">✅ ' + (data.message || ('已开始：' + data.status)) + '</span>';
    document.getElementById('links').style.display = 'block';
    document.getElementById('viewResult').href = '/api/v1/research/' + currentRun;
  } catch (e) {
    button.disabled = false;
    out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>';
  }
};
document.getElementById('intelBtn').onclick = async () => {
  const out = document.getElementById('intelStatus');
  out.textContent = '正在采集与推送今日情报（约 3-5 分钟）…';
  try {
    const data = await call('POST', '/api/v1/intelligence/daily', null);
    out.innerHTML = data.paused
      ? '<span class="warn">⏸ 推送已暂停，未采集（先点「恢复推送」）</span>'
      : '<span class="ok">✅ 已触发：' + data.date + '（同日重复触发不会重复采集）</span>';
  } catch (e) { out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>'; }
};
// —— 一键停止：调查任务 ——
document.getElementById('stopAllBtn').onclick = async () => {
  const out = document.getElementById('stopAllStatus');
  if (!confirm('确定停止所有正在执行的调查任务吗？已停止的任务不会自动恢复。')) return;
  out.textContent = '正在停止…';
  try {
    const data = await call('POST', '/api/v1/research/stop-all', null);
    out.innerHTML = data.count > 0
      ? '<span class="ok">✅ 已停止 ' + data.count + ' 个调查任务（' + data.stopped.map(s => s.run_id.slice(-6)).join(', ') + '）</span>'
      : '<span class="ok">当前没有运行中的调查任务</span>';
  } catch (e) { out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>'; }
};
// —— 一键停止：推送（停止 / 恢复两个独立按钮）——
function setPushButtons(paused) {
  document.getElementById('pauseBtn').style.display = paused ? 'none' : 'inline-block';
  document.getElementById('resumeBtn').style.display = paused ? 'inline-block' : 'none';
}
document.getElementById('pauseBtn').onclick = async () => {
  const out = document.getElementById('intelStatus');
  try {
    await call('POST', '/api/v1/intelligence/pause', null);
    out.innerHTML = '<span class="warn">⏸ 推送已停止（每日情报定时触发将被拦截）</span>';
    setPushButtons(true);
  } catch (e) { out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>'; }
};
document.getElementById('resumeBtn').onclick = async () => {
  const out = document.getElementById('intelStatus');
  try {
    await call('POST', '/api/v1/intelligence/resume', null);
    out.innerHTML = '<span class="ok">✅ 推送已恢复（每天 10:00 正常推送）</span>';
    setPushButtons(false);
  } catch (e) { out.innerHTML = '<span class="warn">❌ ' + e.message + '</span>'; }
};
// 页面加载时同步推送开关状态
(async () => {
  try {
    const status = await call('GET', '/api/v1/intelligence/status', null);
    setPushButtons(status.paused);
  } catch (e) { /* 服务未就绪时忽略 */ }
})();
</script></body></html>"""


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
        background.add_task(intel.run_daily)
        return {"triggered": True, "date": datetime.now().date().isoformat(), "ran_async": True}

    @app.get("/api/v1/intelligence/daily/latest")
    def intelligence_latest() -> dict:
        """最近一份情报日报（不触发采集）。"""
        intel = _intelligence_service()
        brief = intel._load_published(datetime.now().date())
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
        """情报推送开关状态。"""
        return {"paused": _intelligence_service().is_paused()}

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

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            with db.session() as session:
                session.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "version": app.version})
        except Exception:  # noqa: BLE001 - health must never raise
            return JSONResponse({"status": "error", "version": app.version}, status_code=503)

    return app
