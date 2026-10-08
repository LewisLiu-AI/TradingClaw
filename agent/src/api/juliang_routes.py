"""Juliang (巨量) dynamic-proxy settings and status routes.

Mounted by ``agent/api_server.py`` via ``app.include_router(juliang_router)``.

Credentials are persisted to ``agent/.env`` (same store as Tushare/LLM keys) and
pushed into ``os.environ`` + ``reset_env_config()`` so the runtime picks them up
immediately. Responses never echo the API key or password — only a configured
boolean.
"""

from __future__ import annotations

import os
import sys as _sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backtest.loaders.juliang_proxy import get_juliang_client
from src.config.accessor import reset_env_config

juliang_router = APIRouter()
_security = HTTPBearer(auto_error=False)

# Env keys managed by this module (mirrors ``DataConfig`` aliases).
KEY_ENABLED = "VIBE_TRADING_JULIANG_ENABLED"
KEY_TRADE_NO = "VIBE_TRADING_JULIANG_TRADE_NO"
KEY_API_KEY = "VIBE_TRADING_JULIANG_API_KEY"
KEY_USERNAME = "VIBE_TRADING_JULIANG_USERNAME"
KEY_PASSWORD = "VIBE_TRADING_JULIANG_PASSWORD"
KEY_THRESHOLD = "VIBE_TRADING_JULIANG_QUOTA_ALERT_THRESHOLD"

_ALL_KEYS = (KEY_ENABLED, KEY_TRADE_NO, KEY_API_KEY, KEY_USERNAME, KEY_PASSWORD, KEY_THRESHOLD)

# Documented placeholders that count as "not configured".
_PLACEHOLDERS = {
    "",
    "your-trade-no",
    "your-juliang-api-key",
    "your-username",
    "your-password",
    "xxx",
}


# ---------------------------------------------------------------------------
# Host access helpers
# ---------------------------------------------------------------------------


def _host():
    return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")


async def _require_auth(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    await _host().require_auth(request, cred)


async def _require_settings_write_auth(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    await _host().require_settings_write_auth(request, cred)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class JuliLangProxySettingsResponse(BaseModel):
    """Redacted Juliang proxy settings for the Settings UI."""

    enabled: bool
    trade_no_configured: bool
    api_key_configured: bool
    username: str
    password_configured: bool
    quota_alert_threshold: int
    env_path: str


class UpdateJuliLangProxySettingsRequest(BaseModel):
    """Update Juliang proxy credentials. Blank field = keep the stored value."""

    enabled: bool | None = None
    trade_no: str | None = None
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    quota_alert_threshold: int | None = Field(default=None, ge=1)
    clear_trade_no: bool = False
    clear_api_key: bool = False
    clear_username: bool = False
    clear_password: bool = False


class JuliLangProxyStatusResponse(BaseModel):
    """Cached proxy-pool status (never consumes quota)."""

    configured: bool
    enabled: bool
    surplus_quantity: int | None
    current_proxy: str | None
    proxy_valid: bool
    proxy_valid_until: int | None
    last_extracted_at: int | None
    quota_alert_threshold: int
    last_error: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_env_values() -> dict[str, str]:
    host = _host()
    env_path = host.ENV_PATH
    if env_path.exists():
        return host._read_env_values(env_path)
    return {}


def _is_set(value: str) -> bool:
    host = _host()
    return host._is_configured_secret(value, _PLACEHOLDERS)


def _settings_response(values: dict[str, str] | None = None) -> JuliLangProxySettingsResponse:
    host = _host()
    env_values = values if values is not None else _read_env_values()
    return JuliLangProxySettingsResponse(
        enabled=env_values.get(KEY_ENABLED, "").strip().lower() in {"1", "true", "yes", "on"},
        trade_no_configured=_is_set(env_values.get(KEY_TRADE_NO, "")),
        api_key_configured=_is_set(env_values.get(KEY_API_KEY, "")),
        username=env_values.get(KEY_USERNAME, ""),
        password_configured=_is_set(env_values.get(KEY_PASSWORD, "")),
        quota_alert_threshold=host._coerce_int(
            env_values.get(KEY_THRESHOLD, "1000"), 1000
        ),
        env_path=host._project_relative_path(host.ENV_PATH),
    )


def _status_response() -> JuliLangProxyStatusResponse:
    status = get_juliang_client().status()
    return JuliLangProxyStatusResponse(
        configured=bool(status.get("configured")),
        enabled=bool(status.get("enabled")),
        surplus_quantity=status.get("surplus_quantity"),
        current_proxy=status.get("current_proxy"),
        proxy_valid=bool(status.get("proxy_valid")),
        proxy_valid_until=status.get("proxy_valid_until"),
        last_extracted_at=status.get("last_extracted_at"),
        quota_alert_threshold=int(status.get("quota_alert_threshold") or 0),
        last_error=status.get("last_error"),
    )


def _sync_os_environ(updates: dict[str, str]) -> None:
    """Apply saved values to the running process and rebuild env config."""
    for key, value in updates.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    reset_env_config()
    get_juliang_client().reset()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@juliang_router.get(
    "/settings/juliang-proxy",
    response_model=JuliLangProxySettingsResponse,
    dependencies=[Depends(_require_auth)],
)
async def get_juliang_proxy_settings() -> JuliLangProxySettingsResponse:
    """Return redacted Juliang proxy settings."""
    return _settings_response()


@juliang_router.put(
    "/settings/juliang-proxy",
    response_model=JuliLangProxySettingsResponse,
    dependencies=[Depends(_require_settings_write_auth)],
)
async def put_juliang_proxy_settings(
    payload: UpdateJuliLangProxySettingsRequest,
) -> JuliLangProxySettingsResponse:
    """Persist Juliang proxy settings and hot-apply them to the runtime."""
    host = _host()
    current = _read_env_values()
    updates: dict[str, str] = {}

    if payload.enabled is not None:
        updates[KEY_ENABLED] = "1" if payload.enabled else "0"

    for key, value, clear in (
        (KEY_TRADE_NO, payload.trade_no, payload.clear_trade_no),
        (KEY_API_KEY, payload.api_key, payload.clear_api_key),
        (KEY_USERNAME, payload.username, payload.clear_username),
        (KEY_PASSWORD, payload.password, payload.clear_password),
    ):
        if clear:
            updates[key] = ""
        elif value is not None and value.strip():
            updates[key] = value.strip()
        elif key in current:
            updates[key] = current[key]

    if payload.quota_alert_threshold is not None:
        updates[KEY_THRESHOLD] = str(payload.quota_alert_threshold)

    if updates:
        host._write_env_values(host.ENV_PATH, updates)
        _sync_os_environ(updates)

    return _settings_response(host._read_env_values(host.ENV_PATH))


@juliang_router.get(
    "/settings/juliang-proxy/status",
    response_model=JuliLangProxyStatusResponse,
    dependencies=[Depends(_require_auth)],
)
async def get_juliang_proxy_status() -> JuliLangProxyStatusResponse:
    """Return the cached proxy-pool status (quota, live proxy, validity).

    This endpoint never extracts — it reads the last-known state from the pool,
    so it consumes no quota.
    """
    return _status_response()


@juliang_router.post(
    "/settings/juliang-proxy/refresh",
    response_model=JuliLangProxyStatusResponse,
    dependencies=[Depends(_require_settings_write_auth)],
)
async def post_juliang_proxy_refresh() -> JuliLangProxyStatusResponse:
    """Force-extract a fresh proxy now.

    Consumes one quota unit and updates the cached ``surplus_quantity``. Use
    sparingly — the status endpoint already reports the last-known quota without
    extracting.
    """
    client = get_juliang_client()
    if not client.is_configured():
        raise HTTPException(status_code=422, detail="Juliang proxy is not configured")
    client.force_refresh()
    return _status_response()
