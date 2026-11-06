"""Live integration tests for the real Eastmoney interface + Juliang proxy chain.

These make genuine HTTP requests to Eastmoney endpoints and, for the proxy-path
test, consume real Juliang dynamic-proxy quota (one extraction, then reused for
the single request). Like ``test_e2e_harness_v2.py``, they are gated behind an
opt-in env var so no default/CI ``pytest`` pass ever touches the network:

    VIBE_TRADING_RUN_LIVE_EASTMONEY=1 pytest agent/tests/test_eastmoney_live.py

The ``integration`` marker additionally labels the file for ``-m integration``.

Skip policy:
    * Module-wide: skips unless ``VIBE_TRADING_RUN_LIVE_EASTMONEY`` is set, and
      skips when the Eastmoney search host is unreachable.
    * Proxy-path test: additionally skips when Juliang is not configured.
"""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import date, timedelta

import pytest

from backtest.loaders import eastmoney_client as ec
from backtest.loaders.juliang_proxy import get_juliang_client

pytestmark = pytest.mark.integration

# Opt-in gate, mirroring the repo's ``VIBE_TRADING_RUN_LIVE_E2E`` convention for
# tests that exercise a real external service (here: Eastmoney + real quota).
_LIVE_ENV = "VIBE_TRADING_RUN_LIVE_EASTMONEY"

# The search host is direct-connect (never proxied) and reachable from both
# residential and datacenter IPs, so it is a reliable "network is up" probe.
_SEARCH_HOST = "searchapi.eastmoney.com"


def _eastmoney_reachable() -> bool:
    try:
        with socket.create_connection((_SEARCH_HOST, 443), timeout=5):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module", autouse=True)
def _require_live_run():
    if not os.environ.get(_LIVE_ENV):
        pytest.skip(f"set {_LIVE_ENV}=1 to run live Eastmoney tests")
    if not _eastmoney_reachable():
        pytest.skip("Eastmoney is unreachable from this network; not running live tests")


def _assert_ohlc_invariants(rows: list[dict]) -> None:
    """Assert the OHLCV contract every real push2his kline must satisfy."""
    assert rows, "expected at least one bar"
    dates = [r["trade_date"] for r in rows]
    assert dates == sorted(dates), "kline must be ascending by date"
    for row in rows:
        assert row["volume"] > 0, f"non-positive volume on {row['trade_date']}"
        assert row["amount"] > 0, f"non-positive amount on {row['trade_date']}"
        assert row["high"] >= max(row["open"], row["close"]), f"high below body on {row['trade_date']}"
        assert row["low"] <= min(row["open"], row["close"]), f"low above body on {row['trade_date']}"


class TestLiveSecidResolution:
    def test_us_ticker_resolves_through_real_search(self) -> None:
        """US secids require a live call to the search/suggest endpoint."""
        secid = ec.resolve_secid("AAPL.US")
        assert secid is not None
        market, _, code = secid.partition(".")
        assert market in ("105", "106", "107"), f"unexpected market prefix {market!r}"
        assert code == "AAPL"


class TestLiveKline:
    def test_ashare_daily_kline_fetch(self) -> None:
        """A real daily-kline fetch returns OHLCV-invariant bars from push2his.

        Runs through the production ``get_json`` path, so the request may be
        served direct (this machine) or via the Juliang proxy fallback (a
        WAF-blocked IP); the proxy path itself is pinned down by
        :class:`TestLiveProxyChain`.
        """
        rows = ec.fetch_kline("1.600519", klt=101, beg="20240101", end="20240131")
        _assert_ohlc_invariants(rows)
        # 2024-01-01 is a market holiday; the first trading day is 2024-01-02.
        assert rows[0]["trade_date"] == "2024-01-02"

    def test_kline_reflects_recent_trading(self) -> None:
        """The most recent bar should be within a few trading days of today."""
        beg = (date.today() - timedelta(days=14)).strftime("%Y%m%d")
        rows = ec.fetch_kline("1.600519", klt=101, beg=beg)
        _assert_ohlc_invariants(rows)
        threshold = (date.today() - timedelta(days=10)).isoformat()
        assert rows[-1]["trade_date"] >= threshold, "last bar is stale"


class TestLiveProxyChain:
    def test_forced_proxy_path_returns_real_data(self, monkeypatch) -> None:
        """Open the direct-first breaker so the request must ride a live Juliang
        proxy, then verify the proxy actually served real Eastmoney data.

        Consumes one Juliang quota unit per run (one extraction, reused for the
        single request).
        """
        client = get_juliang_client()
        if not client.is_configured():
            pytest.skip("Juliang proxy not configured; set VIBE_TRADING_JULIANG_* to run")

        # Open the direct-first breaker so the doomed direct attempt is skipped
        # and the request is routed through the proxy path.
        breaker = ec._DIRECT_BREAKER
        monkeypatch.setattr(breaker, "_failures", breaker._max_failures)
        monkeypatch.setattr(breaker, "_open_until", time.monotonic() + 600)

        proxied_urls: list[str] = []
        real_via_proxy = ec._get_json_via_proxy

        def recording(url, params):
            proxied_urls.append(url)
            return real_via_proxy(url, params)

        monkeypatch.setattr(ec, "_get_json_via_proxy", recording)

        rows = ec.fetch_kline("1.600519", klt=101, beg="20240102", end="20240110")

        assert proxied_urls, "request was not routed through the proxy path"
        assert proxied_urls[0] == ec._KLINE_URL
        _assert_ohlc_invariants(rows)
        status = client.status()
        assert status["current_proxy"], "no live proxy was extracted"
        assert status["surplus_quantity"] is not None, "surplus not reported by extraction"


class TestLiveReadOnlyDataTools:
    """Live contract checks for the read-only disclosure tools.

    These exist because the unit suites mock ``get_json`` — which keeps them fast
    but makes them blind to upstream drift. Every tool here was silently broken
    by a schema change on Eastmoney's side while its mocked tests stayed green:
    the research-report endpoint started requiring ``beginTime``/``endTime``,
    ``AVG_HOLD_AMT`` was dropped from one holder-count report, and the wrong
    holder-count report was addressed entirely. Assert *shape and freshness*
    against real responses, not specific values.
    """

    def test_research_reports_returns_recent_coverage(self) -> None:
        from src.tools.research_reports_tool import ResearchReportsTool

        payload = json.loads(ResearchReportsTool().execute(code="600519.SH", limit=5))
        assert payload["ok"] is True, payload.get("error")
        reports = payload["data"]["reports"]
        assert reports, "no research reports returned for 600519.SH"
        for report in reports:
            assert report["publish_date"], "report missing publish_date"
            assert report["title"] or report["brokerage"], "report has neither title nor brokerage"
        # The request window must reach back far enough to include real coverage.
        dates = [r["publish_date"] for r in reports]
        assert dates == sorted(dates, reverse=True), "reports must be newest-first"

    def test_shareholder_count_returns_period_series(self) -> None:
        from src.tools.shareholder_count_tool import ShareholderCountTool

        payload = json.loads(
            ShareholderCountTool().execute(code="600519.SH", max_periods=8)
        )
        assert payload["ok"] is True, payload.get("error")
        periods = payload["data"]["periods"]
        assert len(periods) >= 4, f"expected a quarterly series, got {len(periods)} period(s)"
        for period in periods:
            assert period["end_date"], "period missing end_date"
            assert period["holder_count"] and period["holder_count"] > 0
        # All but the oldest period must carry a derived change.
        assert periods[0]["holder_count_change"] is not None
        assert periods[-1]["holder_count_change"] is None

    def test_financial_statements_payload_stays_within_budget(self) -> None:
        from src.agent.loop import TOOL_RESULT_LIMIT
        from src.tools.financial_statements_tool import FinancialStatementsTool

        for statement in ("income", "balance", "cashflow", "indicators"):
            text = FinancialStatementsTool().execute(
                code="600519.SH", statement=statement, period="quarter"
            )
            assert len(text) <= TOOL_RESULT_LIMIT, (
                f"{statement} returned {len(text)} chars, over the {TOOL_RESULT_LIMIT} "
                "tool-result budget — it would be truncated before reaching the model"
            )
            payload = json.loads(text)
            assert payload["ok"] is True, payload.get("error")
            period = payload["data"]["600519.SH"]["periods"][0]
            assert period["REPORT_DATE"], f"{statement} projection dropped REPORT_DATE"
            assert len(period) < 40, f"{statement} projection kept {len(period)} fields"
