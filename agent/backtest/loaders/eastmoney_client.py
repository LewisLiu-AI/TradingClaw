"""Shared Eastmoney HTTP client: secid resolution + push2his kline fetch.

Eastmoney exposes free, no-auth quote endpoints but rate-limits aggressively by
source IP and will temporarily ban a bursting client, so every request here
routes through :mod:`backtest.loaders._http` for per-host throttling and session
reuse. This module is provider-internal plumbing shared by the Eastmoney-backed
loaders; it only knows Eastmoney's ``secid`` addressing scheme and the
``push2his`` kline JSON layout, not any loader's DataFrame conventions.

Eastmoney addresses every instrument by a ``secid`` of the form ``<market>.<code>``:

* A-shares — Shanghai (``.SH``, plus ``.BJ`` Beijing exchange) use market ``1``
  for SH and ``0`` for SZ/BJ.
* Hong Kong (``.HK``) uses market ``116`` with the numeric code zero-padded to
  five digits.
* US (``.US``) markets (NASDAQ ``105`` / NYSE ``106`` / AMEX ``107``) are not
  derivable from the ticker alone, so the market prefix is discovered once via
  Eastmoney's search/suggest endpoint and cached for the life of the process.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

from backtest.loaders._http import resolve_min_interval, throttled_get_json
from backtest.loaders.juliang_proxy import get_juliang_client

logger = logging.getLogger(__name__)

# Eastmoney kline endpoints. push2his serves historical bars; searchapi resolves
# a free-text ticker to its fully-qualified secid (needed for US tickers).
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"

# Throttle/session bucket shared by all Eastmoney calls.
_HOST_KEY = "eastmoney"
_MIN_INTERVAL_ENV = "VIBE_TRADING_EASTMONEY_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL = 1.0

# Eastmoney kline period codes (``klt``) keyed by our interval labels.
KLT_BY_INTERVAL: dict[str, int] = {
    "1D": 101,
    "1W": 102,
    "1M": 103,
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "60m": 60,
}

# push2his column selectors: fields1 picks the per-request meta, fields2 picks
# the per-bar columns in order: date, open, close, high, low, volume, amount.
_FIELDS1 = "f1,f2,f3,f4,f5,f6"
_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57"

# Process-level cache of resolved US secids so a repeated ticker never re-hits
# the search endpoint. Keyed by the upper-cased bare ticker (e.g. "AAPL").
_US_SECID_CACHE: dict[str, str | None] = {}

# ---------------------------------------------------------------------------
# Juliang proxy routing (unblocks WAF-blocked Eastmoney quote hosts)
# ---------------------------------------------------------------------------

# Eastmoney hosts whose connections are WAF-blocked from datacenter IPs. Only
# these are routed through the Juliang dynamic proxy; the datacenter/search/report
# hosts stay direct (they are reachable from the production server).
_JULIANG_PROXIED_HOSTS_DEFAULT = ("push2.eastmoney.com", "push2his.eastmoney.com")
_JULIANG_HOSTS_ENV = "VIBE_TRADING_JULIANG_HOSTS"

# Direct-first circuit breaker: after consecutive direct failures, skip the
# doomed direct attempt for a cooldown window so a blocked IP does not pay one
# failed connection per request.
_DIRECT_BREAKER_MAX_FAILURES = 2
_DIRECT_BREAKER_COOLDOWN_S = 60.0


def _juliang_proxied_hosts() -> frozenset[str]:
    """Return the Eastmoney hosts to route through the Juliang proxy.

    ``VIBE_TRADING_JULIANG_HOSTS`` (comma-separated) overrides the default set.
    """
    override = os.environ.get(_JULIANG_HOSTS_ENV, "").strip()
    if override:
        return frozenset(h.strip().lower() for h in override.split(",") if h.strip())
    return frozenset(_JULIANG_PROXIED_HOSTS_DEFAULT)


class _DirectCircuitBreaker:
    """Tracks consecutive direct failures so a blocked IP skips the direct path."""

    def __init__(self, max_failures: int, cooldown_s: float) -> None:
        self._max_failures = max_failures
        self._cooldown_s = cooldown_s
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._max_failures:
                self._open_until = time.monotonic() + self._cooldown_s

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def should_skip_direct(self) -> bool:
        with self._lock:
            return time.monotonic() < self._open_until


_DIRECT_BREAKER = _DirectCircuitBreaker(_DIRECT_BREAKER_MAX_FAILURES, _DIRECT_BREAKER_COOLDOWN_S)

# A JSONP envelope is a JS callback identifier followed by a parenthesized body,
# optionally terminated by ';'. The identifier is restricted to legal JS names
# (incl. dotted namespaces like "jQuery.cb") so a plain JSON array/object body —
# which never starts this way — is left untouched.
_JSONP_WRAPPER = re.compile(
    r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*\((.*)\)\s*;?\s*$",
    re.DOTALL,
)


def _min_interval() -> float:
    """Resolve the per-call minimum Eastmoney request spacing in seconds."""
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL)


def _should_proxy(url: str) -> bool:
    """Return True when ``url`` should be routed through the Juliang proxy."""
    client = get_juliang_client()
    if not client.is_enabled() or not client.is_configured():
        return False
    host = re.sub(r"^[a-z]+://", "", url.lower()).split("/", 1)[0].split(":", 1)[0]
    return host in _juliang_proxied_hosts()


# Bad nodes are common with dynamic proxies (~30% in practice), so each request
# through a failing node re-extracts a fresh proxy and retries, up to this many
# total attempts per request.
_MAX_PROXY_TRIES = 5


def _get_json_via_proxy(url: str, params: dict[str, Any]) -> Any:
    """GET ``url`` through a (reused) Juliang proxy, re-extracting on failure.

    Reuses the pooled proxy for as long as it is valid; when a request through
    it fails, invalidates it and retries with freshly extracted proxies (up to
    ``_MAX_PROXY_TRIES`` total attempts) to ride out bad dynamic-proxy nodes.
    """
    client = get_juliang_client()
    last_exc: requests.RequestException | None = None
    for _ in range(_MAX_PROXY_TRIES):
        entry = client.get_proxy()
        if entry is None:
            break
        try:
            return throttled_get_json(
                url,
                host_key=_HOST_KEY,
                min_interval=_min_interval(),
                params=params,
                proxies=entry.proxies_dict(),
            )
        except requests.RequestException as exc:
            last_exc = exc
            client.invalidate()  # next get_proxy() extracts a fresh proxy
    if last_exc is not None:
        raise last_exc
    raise requests.RequestException("Juliang proxy unavailable for Eastmoney request")


def get_json(url: str, *, params: dict[str, Any]) -> Any:
    """Issue a throttled Eastmoney GET and decode the body as JSON.

    When the URL targets an Eastmoney quote host that WAF-blocks the caller's IP
    (``push2`` / ``push2his``) and the Juliang proxy is enabled, the request is
    tried direct first and, on failure, routed through the pooled Juliang
    dynamic proxy. A circuit breaker skips the doomed direct attempt after
    repeated failures so a blocked IP does not pay one failed connection per
    request.

    Args:
        url: Fully-qualified Eastmoney endpoint URL.
        params: Query parameters for the request.

    Returns:
        The decoded JSON payload (typically a ``dict``).

    Raises:
        requests.RequestException: Network failure, propagated for the caller's
            retry policy.
        requests.HTTPError: Non-2xx response status.
        ValueError: Body is not valid JSON.
    """
    if not _should_proxy(url):
        return throttled_get_json(
            url,
            host_key=_HOST_KEY,
            min_interval=_min_interval(),
            params=params,
        )

    direct_exc: requests.RequestException | None = None
    if not _DIRECT_BREAKER.should_skip_direct():
        try:
            result = throttled_get_json(
                url,
                host_key=_HOST_KEY,
                min_interval=_min_interval(),
                params=params,
            )
            _DIRECT_BREAKER.record_success()
            return result
        except requests.RequestException as exc:
            direct_exc = exc
            _DIRECT_BREAKER.record_failure()
    try:
        return _get_json_via_proxy(url, params)
    except requests.RequestException as proxy_exc:
        if direct_exc is not None:
            raise direct_exc from proxy_exc
        raise


def _resolve_a_share_secid(code: str, suffix: str) -> str | None:
    """Map an A-share ``code`` + exchange ``suffix`` to its Eastmoney secid.

    SH instruments live on market ``1``; SZ and BJ (Beijing exchange) on ``0``.
    """
    if suffix == "SH":
        return f"1.{code}"
    if suffix in ("SZ", "BJ"):
        return f"0.{code}"
    return None


def _parse_us_secid(payload: Any) -> str | None:
    """Extract a US ``<market>.<code>`` secid from a search/suggest payload.

    Eastmoney's suggest endpoint returns candidates under
    ``QuotationCodeTable.Data``, each carrying a ``QuoteID`` already in
    ``<market>.<code>`` form. The first US-market (105/106/107) candidate wins.

    Args:
        payload: Decoded JSON from the search endpoint.

    Returns:
        The first matching US secid, or ``None`` when no US candidate is found.
    """
    if not isinstance(payload, dict):
        return None
    table = payload.get("QuotationCodeTable")
    if not isinstance(table, dict):
        return None
    candidates = table.get("Data")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        quote_id = candidate.get("QuoteID")
        if not isinstance(quote_id, str) or "." not in quote_id:
            continue
        market = quote_id.split(".", 1)[0]
        if market in ("105", "106", "107"):
            return quote_id
    return None


def _strip_jsonp(text: str) -> Any:
    """Decode a possibly JSONP-wrapped body to a Python object.

    The suggest endpoint sometimes wraps its JSON in a ``callback(...)`` envelope.
    A plain JSON body is parsed as-is first; only a body that actually matches a
    leading callback identifier is unwrapped. This avoids corrupting plain JSON
    whose string values contain parentheses (an earlier first-``(`` / last-``)``
    slice mangled such bodies and returned ``None``).

    Args:
        text: Raw response body.

    Returns:
        The decoded object, or ``None`` when nothing parseable is found.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        pass
    match = _JSONP_WRAPPER.match(stripped)
    if match is None:
        return None
    try:
        return json.loads(match.group(1).strip())
    except (ValueError, TypeError):
        return None


def _resolve_us_secid(code: str) -> str | None:
    """Resolve a US ticker to its Eastmoney secid via search, with caching.

    Args:
        code: Bare upper-cased US ticker (e.g. ``"AAPL"``).

    Returns:
        The resolved ``<market>.<code>`` secid, or ``None`` when unresolvable.
    """
    if code in _US_SECID_CACHE:
        return _US_SECID_CACHE[code]

    secid: str | None = None
    try:
        payload = get_json(
            _SEARCH_URL,
            params={"input": code, "type": "14", "count": "10"},
        )
        if isinstance(payload, str):
            payload = _strip_jsonp(payload)
        secid = _parse_us_secid(payload)
    except Exception as exc:  # noqa: BLE001 - an unresolved ticker is non-fatal
        logger.warning("eastmoney secid search failed for %s: %s", code, exc)
        secid = None

    _US_SECID_CACHE[code] = secid
    return secid


def resolve_secid(symbol: str) -> str | None:
    """Map a Vibe-Trading symbol to its Eastmoney secid.

    Supported suffixes: ``.SH`` / ``.SZ`` / ``.BJ`` (A-share), ``.HK`` (Hong
    Kong, code zero-padded to five digits), ``.US`` (resolved via search and
    cached). A symbol with no recognized suffix, or a US ticker the search
    cannot place, returns ``None``.

    Args:
        symbol: Symbol such as ``"600519.SH"``, ``"00700.HK"`` or ``"AAPL.US"``.

    Returns:
        The Eastmoney secid (e.g. ``"1.600519"``), or ``None`` if unresolvable.
    """
    if not symbol or "." not in symbol:
        return None
    code, _, suffix = symbol.rpartition(".")
    code = code.strip().upper()
    suffix = suffix.strip().upper()
    if not code:
        return None

    if suffix in ("SH", "SZ", "BJ"):
        return _resolve_a_share_secid(code, suffix)
    if suffix == "HK":
        return f"116.{code.zfill(5)}"
    if suffix == "US":
        return _resolve_us_secid(code)
    return None


def _parse_kline_row(raw: str) -> dict[str, Any] | None:
    """Parse one comma-joined push2his kline row into an OHLCV dict.

    Column order follows ``fields2``: date, open, close, high, low, volume,
    amount.

    Args:
        raw: One row string from ``data.klines``.

    Returns:
        A dict ``{trade_date, open, high, low, close, volume, amount}``, or
        ``None`` when the row is malformed.
    """
    parts = raw.split(",")
    if len(parts) < 7:
        return None
    try:
        return {
            "trade_date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
        }
    except (ValueError, TypeError):
        return None


def fetch_kline(
    secid: str,
    *,
    klt: int,
    fqt: int = 1,
    beg: str = "0",
    end: str = "20500101",
) -> list[dict]:
    """Fetch ascending OHLCV bars for one ``secid`` from push2his.

    Args:
        secid: Eastmoney secid (e.g. ``"1.600519"``).
        klt: Period code from :data:`KLT_BY_INTERVAL`.
        fqt: Adjustment mode (0 raw, 1 forward-adjusted, 2 back-adjusted).
        beg: Inclusive start date ``YYYYMMDD`` or ``"0"`` for earliest.
        end: Inclusive end date ``YYYYMMDD``.

    Returns:
        Ascending list of ``{trade_date, open, high, low, close, volume,
        amount}`` dicts. Empty when the payload carries no bars.

    Raises:
        requests.RequestException: Network failure.
        requests.HTTPError: Non-2xx response status.
        ValueError: Body is not valid JSON.
    """
    payload = get_json(
        _KLINE_URL,
        params={
            "secid": secid,
            "klt": str(klt),
            "fqt": str(fqt),
            "beg": beg,
            "end": end,
            "fields1": _FIELDS1,
            "fields2": _FIELDS2,
            "rev": "1",
            "lmt": "1000000",
        },
    )

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    klines = data.get("klines")
    if not isinstance(klines, list):
        return []

    rows: list[dict] = []
    for raw in klines:
        if not isinstance(raw, str):
            continue
        parsed = _parse_kline_row(raw)
        if parsed is not None:
            rows.append(parsed)
    return rows
