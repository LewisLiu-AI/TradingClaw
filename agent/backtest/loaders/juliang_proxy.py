"""Reusable Juliang (巨量) dynamic-proxy pool for Eastmoney quote access.

Eastmoney's realtime/history quote hosts (``push2`` / ``push2his``) WAF-block
non-whitelisted IPs, which makes every Eastmoney-backed tool (fund flow,
northbound, dragon-tiger, sector, margin, ...) fail from a datacenter IP. A
Juliang dynamic proxy — a short-lived Chinese residential/ADSL IP — is accepted
by Eastmoney, so routing those requests through it unblocks the tools.

Each extracted proxy IP lives only 30-60 seconds, and every extraction consumes
one unit of a fixed quota. This module therefore pools a single proxy: it keeps
one live entry and reuses it for every request until it is about to expire or a
request through it fails, and only then extracts a replacement. Quota
conservation is the point of the pooling — an analysis pass typically fans out
to several Eastmoney endpoints within a few seconds, so one proxy should serve
the whole pass.

Read-only: no request here reaches a trading endpoint. Config comes from the
typed env schema (``DataConfig.juliang_*``) so the Settings UI can hot-reload it
via ``reset_env_config()``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Juliang dynamic-proxy extraction endpoint. ``result_type=json`` carries both
# the proxy list and the remaining quota (``surplus_quantity``) in one response.
_EXTRACTION_URL = "http://v2.api.juliangip.com/dynamic/getips"

# Safety margin subtracted from the provider's 30-60s IP lifetime so a proxy is
# discarded *before* it actually expires, never after.
_SAFETY_MARGIN_S = 5.0

_DEFAULT_TIMEOUT_S = 15.0

# Juliang env keys injected from ``agent/.env`` as a fallback when another
# dotenv file (e.g. ``~/.vibe-trading/.env``) shadows it during startup.
_JULIANG_ENV_KEYS = (
    "VIBE_TRADING_JULIANG_ENABLED",
    "VIBE_TRADING_JULIANG_TRADE_NO",
    "VIBE_TRADING_JULIANG_API_KEY",
    "VIBE_TRADING_JULIANG_USERNAME",
    "VIBE_TRADING_JULIANG_PASSWORD",
    "VIBE_TRADING_JULIANG_QUOTA_ALERT_THRESHOLD",
    "VIBE_TRADING_JULIANG_QUOTA_ALERT_MIN_INTERVAL_H",
    "VIBE_TRADING_JULIANG_QUOTA_ALERT_INTERVAL_S",
)


def _agent_env_path() -> Path:
    """Return ``agent/.env`` (this file lives at agent/backtest/loaders/)."""
    return Path(__file__).resolve().parent.parent.parent / ".env"


def _inject_juliang_from_env_file() -> None:
    """Set any Juliang env keys present in ``agent/.env`` into ``os.environ``.

    ``_ensure_dotenv`` loads the first candidate that exists and may pick a
    shadowing file (``~/.vibe-trading/.env``) over ``agent/.env``. The Settings
    UI persists to ``agent/.env``, so this fallback makes that authoritative
    regardless of dotenv resolution order.
    """
    env_path = _agent_env_path()
    if not env_path.exists():
        return
    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in _JULIANG_ENV_KEYS:
            values[key] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        os.environ.setdefault(key, value)


@dataclass
class ProxyEntry:
    """One live Juliang proxy plus its auth and expiry bookkeeping."""

    host: str
    port: int
    username: str
    password: str
    expires_at: float  # time.monotonic() deadline
    extracted_at: float  # time.time() epoch, for display

    @property
    def host_port(self) -> str:
        return f"{self.host}:{self.port}"

    def proxies_dict(self) -> dict[str, str]:
        """Build the ``requests`` ``proxies`` mapping for this entry."""
        url = f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return {"http": url, "https": url}


class JuliangProxyClient:
    """Thread-safe single-proxy pool backed by the Juliang extraction API."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: ProxyEntry | None = None
        self._invalid = False
        self._surplus_quantity: int | None = None
        self._last_error: str | None = None
        self._last_extracted_at: float | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _config():
        """Read the active Juliang config from the typed env schema."""
        # Ensure agent/.env is in os.environ even if this module is used before
        # the LLM provider initialises (which normally loads dotenv on startup).
        try:
            from src.providers.llm import _ensure_dotenv

            _ensure_dotenv()
        except Exception:  # noqa: BLE001 - dotenv load is best-effort here
            pass
        from src.config.accessor import get_env_config, reset_env_config

        cfg = get_env_config().data
        if cfg.juliang_trade_no and cfg.juliang_api_key:
            return cfg
        # A shadowing dotenv file may have hidden agent/.env; inject its Juliang
        # keys directly so the Settings UI's persistence is always honoured.
        _inject_juliang_from_env_file()
        reset_env_config()
        return get_env_config().data

    def is_enabled(self) -> bool:
        cfg = self._config()
        return bool(cfg.juliang_enabled)

    def is_configured(self) -> bool:
        cfg = self._config()
        return bool(
            cfg.juliang_trade_no
            and cfg.juliang_api_key
            and cfg.juliang_username
            and cfg.juliang_password
        )

    # ------------------------------------------------------------------
    # Pool access
    # ------------------------------------------------------------------

    def get_proxy(self) -> ProxyEntry | None:
        """Return the live proxy, extracting a replacement only when needed.

        Reuses the current entry while it is valid and not marked invalid. A
        single analysis pass makes many Eastmoney calls within seconds, so this
        keeps them on one proxy and conserves the quota.
        """
        with self._lock:
            current = self._current
            if (
                current is not None
                and not self._invalid
                and time.monotonic() < current.expires_at - _SAFETY_MARGIN_S
            ):
                return current
            try:
                return self._extract_locked()
            except Exception as exc:  # noqa: BLE001 - surface as None, caller falls back to direct
                logger.warning("juliang proxy extraction failed: %s", exc)
                self._last_error = str(exc)
                return None

    def invalidate(self) -> None:
        """Mark the current proxy unusable so the next call re-extracts."""
        with self._lock:
            self._invalid = True

    def force_refresh(self) -> dict[str, Any]:
        """Extract a fresh proxy now (consumes one quota unit) and report status.

        Used by the Settings UI's "refresh quota" button.
        """
        with self._lock:
            try:
                self._extract_locked()
            except Exception as exc:  # noqa: BLE001 - report, do not raise across HTTP
                self._last_error = str(exc)
                logger.warning("juliang force_refresh failed: %s", exc)
        return self.status_locked()

    def reset(self) -> None:
        """Drop cached state so the next call re-reads config and re-extracts."""
        with self._lock:
            self._current = None
            self._invalid = False
            self._surplus_quantity = None
            self._last_error = None
            self._last_extracted_at = None

    # ------------------------------------------------------------------
    # Status (never consumes quota)
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.status_locked()

    def status_locked(self) -> dict[str, Any]:
        cfg = self._config()
        current = self._current
        now = time.monotonic()
        valid = (
            current is not None
            and not self._invalid
            and now < current.expires_at - _SAFETY_MARGIN_S
        )
        return {
            "configured": self.is_configured(),
            "enabled": self.is_enabled(),
            "surplus_quantity": self._surplus_quantity,
            "current_proxy": current.host_port if valid and current else None,
            "proxy_valid": valid,
            "proxy_valid_until": (
                int(current.expires_at) if valid and current else None
            ),
            "last_extracted_at": int(self._last_extracted_at) if self._last_extracted_at else None,
            "quota_alert_threshold": int(cfg.juliang_quota_alert_threshold or 0),
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _extract_locked(self) -> ProxyEntry:
        """Call the extraction API and store the fresh proxy.

        Caller must hold ``self._lock``.
        """
        cfg = self._config()
        if not self.is_enabled() or not self.is_configured():
            raise RuntimeError("juliang proxy is not enabled/configured")

        lifetime = float(cfg.juliang_proxy_lifetime_s or 45)
        try:
            resp = requests.get(
                _EXTRACTION_URL,
                params={
                    "trade_no": cfg.juliang_trade_no,
                    "key": cfg.juliang_api_key,
                    "num": 1,
                    "pt": 1,
                    "result_type": "json",
                    "split": 1,
                    "auto_white": 1,
                },
                timeout=_DEFAULT_TIMEOUT_S,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - normalized to RuntimeError
            raise RuntimeError(f"juliang extraction HTTP error: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("code") != 200:
            raise RuntimeError(f"juliang extraction rejected: {payload.get('msg') if isinstance(payload, dict) else payload}")

        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        proxy_list = data.get("proxy_list")
        if not isinstance(proxy_list, list) or not proxy_list:
            raise RuntimeError("juliang extraction returned no proxy")

        raw = proxy_list[0]
        if isinstance(raw, dict):
            host = str(raw.get("ip") or "")
            port_raw = raw.get("port")
        else:
            host, _, port_raw = str(raw).partition(":")
        try:
            port = int(port_raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"juliang extraction returned malformed proxy: {raw}") from exc
        if not host or port <= 0:
            raise RuntimeError(f"juliang extraction returned malformed proxy: {raw}")

        surplus = data.get("surplus_quantity")
        if surplus is not None:
            try:
                self._surplus_quantity = int(surplus)
            except (TypeError, ValueError):
                pass

        entry = ProxyEntry(
            host=host,
            port=port,
            username=cfg.juliang_username,
            password=cfg.juliang_password,
            expires_at=time.monotonic() + lifetime,
            extracted_at=time.time(),
        )
        self._current = entry
        self._invalid = False
        self._last_error = None
        self._last_extracted_at = entry.extracted_at
        logger.info(
            "juliang proxy extracted %s (surplus=%s, lifetime=%.0fs)",
            entry.host_port,
            self._surplus_quantity,
            lifetime,
        )
        return entry


# Process-wide singleton shared by the Eastmoney client and the Settings API.
_client = JuliangProxyClient()


def get_juliang_client() -> JuliangProxyClient:
    """Return the process-wide Juliang proxy client."""
    return _client
