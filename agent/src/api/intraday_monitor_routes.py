"""Intraday volume-surge monitor status route.

Mounted by ``agent/api_server.py`` via ``register_intraday_monitor_routes``.
Read-only: the monitor's lifecycle is env-gated and process-managed, so the
endpoint only reports status (running state, basket, last scan, recent alerts)
for the Web UI status card.
"""

from __future__ import annotations

import sys as _sys
from typing import Any, Dict

from fastapi import APIRouter, Depends, FastAPI


def register_intraday_monitor_routes(
    app: FastAPI,
    require_auth=None,
) -> None:
    """Mount the intraday-monitor status route onto ``app``."""
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if require_auth is None:
        if host is None:
            raise RuntimeError(
                "register_intraday_monitor_routes: api_server module not in "
                "sys.modules; ensure api_server is imported first"
            )
        require_auth = host.require_auth

    router = APIRouter(dependencies=[Depends(require_auth)])

    @router.get("/intraday-monitor/status")
    async def intraday_monitor_status() -> Dict[str, Any]:
        """Status snapshot: enabled/running, basket, last scan, recent alerts."""
        from src.intraday_monitor.monitor import intraday_monitor_status

        return intraday_monitor_status()

    app.include_router(router)
