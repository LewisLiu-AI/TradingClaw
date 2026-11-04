"""Fund-flow continuity detection for the intraday monitor (layer 3).

The layer-3 style confirmation answers "is the big money still accumulating?"
rather than "is price surging right now?". The rule: a symbol qualifies when
its main-force net inflow (主力净额) has been positive for at least
``min_days`` **consecutive** daily rows — the latest row being the current
session's running total — and today's super-large-order net inflow is also
positive (the 2026-11-04 SMIC pattern: 3 straight days of main-force inflow
with the super-large bucket turning positive on day 3).

Rows come from :func:`src.tools.fund_flow_tool._fetch_symbol_flow` with
``period="daily"``; each carries ``{timestamp, main, small, medium, large,
super_large}`` in CNY. Row order is normalised here, so callers may pass the
payload in either direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

DEFAULT_MIN_DAYS = 3


@dataclass(frozen=True)
class InflowSignal:
    """One symbol's confirmed multi-day main-force accumulation."""

    days: int  # consecutive positive-main rows including today
    today_main: float
    today_super_large: float
    last_date: str  # timestamp of the latest row (today during a session)


def detect_inflow_continuity(
    rows: Sequence[dict],
    *,
    min_days: int = DEFAULT_MIN_DAYS,
) -> InflowSignal | None:
    """Return the accumulation signal when the continuity rule holds.

    Args:
        rows: Daily fund-flow rows (any order; sorted by ``timestamp`` here).
        min_days: Required consecutive positive main-force days, the latest
            row counting as the current (possibly partial) session.

    Returns:
        An :class:`InflowSignal` when the last ``min_days`` rows all carry a
        positive main bucket and the latest row's super-large bucket is also
        positive; ``None`` otherwise. Degenerate/empty rows never qualify.
    """
    ordered = sorted(
        (row for row in rows if row.get("timestamp")),
        key=lambda row: str(row["timestamp"]),
    )
    if len(ordered) < min_days:
        return None
    tail = ordered[-min_days:]
    if any((row.get("main") or 0.0) <= 0 for row in tail):
        return None
    latest = ordered[-1]
    today_super = latest.get("super_large") or 0.0
    if today_super <= 0:
        return None
    days = 0
    for row in reversed(ordered):
        if (row.get("main") or 0.0) <= 0:
            break
        days += 1
    return InflowSignal(
        days=days,
        today_main=latest.get("main") or 0.0,
        today_super_large=today_super,
        last_date=str(latest["timestamp"]),
    )


def format_inflow_alert(signals: Sequence[tuple[str, str, InflowSignal]], scan_time: str) -> str:
    """Render the Feishu alert for confirmed accumulation symbols.

    Each entry is ``(symbol, name, signal)``; amounts print in 亿元.
    """
    if not signals:
        return ""
    lines = [f"💰 资金面确认 · 主力连续净流入 · {scan_time}"]
    for symbol, name, signal in signals:
        lines.append(
            f"· {name}({symbol}) 主力连续 {signal.days} 日净流入，"
            f"今日主力 +{signal.today_main / 1e8:.2f}亿 / 超大单 +{signal.today_super_large / 1e8:.2f}亿"
        )
    lines.append("（研究监控，非交易指令）")
    return "\n".join(lines)
