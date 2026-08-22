"""Background Feishu alert when the Juliang proxy quota runs low.

The Juliang pool's ``surplus_quantity`` is only refreshed when a proxy is
extracted (there is no standalone quota-query endpoint), so this watcher polls
the pooled client's cached status on a fixed interval and sends a Feishu alert
once the remaining quota drops below the configured threshold. Alerts are
rate-limited (default once per 24h) so a low-quota state does not spam.

Mounting: ``agent/api_server.py`` startup/shutdown hooks start/stop the watcher
only when the Juliang proxy is enabled. Delivery reuses the same channel-runtime
session-map + ``publish_outbound`` path as scheduled-research results, so any
Feishu chat that has paired with the bot receives the alert.
"""

from __future__ import annotations

import asyncio
import logging
import sys as _sys
import time

logger = logging.getLogger(__name__)

# In-memory last-alert timestamp (``time.monotonic()``). Reset on restart is
# acceptable — a low-quota state will simply alert again after a fresh start.
_last_alert_at = 0.0


def _host():
    return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")


async def _send_feishu_alert(host, text: str) -> None:
    """Publish ``text`` to every Feishu chat bound in the channel runtime."""
    runtime = host._get_channel_runtime() if hasattr(host, "_get_channel_runtime") else None
    if runtime is None or getattr(runtime, "bus", None) is None:
        logger.info("juliang quota alert skipped: channel runtime not available")
        return
    from src.channels.bus.events import OutboundMessage

    session_map = getattr(runtime, "_session_map", None) or {}
    targets = [key for key in session_map if key.partition(":")[0] == "feishu"]
    if not targets:
        logger.info("juliang quota alert skipped: no feishu chats bound")
        return
    for key in targets:
        _, sep, chat_id = key.partition(":")
        if not sep:
            continue
        await runtime.bus.publish_outbound(
            OutboundMessage(channel="feishu", chat_id=chat_id, content=text)
        )
        logger.info("juliang quota alert queued for feishu:%s", chat_id)


async def _quota_watch_loop(host, interval_s: int) -> None:
    """Poll the Juliang pool status and alert when the quota is low."""
    from backtest.loaders.juliang_proxy import get_juliang_client
    from src.config.accessor import get_env_config

    global _last_alert_at  # noqa: PLW0603
    while True:
        try:
            client = get_juliang_client()
            if client.is_enabled() and client.is_configured():
                status = client.status()
                surplus = status.get("surplus_quantity")
                cfg = get_env_config().data
                threshold = int(cfg.juliang_quota_alert_threshold or 1000)
                min_interval_h = int(cfg.juliang_quota_alert_min_interval_h or 24)
                if (
                    surplus is not None
                    and int(surplus) < threshold
                    and time.monotonic() - _last_alert_at >= min_interval_h * 3600
                ):
                    _last_alert_at = time.monotonic()
                    text = (
                        "⚠️ 巨量代理余量预警\n"
                        f"当前剩余: {surplus} 条\n"
                        f"预警阈值: {threshold} 条\n"
                        "余量不足会影响东财资金流等功能的可用性,请及时续费。"
                    )
                    await _send_feishu_alert(host, text)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a bad tick must not kill the watcher
            logger.error("juliang quota watch tick failed", exc_info=True)
        await asyncio.sleep(interval_s)


class JuliangQuotaWatcher:
    """Owns the background quota-watch task."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        from backtest.loaders.juliang_proxy import get_juliang_client
        from src.config.accessor import get_env_config

        if not get_juliang_client().is_enabled():
            logger.info("juliang quota watcher not started: proxy disabled")
            return
        interval_s = int(get_env_config().data.juliang_quota_alert_interval_s or 3600)
        host = _host()
        if host is None:
            logger.warning("juliang quota watcher not started: api_server not loaded")
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(
            _quota_watch_loop(host, max(interval_s, 60)),
            name="juliang-quota-watch",
        )
        logger.info("juliang quota watcher started (interval=%ss)", interval_s)

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None
