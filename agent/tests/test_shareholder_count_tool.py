"""Tests for get_shareholder_count: success + error envelopes, HTTP mocked.

The Eastmoney datacenter call is mocked at ``get_json`` (imported into the tool
module), so no test reaches a live endpoint.

Note the fixture mirrors ``RPT_F10_EH_HOLDERNUM``, the F10 history series: it
carries ``HOLDER_TOTAL_NUM`` / ``AVG_HOLD_AMT`` and no change columns (the tool
derives those). Upstream removes columns without notice and the whole report then
fails with ``code 9501 <field>返回字段不存在``, so a fixture using retired field
names would keep the suite green while the tool was dead — which is exactly what
happened before.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import shareholder_count_tool as sct
from src.tools.shareholder_count_tool import ShareholderCountTool

_SAMPLE_PAYLOAD = {
    "result": {
        "data": [
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2024-03-31 00:00:00",
                "HOLDER_TOTAL_NUM": 188000,
                "AVG_HOLD_AMT": 12345678.0,
                "NOTICE_DATE": "2024-04-20 00:00:00",
            },
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2023-12-31 00:00:00",
                "HOLDER_TOTAL_NUM": 190000,
                "AVG_HOLD_AMT": 12000000.0,
                "NOTICE_DATE": "2024-01-20 00:00:00",
            },
        ]
    }
}


def test_success_envelope_parses_periods_newest_first():
    with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD) as mock_get:
        out = ShareholderCountTool().execute(code="600519.SH")

    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["market"] == "CN"
    assert payload["source"] == "eastmoney"
    assert payload["data"]["code"] == "600519.SH"

    periods = payload["data"]["periods"]
    assert len(periods) == 2
    assert periods[0]["end_date"] == "2024-03-31"
    assert periods[0]["holder_count"] == 188000.0
    assert periods[0]["avg_hold_amount"] == 12345678.0
    assert periods[0]["notice_date"] == "2024-04-20"

    # SECUCODE filter flows through to the datacenter request.
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["filter"] == '(SECUCODE="600519.SH")'
    assert kwargs["params"]["reportName"] == "RPT_F10_EH_HOLDERNUM"


def test_change_is_derived_from_consecutive_periods():
    with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD):
        out = ShareholderCountTool().execute(code="600519.SH")

    periods = json.loads(out)["data"]["periods"]
    # 188000 vs the prior 190000: -2000, -1.0526%.
    assert periods[0]["holder_count_change"] == -2000.0
    assert round(periods[0]["holder_count_change_pct"], 4) == round(-2000 / 190000 * 100, 4)


def test_oldest_period_has_no_change_rather_than_zero():
    """The window's last row has no predecessor; 0 would read as 'unchanged'."""
    with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD):
        out = ShareholderCountTool().execute(code="600519.SH")

    oldest = json.loads(out)["data"]["periods"][-1]
    assert oldest["holder_count_change"] is None
    assert oldest["holder_count_change_pct"] is None


def test_max_periods_caps_returned_rows():
    with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD):
        out = ShareholderCountTool().execute(code="600519.SH", max_periods=1)
    payload = json.loads(out)
    assert len(payload["data"]["periods"]) == 1


def test_non_a_share_returns_error_envelope():
    out = ShareholderCountTool().execute(code="AAPL.US")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "A-share" in payload["error"]


def test_missing_code_returns_error_envelope():
    out = ShareholderCountTool().execute()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "required" in payload["error"]


def test_empty_disclosure_returns_error_envelope():
    with patch.object(sct, "get_json", return_value={"result": {"data": []}}):
        out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "no shareholder-count" in payload["error"]


def test_request_failure_is_caught_as_error_envelope():
    with patch.object(sct, "get_json", side_effect=RuntimeError("HTTP 429")):
        out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "429" in payload["error"]
