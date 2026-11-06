"""Read-only financial-statements tool: three statements + key indicators.

Pulls a single stock's balance sheet, income statement, cash-flow statement, or
key per-period indicators from a market-appropriate public source:

* **A-share** (``.SH`` / ``.SZ`` / ``.BJ``) — Eastmoney's A-share F10 report
  datasets (``RPT_F10_FINANCE_*``), filtered on the dotted ``SECUCODE`` (e.g.
  ``600519.SH``). The legacy Sina ``quotes.sina.cn`` company-finance openapi
  returned a graceful-empty masking an upstream failure, so the A-share path now
  shares the Eastmoney transport with HK.
* **US** (``.US``) — SEC EDGAR companyfacts XBRL, resolved by ticker->CIK.
* **Hong Kong** (``.HK``) — Eastmoney's HK F10 financial-report datasets,
  filtered on the bare ``SECURITY_CODE``; ``indicators`` reads the
  main-indicator dataset.

Eastmoney requests go through :func:`backtest.loaders.eastmoney_client.get_json`
(``host_key="eastmoney"``); SEC requests go through the shared EDGAR client
(``host_key="sec"``).

The tool is read-only and self-contained: ``execute`` returns a JSON-string
envelope and never raises for a recoverable per-request failure — a bad symbol
or a transient HTTP error is reported inside the envelope.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backtest.loaders.eastmoney_client import get_json, resolve_secid
from backtest.loaders.sec_edgar_client import cik_for, get_company_facts
from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# --- Eastmoney datacenter report API --------------------------------------

# Eastmoney datacenter report API. The three statements and the main-indicator
# dataset are addressed by report name, which differs by market (A / HK).
_EM_REPORT_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

# (market_prefix_group, statement) -> Eastmoney report name. ``a`` covers the
# mainland exchanges (markets 0/1); ``hk`` covers 116.
_EM_REPORT_NAME: dict[str, dict[str, str]] = {
    "a": {
        "balance": "RPT_F10_FINANCE_GBALANCE",
        "income": "RPT_F10_FINANCE_GINCOME",
        "cashflow": "RPT_F10_FINANCE_GCASHFLOW",
        "indicators": "RPT_F10_FINANCE_MAINFINADATA",
    },
    "hk": {
        "balance": "RPT_HKF10_FN_BALANCE",
        "income": "RPT_HKF10_FN_INCOME",
        "cashflow": "RPT_HKF10_FN_CASHFLOW",
        "indicators": "RPT_HKF10_FN_GMAININDICATOR",
    },
}

# Eastmoney mainland A-share markets (SZ/BJ = 0, SH = 1) and the HK market.
_EM_A_MARKETS = ("0", "1")
_EM_HK_MARKET = "116"

_SEC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "balance": (
        "Assets",
        "AssetsCurrent",
        "CashAndCashEquivalentsAtCarryingValue",
        "Liabilities",
        "LiabilitiesCurrent",
        "LongTermDebtAndFinanceLeaseObligationsCurrentAndNoncurrent",
        "StockholdersEquity",
    ),
    "income": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
    ),
    "cashflow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
    ),
    "indicators": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "NetIncomeLoss",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "EarningsPerShareDiluted",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
}

# --- Shared limits / validation ------------------------------------------

_VALID_STATEMENTS = ("balance", "income", "cashflow", "indicators")
_VALID_PERIODS = ("annual", "quarter")

# Defensive caps so a payload can never blow up the LLM context. ``columns: ALL``
# returns ~200 fields per row (104-121 of them populated), so 40 periods alone
# serialised to ~180k chars -- more than an order of magnitude over the loop's
# 10k tool-result budget, which used to truncate the JSON mid-object.
_MAX_PERIODS = 40
_DEFAULT_PERIODS = 8
_MAX_FIELDS_PER_PERIOD = 200

# The reporting-period keys every projection keeps.
_PERIOD_KEYS = ("REPORT_DATE", "REPORT_DATE_NAME")

# Curated default projection per statement: the line items an equity analysis
# actually reasons about. Callers that need a full filing pass ``fields=[...]``
# (or ``fields=["*"]``) instead. Measured effect for one A-share, ``indicators``:
# 40 periods x 165 fields = 179,600 chars -> 8 periods x 21 fields = ~4.4k chars.
_CORE_FIELDS: dict[str, tuple[str, ...]] = {
    "income": (
        "TOTAL_OPERATE_INCOME",
        "TOTAL_OPERATE_INCOME_YOY",
        "OPERATE_COST",
        "OPERATE_COST_YOY",
        "RESEARCH_EXPENSE",
        "SALE_EXPENSE",
        "MANAGE_EXPENSE",
        "FINANCE_EXPENSE",
        "OPERATE_PROFIT",
        "TOTAL_PROFIT",
        "INCOME_TAX",
        "NETPROFIT",
        "PARENT_NETPROFIT",
        "PARENT_NETPROFIT_YOY",
        "DEDUCT_PARENT_NETPROFIT",
        "DEDUCT_PARENT_NETPROFIT_YOY",
        "BASIC_EPS",
        "DILUTED_EPS",
        "TOTAL_COMPRE_INCOME",
    ),
    "balance": (
        "TOTAL_ASSETS",
        "TOTAL_CURRENT_ASSETS",
        "TOTAL_NONCURRENT_ASSETS",
        "MONETARYFUNDS",
        "ACCOUNTS_RECE",
        "NOTE_ACCOUNTS_RECE",
        "INVENTORY",
        "FIXED_ASSET",
        "CIP",
        "INTANGIBLE_ASSET",
        "GOODWILL",
        "TOTAL_LIABILITIES",
        "TOTAL_CURRENT_LIAB",
        "SHORT_LOAN",
        "ACCOUNTS_PAYABLE",
        "CONTRACT_LIAB",
        "LONG_LOAN",
        "TOTAL_EQUITY",
        "TOTAL_PARENT_EQUITY",
        "MINORITY_EQUITY",
        "SHARE_CAPITAL",
        "TOTAL_LIAB_EQUITY",
    ),
    "cashflow": (
        "SALES_SERVICES",
        "TOTAL_OPERATE_INFLOW",
        "TOTAL_OPERATE_OUTFLOW",
        "PAY_ALL_TAX",
        "PAY_STAFF_CASH",
        "NETCASH_OPERATE",
        "NETCASH_OPERATE_YOY",
        "NETCASH_INVEST",
        "NETCASH_FINANCE",
        "CONSTRUCT_LONG_ASSET",
        "INVEST_PAY_CASH",
        "FA_IR_DEPR",
        "IA_AMORTIZE",
        "CCE_ADD",
        "END_CCE_BALANCE",
    ),
    "indicators": (
        "EPSJB",
        "EPSKCJB",
        "BPS",
        "MGJYXJJE",
        "TOTALOPERATEREVE",
        "TOTALOPERATEREVETZ",
        "MLR",
        "PARENTNETPROFIT",
        "PARENTNETPROFITTZ",
        "KCFJCXSYJLR",
        "KCFJCXSYJLRTZ",
        "XSMLL",
        "XSJLL",
        "ROEJQ",
        "ROEKCJQ",
        "ZZCJLL",
        "ROIC",
        "ZCFZL",
        "LD",
        "SD",
        "XJLLB",
        "YSZKYYSR",
        "JYXJLYYSR",
        "TOTAL_SHARE",
        "STAFF_NUM",
    ),
}


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _clamp_periods(value: Any) -> int:
    """Coerce a requested period count into ``1.._MAX_PERIODS``.

    Args:
        value: Raw ``limit`` argument from the tool call.

    Returns:
        The clamped period count, defaulting to :data:`_DEFAULT_PERIODS` when the
        value is absent or not an integer.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_PERIODS
    return max(1, min(n, _MAX_PERIODS))


def _truncate_period(record: dict[str, Any]) -> dict[str, Any]:
    """Cap one period's field count so a single record stays context-safe.

    Args:
        record: A flat period dict (field name -> value).

    Returns:
        A new dict with at most :data:`_MAX_FIELDS_PER_PERIOD` items, preserving
        insertion order. The original is never mutated.
    """
    items = list(record.items())
    if len(items) <= _MAX_FIELDS_PER_PERIOD:
        return dict(items)
    return dict(items[:_MAX_FIELDS_PER_PERIOD])


def _project_period(
    record: dict[str, Any], keep: tuple[str, ...] | None
) -> dict[str, Any]:
    """Reduce one period record to the requested fields.

    Args:
        record: A flat period dict (field name -> value).
        keep: Field names to retain, or ``None`` for no projection.

    Returns:
        A new dict holding the period keys that exist in ``record`` plus every
        requested field present in ``record``. A projection that matches nothing
        falls back to the unprojected record so a provider rename cannot silently
        empty the payload.
    """
    if keep is None:
        return _truncate_period(record)

    matched = [key for key in keep if key in record]
    if not matched:
        return _truncate_period(record)

    projected = {key: record[key] for key in _PERIOD_KEYS if key in record}
    projected.update({key: record[key] for key in matched})
    return projected


def _resolve_fields(
    statement: str, fields: list[str] | None, *, curated: bool = True
) -> tuple[str, ...] | None:
    """Decide which fields to keep for a statement.

    Args:
        statement: One of :data:`_VALID_STATEMENTS`.
        fields: Caller-supplied field names. ``["*"]`` asks for every provider
            field; ``None``/empty asks for the curated default.
        curated: Whether the curated per-statement set applies. False for US
            statements, whose us-gaap concept names differ from the A-share
            provider field names in :data:`_CORE_FIELDS`.

    Returns:
        The field names to keep, or ``None`` to return every provider field.
    """
    if fields and fields != ["*"]:
        return tuple(fields)
    if fields == ["*"]:
        return None
    return _CORE_FIELDS.get(statement) if curated else None


def _cap_periods(
    periods: list[dict[str, Any]],
    limit: int = _DEFAULT_PERIODS,
    keep: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Keep the most recent periods and project each onto the wanted fields.

    Args:
        periods: Period records as returned by the provider parser.
        limit: Maximum number of most-recent periods to keep.
        keep: Field names to retain per period, or ``None`` to keep all fields.

    Returns:
        A new list of at most ``limit`` projected records.
    """
    return [_project_period(record, keep) for record in periods[:limit]]


def _eastmoney_market_group(secid: str) -> str | None:
    """Classify an Eastmoney secid into the ``a`` or ``hk`` report group.

    Args:
        secid: Eastmoney secid (e.g. ``"1.600519"`` or ``"116.00700"``).

    Returns:
        ``"a"``, ``"hk"``, or ``None`` when the market prefix is unrecognized.
    """
    market = secid.split(".", 1)[0]
    if market in _EM_A_MARKETS:
        return "a"
    if market == _EM_HK_MARKET:
        return "hk"
    return None


def _parse_eastmoney_periods(payload: Any) -> list[dict[str, Any]]:
    """Extract period records from an Eastmoney datacenter report payload.

    Eastmoney nests report rows under ``result.data`` as a list of flat dicts.
    Any other shape yields an empty list rather than raising.

    Args:
        payload: Decoded JSON from the datacenter report API.

    Returns:
        A list of flat period dicts (possibly empty).
    """
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _eastmoney_filter(group: str, code: str, secid: str) -> str:
    """Build the datacenter ``filter`` clause for one market group.

    The A-share F10 datasets key on the dotted ``SECUCODE`` (e.g.
    ``600519.SH``), whereas the HK datasets key on the bare ``SECURITY_CODE``
    carried in the secid (e.g. ``00700``). No ``REPORT_TYPE`` clause
    is emitted: Eastmoney stores ``REPORT_TYPE`` as locale text (年报 / 一季报)
    or a ``2026/Q1`` string that differs by market and report, so a numeric
    filter matched zero rows. Period selection is done client-side instead
    (see :func:`_filter_by_period`).

    Args:
        group: Market group from :func:`_eastmoney_market_group`.
        code: Original Vibe-Trading symbol (e.g. ``"600519.SH"``).
        secid: Resolved Eastmoney secid (e.g. ``"1.600519"``).

    Returns:
        The Eastmoney ``filter`` query-parameter string.
    """
    if group == "a":
        return f'(SECUCODE="{code.upper()}")'
    bare_code = secid.split(".", 1)[1]
    return f'(SECURITY_CODE="{bare_code}")'


def _filter_by_period(
    periods: list[dict[str, Any]], period: str
) -> list[dict[str, Any]]:
    """Best-effort client-side period selection by report date.

    Eastmoney returns a mixed newest-first series (annual + interim reports).
    For ``annual`` we keep only fiscal-year-end rows (``REPORT_DATE`` ending
    ``-12-31``); if none match — e.g. an issuer whose fiscal year does not end
    in December — we fall back to the full series rather than drop all data.
    ``quarter`` returns the full newest-first series unchanged.

    Args:
        periods: Period records (newest-first) from the report parser.
        period: ``"annual"`` or ``"quarter"``.

    Returns:
        The filtered list; never empty when ``periods`` is non-empty.
    """
    if period != "annual":
        return periods
    annual = [
        row
        for row in periods
        if str(row.get("REPORT_DATE", ""))[:10].endswith("-12-31")
    ]
    return annual or periods


def _fetch_eastmoney_statement(
    code: str,
    *,
    statement: str,
    period: str,
    limit: int = _DEFAULT_PERIODS,
    keep: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Fetch one A-share/HK statement from Eastmoney, shaped into a result dict.

    Args:
        code: Symbol (e.g. ``"600519.SH"`` or ``"00700.HK"``).
        statement: One of :data:`_VALID_STATEMENTS`.
        period: ``"annual"`` or ``"quarter"``.
        limit: Maximum number of most-recent periods to return.
        keep: Field names to retain per period, or ``None`` to keep all fields.

    Returns:
        ``{"periods": [...]}`` on success or ``{"error": ...}`` on failure;
        never raises.
    """
    secid = resolve_secid(code)
    if secid is None:
        return {"error": "unresolvable symbol"}

    group = _eastmoney_market_group(secid)
    if group is None:
        return {"error": "symbol is not an A-share or Hong Kong instrument"}

    # Fetch the full series so ``annual`` filtering still has history to draw on,
    # then narrow server-side cost by asking only for as many rows as needed.
    fetch_rows = _MAX_PERIODS if period == "annual" else limit

    params = {
        "reportName": _EM_REPORT_NAME[group][statement],
        "columns": "ALL",
        "filter": _eastmoney_filter(group, code, secid),
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "pageNumber": "1",
        "pageSize": str(fetch_rows),
        "source": "F10",
        "client": "PC",
    }
    try:
        payload = get_json(_EM_REPORT_URL, params=params)
    except Exception as exc:  # noqa: BLE001 - one bad fetch must not kill the call
        logger.warning("eastmoney statement fetch failed for %s: %s", code, exc)
        return {"error": str(exc)}

    periods = _filter_by_period(_parse_eastmoney_periods(payload), period)
    return {"periods": _cap_periods(periods, limit, keep)}


def _to_number(value: Any) -> float | None:
    """Coerce a numeric provider cell to float, preserving missing values."""
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_sec_unit(units: dict[str, Any]) -> tuple[str, list[Any]]:
    """Pick the SEC XBRL unit bucket with the most reported rows."""
    best_key = ""
    best_rows: list[Any] = []
    for key, rows in units.items():
        if isinstance(rows, list) and len(rows) >= len(best_rows):
            best_key, best_rows = str(key), rows
    return best_key, best_rows


def _sec_period_matches(row: dict[str, Any], period: str) -> bool:
    """Return whether a SEC fact row belongs in the requested cadence."""
    if period != "annual":
        return True
    fp = str(row.get("fp") or "").upper()
    form = str(row.get("form") or "").upper()
    return fp == "FY" or form == "10-K"


def _fetch_sec_statement(
    code: str,
    *,
    statement: str,
    period: str,
    limit: int = _DEFAULT_PERIODS,
    keep: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Fetch one US statement from SEC companyfacts, shaped as flat periods.

    Args:
        code: US symbol with ``.US`` suffix, e.g. ``"AAPL.US"``.
        statement: One of :data:`_VALID_STATEMENTS`.
        period: ``"annual"`` or ``"quarter"``.
        limit: Maximum number of most-recent periods to return.
        keep: Field names to retain per period, or ``None`` to keep all fields.

    Returns:
        ``{"periods": [...]}`` on success or ``{"error": ...}`` on failure.
    """
    ticker = code.rsplit(".", 1)[0].strip().upper()
    try:
        cik = cik_for(ticker)
    except Exception as exc:  # noqa: BLE001 - surface provider failures as envelope
        logger.warning("SEC ticker lookup failed for %s: %s", code, exc)
        return {"error": f"SEC ticker lookup failed: {exc}"}
    if not cik:
        return {"error": "ticker not found in SEC company table"}

    try:
        facts = get_company_facts(cik)
    except Exception as exc:  # noqa: BLE001 - one bad fetch must not kill the call
        logger.warning("SEC companyfacts fetch failed for %s: %s", code, exc)
        return {"error": f"SEC companyfacts request failed: {exc}"}

    gaap = (facts.get("facts") or {}).get("us-gaap") if isinstance(facts, dict) else None
    if not isinstance(gaap, dict):
        return {"periods": []}

    periods_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for concept_name in _SEC_CONCEPTS[statement]:
        concept = gaap.get(concept_name)
        units = concept.get("units") if isinstance(concept, dict) else None
        if not isinstance(units, dict):
            continue
        unit_key, rows = _pick_sec_unit(units)
        for row in rows:
            if not isinstance(row, dict) or not _sec_period_matches(row, period):
                continue
            end = row.get("end")
            value = _to_number(row.get("val"))
            if not end or value is None:
                continue
            key = (end, row.get("fy"), row.get("fp"), row.get("form"), row.get("accn"))
            period_row = periods_by_key.setdefault(
                key,
                {
                    "REPORT_DATE": end,
                    "FISCAL_YEAR": row.get("fy"),
                    "FISCAL_PERIOD": row.get("fp"),
                    "FORM": row.get("form"),
                    "ACCESSION": row.get("accn"),
                    "_units": {},
                },
            )
            period_row[concept_name] = value
            period_row["_units"][concept_name] = unit_key

    periods = sorted(
        periods_by_key.values(),
        key=lambda row: str(row.get("REPORT_DATE") or ""),
        reverse=True,
    )
    return {"periods": _cap_periods(periods, limit, keep)}


def _classify_market(code: str) -> str | None:
    """Classify a symbol's suffix into ``a_share``, ``us``, ``hk``, or ``None``.

    Args:
        code: Symbol with a market suffix (e.g. ``"600519.SH"``, ``"AAPL.US"``).

    Returns:
        The market label, or ``None`` when the suffix is unrecognized.
    """
    suffix = code.rpartition(".")[2].strip().upper()
    if suffix in ("SH", "SZ", "BJ"):
        return "a_share"
    if suffix == "US":
        return "us"
    if suffix == "HK":
        return "hk"
    return None


class FinancialStatementsTool(BaseTool):
    """Fetch a stock's three financial statements or key per-period indicators."""

    name = "get_financial_statements"
    description = (
        "Fetch a single stock's financial statements: balance sheet, income "
        "statement, cash-flow statement, or key per-period indicators (margins, "
        "ROE, EPS, etc.). Markets: A-share (.SH/.SZ/.BJ), US (.US) and "
        "Hong Kong (.HK). US uses SEC EDGAR companyfacts; A-share and HK use "
        "Eastmoney. Reports come back newest-first as flat per-period rows. Use "
        'this to read fundamentals before building a valuation or screen. Example: '
        '{"code": "600519.SH", "statement": "income", "period": "annual"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Single symbol with a market suffix, e.g. '600519.SH', "
                    "'000001.SZ', 'AAPL.US', or '00700.HK'."
                ),
            },
            "statement": {
                "type": "string",
                "enum": list(_VALID_STATEMENTS),
                "description": (
                    "Which report to fetch: 'balance' (balance sheet), 'income' "
                    "(income statement), 'cashflow' (cash-flow statement), or "
                    "'indicators' (key per-period indicators)."
                ),
                "default": "indicators",
            },
            "period": {
                "type": "string",
                "enum": list(_VALID_PERIODS),
                "description": (
                    "Reporting cadence: 'annual' (annual reports) or 'quarter' "
                    "(quarterly reports)."
                ),
                "default": "annual",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "How many most-recent periods to return "
                    f"(1-{_MAX_PERIODS}). Defaults to {_DEFAULT_PERIODS}. Raise it "
                    "only when a long history is genuinely needed: each period "
                    "carries the full field set."
                ),
                "default": _DEFAULT_PERIODS,
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Which line items to return. Omit for a curated core set of "
                    "~20-25 analyst-relevant fields per statement (INCOME: "
                    "TOTAL_OPERATE_INCOME / PARENT_NETPROFIT / BASIC_EPS ...; "
                    "BALANCE: TOTAL_ASSETS / INVENTORY / TOTAL_LIABILITIES ...; "
                    "CASHFLOW: NETCASH_OPERATE / NETCASH_INVEST ...). Pass explicit "
                    "names for anything else, or ['*'] for every provider field "
                    "(~200 per period, very large)."
                ),
            },
        },
        "required": ["code"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Validate inputs, dispatch by market, and return a JSON envelope.

        Args:
            **kwargs: ``code`` (str, required), ``statement`` (one of balance|
                income|cashflow|indicators, default 'indicators'), ``period``
                (annual|quarter, default 'annual'), ``limit`` (periods to
                return, default 8), ``fields`` (explicit line items, or ``['*']``
                for every provider field; omitted means the curated core set).

        Returns:
            A JSON string ``{"ok": true, "market": str, "source": str,
            "statement": str, "period": str, "data": {...}}`` when the fetch
            yields data, ``{"ok": false, "error": ...}`` when validation fails,
            or the same envelope with ``ok: false`` plus a top-level ``error``
            when the per-market fetch failed for every requested code (so a
            nested fetch error is never masked by a top-level ``ok: true``).
        """
        code = kwargs.get("code")
        if not isinstance(code, str) or not code.strip():
            return _error("code must be a non-empty symbol string")
        code = code.strip()

        statement = kwargs.get("statement", "indicators")
        if statement not in _VALID_STATEMENTS:
            return _error(f"statement must be one of {list(_VALID_STATEMENTS)}")

        period = kwargs.get("period", "annual")
        if period not in _VALID_PERIODS:
            return _error(f"period must be one of {list(_VALID_PERIODS)}")

        market = _classify_market(code)
        if market is None:
            return _error(
                "code must carry a supported suffix: .SH/.SZ/.BJ, .US, or .HK"
            )

        limit = _clamp_periods(kwargs.get("limit", _DEFAULT_PERIODS))
        raw_fields = kwargs.get("fields")
        fields = [str(f) for f in raw_fields] if isinstance(raw_fields, list) else None
        keep = _resolve_fields(statement, fields, curated=market != "us")

        if market == "us":
            result = _fetch_sec_statement(
                code, statement=statement, period=period, limit=limit, keep=keep
            )
            source = "sec_edgar"
        else:
            result = _fetch_eastmoney_statement(
                code, statement=statement, period=period, limit=limit, keep=keep
            )
            source = "eastmoney"

        # The fetch failed for every requested code (here, the single ``code``)
        # iff its result carries an ``error``. Surface that as a top-level
        # ``ok: false`` so a nested failure is never masked by ``ok: true``.
        all_failed = "error" in result
        envelope: dict[str, Any] = {
            "ok": not all_failed,
            "market": market,
            "source": source,
            "statement": statement,
            "period": period,
            "data": {code: result},
        }
        if not all_failed and keep is not None:
            # Tell the caller the payload was projected, so a missing line item
            # is never mistaken for an unreported one.
            envelope["fields_mode"] = "core"
            envelope["fields_available"] = (
                "pass fields=['<name>', ...] for specific items, "
                "or fields=['*'] for every provider field"
            )
        if all_failed:
            envelope["error"] = result["error"]
        return json.dumps(envelope, ensure_ascii=False)
