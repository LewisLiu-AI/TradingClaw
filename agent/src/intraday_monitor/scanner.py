"""Intraday minute-level volume-surge detection over a fixed watch basket.

The rule encoded here was calibrated on the 2026-11-04 SMIC (688981) session:
a genuine sustained surge is *consecutive* minute bars trading well above the
recent baseline (the 13:00 reopening spike was a single-bar pulse and must not
fire), confirmed by price breaking the session high. Concretely, a signal
requires ``min_consecutive`` adjacent minute bars each trading at least
``surge_multiple / 2`` × the **median** turnover of the ``baseline_bars`` bars
right before the run, with the run's last bar at ``surge_multiple`` × that
median and closing above the session high built before the run. The median
(rather than the mean) keeps a lone reopening spike inside the baseline window
from inflating the reference level, and the split thresholds match how a real
surge builds: on 11/04 the first bar printed ~2.7× and the second ~5× the
~14M-CNY midday median. The run's first bar must fall outside the opening-pulse
windows (09:30–09:34 and 13:00–13:04) so reopen spikes are filtered out.

Bars come from :func:`backtest.loaders.eastmoney_client.fetch_kline` with
``klt=1``; each carries ``{trade_date, open, high, low, close, volume,
amount}`` with ``trade_date`` shaped ``"YYYY-MM-DD HH:MM"`` for minute bars.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Sequence

logger = logging.getLogger(__name__)

# Opening-pulse windows (inclusive HH:MM bounds). A surge run whose *first*
# bar falls inside one of these is the reopen/auction spike, not a signal.
_PULSE_WINDOWS = (("09:30", "09:34"), ("13:00", "13:04"))

# How many trailing bars a scan still considers — with a 5-minute scan cadence
# the run may have started a few minutes before the scan ticked.
_LOOKBACK_BARS = 8

DEFAULT_SURGE_MULTIPLE = 4.0
DEFAULT_BASELINE_BARS = 30
DEFAULT_MIN_CONSECUTIVE = 2

# Default core basket: semiconductors, other STAR-50 heavyweights, CATL, PCB,
# plus two broker bellwethers as the layer-3 style confirmation (a broker
# volume surge alongside tech is the classic incremental-money tell).
# Values are Vibe-Trading symbols; sector powers the board-level escalation.
DEFAULT_BASKET: dict[str, str] = {
    "688981.SH": ("中芯国际", "半导体"),
    "002371.SZ": ("北方华创", "半导体"),
    "688256.SH": ("寒武纪", "半导体"),
    "688041.SH": ("海光信息", "半导体"),
    "688012.SH": ("中微公司", "半导体"),
    "688111.SH": ("金山办公", "科创50权重"),
    "688008.SH": ("澜起科技", "科创50权重"),
    "688036.SH": ("传音控股", "科创50权重"),
    "300750.SZ": ("宁德时代", "电池"),
    "002463.SZ": ("沪电股份", "PCB"),
    "300476.SZ": ("胜宏科技", "PCB"),
    "002916.SZ": ("深南电路", "PCB"),
    "600183.SH": ("生益科技", "PCB"),
    "002384.SZ": ("东山精密", "PCB"),
    "600030.SH": ("中信证券", "券商"),
    "300059.SZ": ("东方财富", "券商"),
}

# A same-sector signal count at or above this escalates to a board-level alert.
BOARD_SIGNAL_THRESHOLD = 3


@dataclass(frozen=True)
class SurgeSignal:
    """One detected sustained volume surge on a basket symbol."""

    symbol: str
    name: str
    sector: str
    time_label: str  # HH:MM of the run's last bar
    ratio: float  # run-bar turnover vs baseline mean, in multiples
    close: float
    prev_session_high: float

    def describe(self) -> str:
        head = f"[{self.sector}] {self.name}({self.symbol})"
        return (
            f"{head} {self.time_label} 持续放量 "
            f"{self.ratio:.1f}倍于近{DEFAULT_BASELINE_BARS}分钟均值，"
            f"现价 {self.close:.2f} 突破盘中前高 {self.prev_session_high:.2f}"
        )


def _time_label(bar: dict) -> str:
    """Return the ``HH:MM`` part of a minute bar's ``trade_date``."""
    return bar["trade_date"][-5:]


def _in_pulse_window(label: str) -> bool:
    return any(low <= label <= high for low, high in _PULSE_WINDOWS)


def detect_surge(
    bars: Sequence[dict],
    *,
    surge_multiple: float = DEFAULT_SURGE_MULTIPLE,
    baseline_bars: int = DEFAULT_BASELINE_BARS,
    min_consecutive: int = DEFAULT_MIN_CONSECUTIVE,
) -> SurgeSignal | None:
    """Return the strongest sustained surge whose run ends in the last bars.

    Args:
        bars: Today's ascending minute bars (``amount`` in CNY, ``trade_date``
            ending in ``HH:MM``). At least ``baseline_bars + min_consecutive``
            bars are needed for a meaningful baseline.
        surge_multiple: Turnover multiple over the baseline mean a bar must
            reach to count as part of the surge run.
        baseline_bars: Size of the rolling turnover-baseline window taken
            immediately before each candidate run.
        min_consecutive: Adjacent qualifying bars required for a signal.

    Returns:
        The qualifying run (highest ratio) whose last bar lies within the last
        ``_LOOKBACK_BARS`` bars, or ``None`` when no run qualifies.
    """
    if len(bars) < baseline_bars + min_consecutive:
        return None

    best: SurgeSignal | None = None
    # Only runs whose last bar sits within the recent lookback window count —
    # older surges were (or should have been) reported by an earlier scan.
    min_last_index = len(bars) - _LOOKBACK_BARS
    for start in range(baseline_bars, len(bars) - min_consecutive + 1):
        if start + min_consecutive - 1 < min_last_index:
            continue
        first = bars[start]
        if _in_pulse_window(_time_label(first)):
            continue
        baseline = statistics.median(
            bar["amount"] for bar in bars[start - baseline_bars : start]
        )
        if baseline <= 0:
            continue
        run = bars[start : start + min_consecutive]
        if any(bar["amount"] < (surge_multiple / 2) * baseline for bar in run):
            continue
        last = run[-1]
        if last["amount"] < surge_multiple * baseline:
            continue
        prev_session_high = max(bar["high"] for bar in bars[:start])
        if last["close"] <= prev_session_high:
            continue
        ratio = last["amount"] / baseline
        signal = SurgeSignal(
            symbol="",
            name="",
            sector="",
            time_label=_time_label(last),
            ratio=ratio,
            close=last["close"],
            prev_session_high=prev_session_high,
        )
        if best is None or signal.ratio > best.ratio:
            best = signal
    return best


def annotate(signal: SurgeSignal, symbol: str, name: str, sector: str) -> SurgeSignal:
    """Fill a detected signal's symbol identity fields."""
    return SurgeSignal(
        symbol=symbol,
        name=name,
        sector=sector,
        time_label=signal.time_label,
        ratio=signal.ratio,
        close=signal.close,
        prev_session_high=signal.prev_session_high,
    )


def format_alert(signals: Sequence[SurgeSignal], scan_time: str) -> str | None:
    """Render a Feishu alert text, or ``None`` when nothing to report.

    Same-sector signals at :data:`BOARD_SIGNAL_THRESHOLD` or more are promoted
    to a board-level header line.
    """
    if not signals:
        return None
    sector_counts: dict[str, list[SurgeSignal]] = {}
    for signal in signals:
        sector_counts.setdefault(signal.sector, []).append(signal)
    board_lines = [
        f"🚀 板块级信号：{sector} {len(group)}只权重同时放量"
        for sector, group in sorted(sector_counts.items())
        if len(group) >= BOARD_SIGNAL_THRESHOLD
    ]
    lines = [f"📢 盘中放量异动 · {scan_time}"]
    lines.extend(board_lines)
    lines.extend(f"· {signal.describe()}" for signal in signals)
    lines.append("（研究监控，非交易指令）")
    return "\n".join(lines)
