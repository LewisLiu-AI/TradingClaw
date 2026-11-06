"""Read-only tool: A-share quarterly shareholder count via Eastmoney datacenter.

Eastmoney's datacenter report API publishes the periodic "股东户数" (number of
registered shareholders) disclosure for mainland A-shares: the holder count per
report period, the quarter-over-quarter change, and the average holding value
per account. This tool wraps that report behind the project's BaseTool contract
and the frozen, IP-throttled Eastmoney client so the agent never hits the host
un-throttled and never re-implements provider plumbing.

Only mainland A-shares (``.SH`` / ``.SZ`` / ``.BJ``) carry this disclosure;
other markets return an error envelope.
"""

from __future__ import annotations

import json
from typing import Any

from backtest.loaders.eastmoney_client import get_json, resolve_secid
from src.agent.tools import BaseTool

# Eastmoney datacenter report endpoint + the shareholder-number report id.
_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# Two reports exist upstream and they are not interchangeable:
#
# * ``RPT_HOLDERNUMLATEST`` — one row, the most recent disclosure only, with the
#   provider-computed change/ratio/avg-holding columns. It has no history, so
#   ``max_periods`` could only ever yield a single period.
# * ``RPT_F10_EH_HOLDERNUM`` — the full quarterly series (holder count and
#   per-account holding value per report period). Used here.
#
# Either report fails wholesale (HTTP 200 with ``success: false`` and
# ``code: 9501 <field>返回字段不存在``) if any requested column was removed
# upstream, so the column list is kept minimal and verified against live data.
_REPORT_NAME = "RPT_F10_EH_HOLDERNUM"
_COLUMNS = "SECUCODE,SECURITY_CODE,END_DATE,HOLDER_TOTAL_NUM,AVG_HOLD_AMT,NOTICE_DATE"

# Hard cap on returned periods so a long history cannot bloat the payload.
_MAX_PERIODS = 24

# A-share exchange suffixes this disclosure covers.
_A_SHARE_SUFFIXES = ("SH", "SZ", "BJ")


class ShareholderCountTool(BaseTool):
    """Fetch A-share quarterly shareholder counts with QoQ change and avg holding."""

    name = "get_shareholder_count"
    description = (
        "Fetch mainland A-share quarterly shareholder count (股东户数) from the "
        "Eastmoney F10 series: holder count per report period, the derived "
        "quarter-over-quarter change (absolute and percent), the per-account "
        "average holding value, and each period's disclosure date. Returns the "
        "most recent periods, newest first; the oldest period in the window has "
        "no predecessor and therefore no change value. Markets: China A-shares "
        "only (.SH / .SZ / .BJ). Example: {\"code\": \"600519.SH\", "
        "\"max_periods\": 8}."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "A-share symbol in <code>.<exchange> form, exchange suffix one of "
                    "SH / SZ / BJ (e.g. '600519.SH', '000001.SZ', '830799.BJ')."
                ),
            },
            "max_periods": {
                "type": "integer",
                "description": (
                    "Maximum number of most-recent report periods to return "
                    f"(1-{_MAX_PERIODS}). Defaults to {_MAX_PERIODS}."
                ),
                "default": _MAX_PERIODS,
            },
        },
        "required": ["code"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Resolve the symbol, query the report, and return a JSON envelope.

        Args:
            **kwargs: ``code`` (required A-share symbol) and optional
                ``max_periods`` (period cap).

        Returns:
            A JSON string envelope. On success:
            ``{"ok": true, "market": "CN", "source": "eastmoney",
            "data": {"code", "periods": [...]}}``. On failure:
            ``{"ok": false, "error": str}``.
        """
        code = kwargs.get("code")
        if not isinstance(code, str) or not code.strip():
            return _error("'code' is required and must be a non-empty A-share symbol")
        code = code.strip().upper()

        suffix = code.rpartition(".")[2]
        if suffix not in _A_SHARE_SUFFIXES:
            return _error(
                f"shareholder count is China A-share only (.SH/.SZ/.BJ); got '{code}'"
            )
        if resolve_secid(code) is None:
            return _error(f"could not resolve A-share symbol '{code}'")

        limit = _clamp_periods(kwargs.get("max_periods", _MAX_PERIODS))

        try:
            payload = get_json(
                _DATACENTER_URL,
                params={
                    "reportName": _REPORT_NAME,
                    "columns": _COLUMNS,
                    "filter": f'(SECUCODE="{code}")',
                    "sortColumns": "END_DATE",
                    "sortTypes": "-1",
                    "pageNumber": "1",
                    "pageSize": str(limit),
                    "source": "WEB",
                    "client": "WEB",
                },
            )
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            return _error(f"eastmoney datacenter request failed: {exc}")

        periods = _parse_periods(payload)
        if not periods:
            return _error(f"no shareholder-count disclosure found for '{code}'")

        return json.dumps(
            {
                "ok": True,
                "market": "CN",
                "source": "eastmoney",
                "data": {"code": code, "periods": periods[:limit]},
            },
            ensure_ascii=False,
        )


def _clamp_periods(value: Any) -> int:
    """Coerce a requested period count into the supported ``1.._MAX_PERIODS`` range."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return _MAX_PERIODS
    return max(1, min(n, _MAX_PERIODS))


def _parse_periods(payload: Any) -> list[dict]:
    """Extract per-period shareholder records from a datacenter payload.

    Args:
        payload: Decoded datacenter JSON; rows live under ``result.data``.

    Returns:
        A list of normalized period dicts (newest first), empty when the payload
        carries no usable rows.
    """
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    rows = result.get("data")
    if not isinstance(rows, list):
        return []

    periods: list[dict] = []
    for row in rows:
        record = _normalize_row(row)
        if record is not None:
            periods.append(record)
    _attach_period_changes(periods)
    return periods


def _attach_period_changes(periods: list[dict]) -> None:
    """Fill ``holder_count_change``/``_pct`` from consecutive periods in place.

    The F10 series carries holder counts only, not the quarter-over-quarter
    delta, so it is derived against the next-older period. The oldest period in
    the returned window has no predecessor and keeps ``None`` for both — never
    zero, which would read as "unchanged".

    Args:
        periods: Period records ordered newest-first (mutated in place).
    """
    for index, record in enumerate(periods):
        current = record.get("holder_count")
        previous = (
            periods[index + 1].get("holder_count")
            if index + 1 < len(periods)
            else None
        )
        if current is None or previous in (None, 0):
            record["holder_count_change"] = None
            record["holder_count_change_pct"] = None
            continue
        change = current - previous
        record["holder_count_change"] = change
        record["holder_count_change_pct"] = change / previous * 100


def _normalize_row(row: Any) -> dict | None:
    """Map one raw datacenter row to our period record, or ``None`` if unusable.

    A row missing both an end date and a holder count carries no signal and is
    dropped; a single bad row never aborts the batch.

    Args:
        row: One element of ``result.data``.

    Returns:
        ``{end_date, holder_count, holder_count_change, holder_count_change_pct,
        avg_hold_amount, notice_date}`` or ``None``. The change fields are
        placeholders filled by :func:`_attach_period_changes`.
    """
    if not isinstance(row, dict):
        return None
    end_date = _clean_date(row.get("END_DATE"))
    holder_count = _to_number(row.get("HOLDER_TOTAL_NUM"))
    if end_date is None and holder_count is None:
        return None
    return {
        "end_date": end_date,
        "holder_count": holder_count,
        "holder_count_change": None,
        "holder_count_change_pct": None,
        "avg_hold_amount": _to_number(row.get("AVG_HOLD_AMT")),
        "notice_date": _clean_date(row.get("NOTICE_DATE")),
    }


def _clean_date(value: Any) -> str | None:
    """Trim a datacenter timestamp to its ``YYYY-MM-DD`` date, or ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().split(" ", 1)[0]


def _to_number(value: Any) -> float | None:
    """Coerce a datacenter cell to ``float``, or ``None`` when absent/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error(message: str) -> str:
    """Render a failure envelope as a JSON string."""
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
