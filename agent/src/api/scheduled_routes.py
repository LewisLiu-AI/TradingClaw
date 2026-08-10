"""Scheduled research HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_scheduled_routes(app, ...)``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys as _sys
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEDULED_RESEARCH_SCHEDULER_ENV = "VIBE_TRADING_ENABLE_SCHEDULER"
_SCHEDULED_RESEARCH_TRUE_VALUES = {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_scheduled_research_store: Any = None
_scheduled_research_executor: Any = None


def _scheduled_research_scheduler_enabled() -> bool:
    """Return whether scheduled research execution is enabled."""
    return get_env_config().agent_tuning.vibe_trading_enable_scheduler


def _get_scheduled_research_store():
    """Return the singleton ScheduledResearchJobStore, creating it on first call."""
    global _scheduled_research_store
    if _scheduled_research_store is None:
        from src.scheduled_research.store import ScheduledResearchJobStore

        _scheduled_research_store = ScheduledResearchJobStore()
    return _scheduled_research_store


async def _dispatch_scheduled_research_job(job) -> None:
    """Run one scheduled research job through the session runtime.

    Waits for the agent run to reach a terminal state, then — when the job's
    ``config["channels"]`` lists delivery targets — publishes the final reply
    to every channel-bound chat on those channels (e.g. the Feishu/WeChat users
    that paired with the bot). The executor's ``COMPLETED`` state therefore
    means "run finished", not merely "enqueued".
    """
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    svc = host._get_session_service()
    if not svc:
        raise RuntimeError("Session runtime not enabled")
    # Pass a copy so the session runtime's internal config writes (e.g.
    # include_shell_tools) do not mutate the persisted scheduled-run config.
    session = svc.create_session(
        title=f"scheduled-research:{job.id}", config=dict(job.config)
    )
    logger.info(
        "dispatching scheduled research job %s via session %s",
        job.id,
        session.session_id,
    )
    send_result = await svc.send_message(session.session_id, job.prompt)
    attempt_id = send_result.get("attempt_id") if isinstance(send_result, dict) else None

    reply = await _wait_for_scheduled_reply(svc, session.session_id, attempt_id)
    if reply is None:
        raise TimeoutError("scheduled research run produced no reply within the timeout")

    await _deliver_scheduled_result(host, reply.content, job)


def _scheduled_run_timeout_s() -> float:
    """Return how long a scheduled research run may take before it times out."""
    raw = os.environ.get("VIBE_TRADING_SCHEDULED_RUN_TIMEOUT_S", "").strip()
    if raw.isdigit():
        return float(raw)
    return 3600.0


async def _wait_for_scheduled_reply(session_service, session_id: str, attempt_id: str | None):
    """Poll for the assistant reply linked to ``attempt_id``.

    Mirrors ``ChannelRuntime._wait_for_reply``: returns the first assistant
    message whose ``linked_attempt_id`` matches, falling back to the most recent
    assistant message when the run never links one. Returns ``None`` on timeout.
    """
    deadline = time.monotonic() + _scheduled_run_timeout_s()
    last_assistant = None
    while time.monotonic() < deadline:
        messages = session_service.get_messages(session_id, limit=200)
        for message in reversed(messages):
            if getattr(message, "role", None) != "assistant":
                continue
            if attempt_id and getattr(message, "linked_attempt_id", None) != attempt_id:
                if last_assistant is None:
                    last_assistant = message
                continue
            return message
        await asyncio.sleep(2)
    return last_assistant


def _available_delivery_channels() -> List[Dict[str, Any]]:
    """Return configured-and-enabled channels usable as delivery targets.

    Reads the structured agent config (``agent.json``/``agent.yaml``) and keeps
    only channels whose section has ``enabled: true``.
    """
    from src.channels.config import load_channels_config
    from src.channels.registry import inspect_channels

    statuses = inspect_channels(load_channels_config())
    return [
        {"name": name, "display_name": info.get("display_name") or name}
        for name, info in sorted(statuses.items())
        if info.get("enabled")
    ]


async def _deliver_scheduled_result(host, content: str, job) -> None:
    """Publish a scheduled result to bound chats on the job's target channels.

    Targets come from ``job.config["channels"]`` (channel names, e.g.
    ``["feishu", "weixin"]``). For each target, every chat bound to that channel
    in the channel runtime's session map receives the result. Best effort: a
    missing channel runtime or an empty session map simply skips delivery.
    """
    config = job.config if isinstance(job.config, dict) else {}
    channels = config.get("channels") or []
    if not isinstance(channels, list) or not channels:
        return
    runtime = host._get_channel_runtime() if hasattr(host, "_get_channel_runtime") else None
    if runtime is None or getattr(runtime, "bus", None) is None:
        logger.info("scheduled result delivery skipped: channel runtime not available")
        return

    from src.channels.bus.events import OutboundMessage

    text = content.strip()
    if not text:
        return
    prompt_preview = job.prompt.strip().replace("\n", " ")[:40]
    payload = f"📊 定时研究结果 · {prompt_preview}\n\n{text}"
    if len(payload) > 4000:
        payload = payload[:4000] + "…(已截断)"

    session_map = getattr(runtime, "_session_map", None) or {}
    for channel_name in channels:
        targets = [key for key in session_map if key.partition(":")[0] == channel_name]
        for key in targets:
            _, sep, chat_id = key.partition(":")
            if not sep:
                continue
            await runtime.bus.publish_outbound(
                OutboundMessage(
                    channel=channel_name,
                    chat_id=chat_id,
                    content=payload,
                    metadata={"_scheduled_result": True, "job_id": job.id},
                )
            )
            logger.info("scheduled result queued for %s:%s", channel_name, chat_id)


def _get_scheduled_research_executor():
    """Return the singleton scheduled research executor."""
    global _scheduled_research_executor
    if _scheduled_research_executor is None:
        from src.scheduled_research.executor import ScheduledResearchExecutor

        _scheduled_research_executor = ScheduledResearchExecutor(
            _get_scheduled_research_store(),
            _dispatch_scheduled_research_job,
            enabled=_scheduled_research_scheduler_enabled(),
        )
    return _scheduled_research_executor


def _start_scheduled_research_executor() -> None:
    """Start scheduled research execution when explicitly enabled."""
    if not _scheduled_research_scheduler_enabled():
        return
    _get_scheduled_research_executor().start()


async def _stop_scheduled_research_executor() -> None:
    """Stop scheduled research execution if it was started."""
    executor = _scheduled_research_executor
    if executor is not None:
        await executor.stop()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateScheduledRunRequest(BaseModel):
    """Request body for POST /scheduled-runs."""

    id: Optional[str] = Field(
        None, description="Job id; auto-generated UUID when omitted"
    )
    prompt: str = Field(
        ..., min_length=1, description="Research prompt or backtest description"
    )
    schedule: str = Field(
        ..., min_length=1, description="Interval-ms or 5-field cron expression"
    )
    next_run_at: Optional[int] = Field(
        None, description="Epoch-ms for next run; defaults to now"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict, description="Optional backtest parameters"
    )


class ScheduledRunResponse(BaseModel):
    """API response for a single scheduled job."""

    id: str
    prompt: str
    schedule: str
    next_run_at: int
    status: str
    created_at: int
    config: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_scheduled_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the scheduled routes onto ``app``.

    Resolves ``require_auth`` from the host ``api_server`` module via
    ``sys.modules`` when not passed explicitly.
    """
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_scheduled_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth

    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        h._validate_path_param(value, kind)

    # --- Routes ---

    @app.post(
        "/scheduled-runs",
        response_model=ScheduledRunResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def create_scheduled_run(
        request: CreateScheduledRunRequest,
    ) -> ScheduledRunResponse:
        """Create (or replace) a scheduled research job.

        The job is persisted immediately. No execution is triggered.
        """
        from src.scheduled_research.models import (
            JobStatus,
            ScheduledResearchJob,
            validate_schedule,
        )

        try:
            validate_schedule(request.schedule)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        now_ms = int(time.time() * 1000)
        job_id = request.id or str(uuid.uuid4())
        # Replacing an existing job (the UI "edit" path) must not reset its
        # next-run to now: that would fire the task immediately. Preserve the
        # existing schedule position unless the caller overrides it explicitly.
        existing = _get_scheduled_research_store().get(job_id) if request.id else None
        next_run_at = (
            request.next_run_at
            if request.next_run_at is not None
            else (existing.next_run_at if existing is not None else now_ms)
        )
        job = ScheduledResearchJob(
            id=job_id,
            prompt=request.prompt,
            schedule=request.schedule,
            next_run_at=next_run_at,
            status=JobStatus.PENDING,
            created_at=now_ms,
            config=request.config,
        )
        _get_scheduled_research_store().upsert(job)
        return ScheduledRunResponse(**job.to_dict())

    @app.get(
        "/scheduled-runs",
        response_model=List[ScheduledRunResponse],
        dependencies=[Depends(require_auth)],
    )
    async def list_scheduled_runs(
        status_filter: Optional[str] = Query(None, alias="status"),
        limit: int = Query(50, ge=1, le=200),
    ) -> List[ScheduledRunResponse]:
        """List scheduled research jobs, optionally filtered by status."""
        jobs = _get_scheduled_research_store().list_jobs(
            status=status_filter, limit=limit
        )
        return [ScheduledRunResponse(**j.to_dict()) for j in jobs]

    @app.get(
        "/scheduled-runs/available-channels",
        response_model=List[Dict[str, Any]],
        dependencies=[Depends(require_auth)],
    )
    async def list_available_channels() -> List[Dict[str, Any]]:
        """List configured-and-enabled channels a job can deliver results to."""
        return _available_delivery_channels()

    @app.delete(
        "/scheduled-runs/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_auth)],
    )
    async def delete_scheduled_run(job_id: str) -> None:
        """Cancel (delete) a scheduled research job by id."""
        _host_validate_path_param(job_id, "job_id")
        removed = _get_scheduled_research_store().delete(job_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail=f"scheduled run {job_id} not found"
            )
