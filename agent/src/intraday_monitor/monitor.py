"""Background intraday volume-surge monitor with Feishu alerts.

Every ``interval`` seconds during A-share trading hours the monitor fetches
1-minute bars for each basket symbol from Eastmoney (through the shared
throttled client) and runs :func:`detect_surge` over them. Triggering symbols
push one Feishu alert, then go into a 30-minute cooldown; a cooldown re-alert
only fires when the surge ratio at least doubles the alerted level (volume
acceleration, not repetition).

Mounting mirrors the Juliang quota watcher: ``agent/api_server.py``
startup/shutdown hooks start/stop the loop, gated by
``VIBE_TRADING_ENABLE_INTRADAY_MONITOR``; delivery reuses the channel-runtime
session-map + ``publish_outbound`` path, so any Feishu chat that has paired
with the bot receives alerts. ``VIBE_TRADING_INTRADAY_MONITOR_BASKET`` can
override the default basket as ``symbol:name:sector`` comma-separated entries.
"""

from __future__ import annotations

import asyncio
import logging
import sys as _sys
import time
from datetime import datetime
from typing import Awaitable, Callable, Mapping
from zoneinfo import ZoneInfo

from src.intraday_monitor.scanner import (
    DEFAULT_BASKET,
    SurgeSignal,
    annotate,
    detect_surge,
    format_alert,
)

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_INTERVAL_S = 300
DEFAULT_COOLDOWN_S = 30 * 60
_ESCALATION_MULTIPLE = 2.0

PushFn = Callable[[str], Awaitable[None]]
NowFn = Callable[[], float]


def _host():
    return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")


def in_trading_hours(now: datetime) -> bool:
    """Return whether *now* (Shanghai wall time) is inside a monitored session.

    Sessions are 09:35–11:30 and 13:05–15:00 on weekdays. The opening minutes
    of each session are deliberately excluded: reopen auction spikes are noise
    the surge rule already filters per-bar, and skipping them avoids firing a
    scan whose data is still settling. Holidays are not modelled — a scan on a
    holiday simply sees a stale/empty bar set and reports nothing.
    """
    if now.weekday() >= 5:
        return False
    hhmm = now.strftime("%H:%M")
    return "09:35" <= hhmm <= "11:30" or "13:05" <= hhmm <= "15:00"


async def _push_feishu(text: str) -> None:
    """Publish *text* to every Feishu chat bound in the channel runtime."""
    host = _host()
    runtime = host._get_channel_runtime() if host and hasattr(host, "_get_channel_runtime") else None
    if runtime is None or getattr(runtime, "bus", None) is None:
        logger.info("intraday monitor alert skipped: channel runtime not available")
        return
    from src.channels.bus.events import OutboundMessage

    session_map = getattr(runtime, "_session_map", None) or {}
    targets = [key for key in session_map if key.partition(":")[0] == "feishu"]
    if not targets:
        logger.info("intraday monitor alert skipped: no feishu chats bound")
        return
    for key in targets:
        _, sep, chat_id = key.partition(":")
        if not sep:
            continue
        await runtime.bus.publish_outbound(
            OutboundMessage(channel="feishu", chat_id=chat_id, content=text)
        )
        logger.info("intraday monitor alert queued for feishu:%s", chat_id)


class IntradayVolumeMonitor:
    """Polling loop that scans the basket and pushes surge alerts."""

    def __init__(
        self,
        *,
        basket: Mapping[str, tuple[str, str]] | None = None,
        interval_s: int = DEFAULT_INTERVAL_S,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        push_fn: PushFn | None = None,
        now_fn: NowFn = time.time,
        enabled: bool = True,
    ) -> None:
        self._basket = dict(basket or DEFAULT_BASKET)
        self._interval_s = interval_s
        self._cooldown_s = cooldown_s
        self._push = push_fn or _push_feishu
        self._now = now_fn
        self._enabled = enabled
        self._task: asyncio.Task | None = None
        self._stopping = False
        # symbol -> (alerted_at epoch s, alerted ratio)
        self._alert_state: dict[str, tuple[float, float]] = {}
        # Status surface for the Web UI status card.
        self._started_at: float | None = None
        self._last_scan_at: float | None = None
        self._last_scan_in_session = False
        # Newest-first alert history, capped for the status endpoint.
        self._alerts: list[dict] = []
        self._max_alerts = 20

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background loop. Idempotent; no-op when disabled."""
        if not self._enabled or self.is_running:
            return
        self._stopping = False
        self._started_at = self._now()
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name="intraday-volume-monitor")

    async def stop(self) -> None:
        """Stop the background loop. Idempotent."""
        task = self._task
        if task is None:
            return
        self._stopping = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            try:
                now = datetime.fromtimestamp(self._now(), _TZ)
                if in_trading_hours(now):
                    await self.scan_once(scan_time=now.strftime("%H:%M"))
                    await self._sleep(self._next_boundary_s())
                else:
                    await self._sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("intraday monitor scan failed", exc_info=True)
                await self._sleep(self._interval_s)

    def _next_boundary_s(self) -> float:
        """Seconds until the next ``interval``-aligned wall-clock boundary."""
        now = self._now()
        return self._interval_s - (now % self._interval_s) or self._interval_s

    async def _sleep(self, seconds: float) -> None:
        if not self._stopping:
            await asyncio.sleep(max(seconds, 1.0))

    async def scan_once(self, *, scan_time: str = "") -> list[SurgeSignal]:
        """Scan every basket symbol and push an alert for new signals.

        Returns the signals that fired this pass (post-cooldown). A symbol in
        cooldown re-alerts only when its surge ratio at least doubles the
        previously alerted ratio.
        """
        from backtest.loaders.eastmoney_client import fetch_kline, resolve_secid

        self._last_scan_at = self._now()
        today = datetime.fromtimestamp(self._now(), _TZ).strftime("%Y%m%d")
        fired: list[SurgeSignal] = []
        for symbol, (name, sector) in self._basket.items():
            try:
                secid = resolve_secid(symbol)
                if secid is None:
                    logger.warning("intraday monitor: unresolvable symbol %s", symbol)
                    continue
                bars = await asyncio.to_thread(
                    fetch_kline, secid, klt=1, beg=today, end=today
                )
            except Exception as exc:  # noqa: BLE001 - one symbol must not kill the scan
                logger.warning("intraday monitor fetch failed for %s: %s", symbol, exc)
                continue
            bars = [bar for bar in bars if bar["trade_date"][:10].replace("-", "") == today]
            signal = detect_surge(bars)
            if signal is None:
                continue
            signal = annotate(signal, symbol, name, sector)
            now_s = self._now()
            alerted = self._alert_state.get(symbol)
            if alerted is not None:
                alerted_at, alerted_ratio = alerted
                if now_s - alerted_at < self._cooldown_s:
                    if signal.ratio < alerted_ratio * _ESCALATION_MULTIPLE:
                        continue
            self._alert_state[symbol] = (now_s, signal.ratio)
            fired.append(signal)

        if fired:
            text = format_alert(fired, scan_time or datetime.now(_TZ).strftime("%H:%M"))
            stamped = scan_time or datetime.now(_TZ).strftime("%H:%M")
            for signal in fired:
                self._alerts.insert(0, {
                    "symbol": signal.symbol,
                    "name": signal.name,
                    "sector": signal.sector,
                    "time": stamped,
                    "ratio": round(signal.ratio, 1),
                    "close": signal.close,
                    "prev_session_high": signal.prev_session_high,
                })
            del self._alerts[self._max_alerts:]
            if text:
                try:
                    await self._push(text)
                except Exception:  # noqa: BLE001 - push failure must not kill the loop
                    logger.error("intraday monitor push failed", exc_info=True)
        return fired

    def status(self) -> dict:
        """Return a JSON-ready status snapshot for the Web UI card."""
        return {
            "running": self.is_running,
            "started_at": self._started_at,
            "interval_s": self._interval_s,
            "cooldown_s": self._cooldown_s,
            "in_trading_hours": in_trading_hours(
                datetime.fromtimestamp(self._now(), _TZ)
            ),
            "last_scan_at": self._last_scan_at,
            "basket": [
                {"symbol": symbol, "name": name, "sector": sector}
                for symbol, (name, sector) in sorted(self._basket.items())
            ],
            "alerts": list(self._alerts),
        }


# ---------------------------------------------------------------------------
# Module-level lifecycle (wired into api_server startup/shutdown)
# ---------------------------------------------------------------------------

_monitor: IntradayVolumeMonitor | None = None


def _basket_from_env(raw: str) -> dict[str, tuple[str, str]]:
    """Parse a ``symbol:name:sector,symbol:name:sector`` override string."""
    basket: dict[str, tuple[str, str]] = {}
    for entry in raw.split(","):
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) == 3 and all(parts):
            basket[parts[0]] = (parts[1], parts[2])
    return basket


def _monitor_enabled() -> bool:
    from src.config.accessor import get_env_config

    return bool(get_env_config().agent_tuning.vibe_trading_enable_intraday_monitor)


def start_intraday_monitor() -> None:
    """Start the monitor when ``VIBE_TRADING_ENABLE_INTRADAY_MONITOR`` is set."""
    global _monitor
    if not _monitor_enabled():
        return
    import os

    from src.config.accessor import get_env_config

    tuning = get_env_config().agent_tuning
    basket_override = os.environ.get("VIBE_TRADING_INTRADAY_MONITOR_BASKET", "").strip()
    basket = _basket_from_env(basket_override) or DEFAULT_BASKET
    interval = int(tuning.vibe_trading_intraday_monitor_interval_s or DEFAULT_INTERVAL_S)
    _monitor = IntradayVolumeMonitor(basket=basket, interval_s=interval)
    _monitor.start()
    logger.info("intraday volume monitor started (%d symbols, %ds interval)", len(basket), interval)


async def stop_intraday_monitor() -> None:
    """Stop the monitor if it was started."""
    if _monitor is not None:
        await _monitor.stop()


def intraday_monitor_status() -> dict:
    """Status snapshot for ``GET /intraday-monitor/status``.

    Always reports ``enabled`` so the UI can distinguish "off" from "down".
    """
    if _monitor is None:
        return {"enabled": False}
    return {"enabled": True, **_monitor.status()}
