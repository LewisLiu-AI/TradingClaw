"""API tests for ``POST /alpha/bench`` universe validation + aliasing.

The Alpha Zoo detail page deep-links into the bench form with the registry's
meta-style universe tag (``equity_us``/``equity_cn``/``crypto``), which must be
accepted and normalized onto the data-panel keys (``sp500``/``csi300``/
``btc-usdt``) — see ``_BENCH_UNIVERSE_ALIASES``. These tests pin that contract:

* **validation** runs through the real ``BenchRequest`` pydantic model via
  ``TestClient.post`` (rejection happens before any worker spawns);
* the **worker** (``_run_bench_blocking``) is stubbed so the 202 path never
  imports the pandas-heavy ``bench_runner`` or touches real data;
* the **compare** endpoint shares the same validator logic, so the alias is
  pinned there too (worker stubbed like in ``test_alpha_compare_api.py``).

Loopback ``TestClient`` (127.0.0.1) bypasses dev-mode auth, matching the
convention in ``test_alpha_compare_api.py`` / ``test_goal_api.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import alpha_routes


def _client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _clear_jobs():
    alpha_routes.ALPHA_BENCH_JOBS.clear()
    alpha_routes.ALPHA_COMPARE_JOBS.clear()
    yield
    alpha_routes.ALPHA_BENCH_JOBS.clear()
    alpha_routes.ALPHA_COMPARE_JOBS.clear()


@pytest.fixture(autouse=True)
def _stub_bench_worker(monkeypatch):
    """Replace the pandas-heavy bench worker with a job-marking no-op."""

    def _fake(job_id: str, *_a: Any, **_k: Any) -> None:
        with alpha_routes._JOBS_LOCK:
            job = alpha_routes.ALPHA_BENCH_JOBS.get(job_id)
            if job is not None:
                job["status"] = "done"
                job["result"] = {"status": "ok"}
                job["_finished_at"] = 0.0

    monkeypatch.setattr(alpha_routes, "_run_bench_blocking", _fake)


def _bench_body(**kw: Any) -> dict[str, Any]:
    body = {"zoo": "academic", "universe": "sp500", "period": "2020-2025", "top": 20}
    body.update(kw)
    return body


# ── meta-style aliases accepted + normalized ────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("equity_us", "sp500"),
        ("equity_cn", "csi300"),
        ("crypto", "btc-usdt"),
        ("sp500", "sp500"),  # panel keys pass through untouched
    ],
)
def test_bench_normalizes_universe_alias(raw: str, expected: str) -> None:
    r = _client().post("/alpha/bench", json=_bench_body(universe=raw))
    assert r.status_code == 202
    job = alpha_routes.ALPHA_BENCH_JOBS[r.json()["job_id"]]
    # The worker must receive the data-panel key, not the meta tag.
    assert job["universe"] == expected


def test_bench_still_rejects_unknown_universe() -> None:
    r = _client().post("/alpha/bench", json=_bench_body(universe="nasdaq"))
    assert r.status_code == 422
    assert "unknown universe" in str(r.json()["detail"])


def test_bench_rejects_universe_without_data_panel() -> None:
    # Aliases only cover universes bench_runner can actually load; meta tags
    # with no panel (equity_hk, futures) must keep failing validation.
    r = _client().post("/alpha/bench", json=_bench_body(universe="equity_hk"))
    assert r.status_code == 422


# ── compare shares the alias contract ───────────────────────────────────────


def test_compare_accepts_meta_universe_alias(monkeypatch) -> None:
    envelope = {"status": "ok", "universe": "sp500", "ranking": [], "skipped": []}
    seen: dict[str, Any] = {}

    def _fake_compare(alpha_ids, universe, period, **kw):
        seen["universe"] = universe
        return dict(envelope)

    monkeypatch.setattr("src.factors.compare_runner.compare_alphas", _fake_compare)
    r = _client().post(
        "/alpha/compare",
        json={
            "alpha_ids": ["alpha101_1", "alpha101_2"],
            "universe": "equity_us",
            "period": "2020-2025",
            "sort": "ir",
        },
    )
    assert r.status_code == 202
    job = alpha_routes.ALPHA_COMPARE_JOBS[r.json()["job_id"]]
    assert job["universe"] == "sp500"
    assert seen["universe"] == "sp500"


# ── request models directly (no HTTP) ───────────────────────────────────────


def test_bench_request_model_normalizes_alias() -> None:
    req = alpha_routes.BenchRequest(zoo="academic", universe="equity_us", period="2020-2025")
    assert req.universe == "sp500"


def test_bench_request_model_rejects_garbage() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        alpha_routes.BenchRequest(zoo="academic", universe="equity_mars", period="2020-2025")
