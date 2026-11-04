"""Unit tests for the intraday volume-surge scanner and monitor.

The canonical fixture mirrors the 2026-11-04 SMIC (688981) afternoon session:
a quiet morning, a single 13:00 reopening pulse (must NOT trigger), a calm
13:01–13:28 stretch, then the sustained 13:29–13:30 surge that broke the
session high (must trigger). Bars are synthetic but keep that session's
turnover ratios.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.intraday_monitor.fundflow import detect_inflow_continuity, format_inflow_alert
from src.intraday_monitor.monitor import IntradayVolumeMonitor, in_trading_hours
from src.intraday_monitor.scanner import (
    DEFAULT_BASKET,
    detect_surge,
    format_alert,
)


def _bar(time_label: str, amount: float, close: float, high: float | None = None) -> dict:
    return {
        "trade_date": f"2026-11-04 {time_label}",
        "open": close,
        "high": high if high is not None else close,
        "low": close,
        "close": close,
        "volume": amount / 100.0,
        "amount": amount,
    }


def _minute_labels(count: int, *, start: tuple[int, int] = (9, 30)) -> list[str]:
    """Generate consecutive HH:MM labels skipping the lunch break."""
    labels: list[str] = []
    hh, mm = start
    for _ in range(count):
        labels.append(f"{hh:02d}:{mm:02d}")
        mm += 1
        if mm == 60:
            hh, mm = hh + 1, 0
        if (hh, mm) == (11, 30):
            hh, mm = 13, 0
    return labels


def _smic_session() -> list[dict]:
    """Build the 11/04-style session up to 13:31 (incl. the 13:29+ surge)."""
    labels = _minute_labels(152)  # 09:30–11:29 (120) + 13:00–13:31 (32)
    bars: list[dict] = []
    price = 101.5
    for index, label in enumerate(labels):
        if label == "13:00":
            # Reopening pulse: one huge bar, immediately collapsing. This is
            # exactly the trap the pulse-window filter must neutralise.
            bars.append(_bar(label, 89_600_000, price))
            continue
        if label >= "13:29":
            # Sustained surge: first bar ~2.5x, confirm bar ~5x the median
            # baseline, mirroring the real 13:29/13:30 build-up.
            price += 0.4
            amount = 50_000_000 if label == "13:29" else 100_000_000
            bars.append(_bar(label, amount, price, high=price))
            continue
        if label >= "11:09":
            # Late-morning drift up on modest volume.
            price += 0.02
            bars.append(_bar(label, 20_000_000, price))
            continue
        # Quiet morning baseline.
        bars.append(_bar(label, 12_000_000, price))
    return bars


def test_sustained_afternoon_surge_triggers():
    signal = detect_surge(_smic_session())
    assert signal is not None
    assert signal.time_label >= "13:29"
    assert signal.ratio >= 4.0
    assert signal.close > signal.prev_session_high


def test_single_reopen_pulse_does_not_trigger():
    bars = _smic_session()
    # Cut the session right after 13:00 so only the pulse exists.
    pulse_only = [bar for bar in bars if bar["trade_date"] <= "2026-11-04 13:28"]
    assert detect_surge(pulse_only) is None


def test_surge_without_new_high_does_not_trigger():
    bars = _smic_session()
    for bar in bars:
        if bar["trade_date"] >= "2026-11-04 13:29":
            # Same huge turnover, but price flat under the session high.
            bar["close"] = 101.0
            bar["high"] = 101.0
    assert detect_surge(bars) is None


def test_short_history_does_not_trigger():
    bars = [_bar(label, 100_000_000, 10.0 + i) for i, label in enumerate(_minute_labels(10))]
    assert detect_surge(bars) is None


def test_old_surge_outside_lookback_not_reported():
    bars = _smic_session()
    # Append 10 quiet bars after the surge so it slides out of the window.
    price = bars[-1]["close"]
    for label in _minute_labels(10, start=(13, 32)):
        bars.append(_bar(label, 12_000_000, price))
    assert detect_surge(bars) is None


def test_format_alert_board_escalation():
    signals = []
    for symbol, (name, _) in DEFAULT_BASKET.items():
        base = detect_surge(_smic_session())
        from src.intraday_monitor.scanner import annotate

        signals.append(annotate(base, symbol, name, "半导体"))
    text = format_alert(signals, "13:35")
    assert "板块级信号：半导体" in text
    assert "非交易指令" in text


class _FakeClock:
    """Fixed wall clock advancing 1s per call (Shanghai timezone)."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> float:
        self._now = self._now.fromtimestamp(self._now.timestamp() + 1, self._now.tzinfo)
        return self._now.timestamp()


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2026-11-04 10:00", True),
        ("2026-11-04 09:31", False),  # pre-open
        ("2026-11-04 11:45", False),  # lunch
        ("2026-11-04 13:30", True),
        ("2026-11-04 15:10", False),  # after close
        ("2026-11-07 10:00", False),  # Saturday
    ],
)
def test_in_trading_hours(stamp: str, expected: bool):
    from zoneinfo import ZoneInfo

    moment = datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    assert in_trading_hours(moment) is expected


def test_monitor_scan_cooldown_and_escalation(monkeypatch: pytest.MonkeyPatch):
    """Alert fires once, stays quiet in cooldown, re-alerts on 2x surge."""
    import asyncio

    from src.intraday_monitor import monitor as monitor_mod

    session = _smic_session()

    def fake_fetch(secid, *, klt, beg, end):  # noqa: ANN001
        return list(session)

    def fake_resolve(symbol):  # noqa: ANN001
        return f"fake.{symbol}"

    pushed: list[str] = []

    async def _push_feishu(text: str) -> None:
        pushed.append(text)

    clock = _FakeClock(datetime.fromisoformat("2026-11-04 13:35").replace(
        tzinfo=monitor_mod._TZ
    ))
    mon = IntradayVolumeMonitor(
        basket={"688981.SH": ("中芯国际", "半导体")},
        push_fn=_push_feishu,
        now_fn=clock,
    )

    import backtest.loaders.eastmoney_client as ec

    monkeypatch.setattr(ec, "fetch_kline", fake_fetch)
    monkeypatch.setattr(ec, "resolve_secid", fake_resolve)

    async def _scenario() -> None:
        fired = await mon.scan_once()
        assert len(fired) == 1 and fired[0].symbol == "688981.SH"
        assert len(pushed) == 1

        # Same surge within cooldown: suppressed.
        assert await mon.scan_once() == []
        assert len(pushed) == 1

        # Volume doubles (ratio 2x): escalation re-alerts.
        for bar in session:
            if bar["trade_date"] >= "2026-11-04 13:29":
                bar["amount"] *= 2.5
        fired = await mon.scan_once()
        assert len(fired) == 1 and len(pushed) == 2

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Layer 3: fund-flow continuity
# ---------------------------------------------------------------------------


def _flow_row(date: str, main: float, super_large: float) -> dict:
    return {
        "timestamp": date,
        "main": main,
        "small": -main / 2,
        "medium": -main / 4,
        "large": main / 2,
        "super_large": super_large,
    }


def test_inflow_continuity_three_days_qualifies():
    rows = [
        _flow_row("2026-10-31", 4.5e8, 1.6e8),
        _flow_row("2026-11-02", 3.9e8, 1.6e8),
        _flow_row("2026-11-03", 4.5e8, -0.9e8),
        _flow_row("2026-11-04", 5.8e8, 2.4e8),
    ]
    signal = detect_inflow_continuity(rows)
    assert signal is not None
    assert signal.days == 4
    assert signal.today_super_large == 2.4e8


def test_inflow_continuity_rejects_negative_super_large_today():
    rows = [
        _flow_row("2026-11-02", 3.9e8, 1e8),
        _flow_row("2026-11-03", 4.5e8, 1e8),
        _flow_row("2026-11-04", 5.8e8, -0.5e8),
    ]
    assert detect_inflow_continuity(rows) is None


def test_inflow_continuity_rejects_broken_streak():
    rows = [
        _flow_row("2026-11-02", -1.3e8, 1e8),
        _flow_row("2026-11-03", 4.5e8, 1e8),
        _flow_row("2026-11-04", 5.8e8, 2.4e8),
    ]
    assert detect_inflow_continuity(rows) is None


def test_inflow_continuity_handles_unsorted_rows():
    rows = [
        _flow_row("2026-11-04", 5.8e8, 2.4e8),
        _flow_row("2026-11-02", 3.9e8, 1e8),
        _flow_row("2026-11-03", 4.5e8, 1e8),
    ]
    assert detect_inflow_continuity(rows) is not None


def test_format_inflow_alert_renders_yi():
    from src.intraday_monitor.fundflow import InflowSignal

    text = format_inflow_alert(
        [("688981.SH", "中芯国际", InflowSignal(3, 5.75e8, 2.42e8, "2026-11-04"))],
        "13:30",
    )
    assert "连续 3 日净流入" in text
    assert "+5.75亿" in text and "+2.42亿" in text


def test_monitor_fund_flow_scan_daily_dedupe(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from src.intraday_monitor import monitor as monitor_mod
    rows = [
        _flow_row("2026-11-02", 3.9e8, 1e8),
        _flow_row("2026-11-03", 4.5e8, 1e8),
        _flow_row("2026-11-04", 5.8e8, 2.4e8),
    ]

    def fake_flow(symbol, *, period, days):  # noqa: ANN001
        return {"symbol": symbol, "rows": list(rows)}

    pushed: list[str] = []

    async def _push(text: str) -> None:
        pushed.append(text)

    clock = _FakeClock(datetime.fromisoformat("2026-11-04 13:35").replace(tzinfo=monitor_mod._TZ))
    mon = monitor_mod.IntradayVolumeMonitor(
        basket={"688981.SH": ("中芯国际", "半导体")},
        push_fn=_push,
        now_fn=clock,
    )

    from src.tools import fund_flow_tool

    monkeypatch.setattr(fund_flow_tool, "_fetch_symbol_flow", fake_flow)

    async def _scenario() -> None:
        fired = await mon.scan_fund_flow()
        assert len(fired) == 1 and fired[0][0] == "688981.SH"
        assert len(pushed) == 1
        # Same day: suppressed even though the continuity still holds.
        assert await mon.scan_fund_flow() == []
        assert len(pushed) == 1
        status = mon.status()
        assert status["fund_flow"]["signals"][0]["days"] == 3

    asyncio.run(_scenario())
