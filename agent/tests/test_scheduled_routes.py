"""Route-level contracts for the scheduled research endpoints.

Exercises the REST surface mounted by ``register_scheduled_routes``:
``POST /scheduled-runs`` (create), ``GET /scheduled-runs`` (list + filter),
``DELETE /scheduled-runs/{job_id}`` (cancel), and
``POST /scheduled-runs/{job_id}/run`` (manual run-now). Each test drives the
app through ``TestClient`` and asserts the persisted store state, so the route
wiring, validation, and status codes are covered end to end.

The store singleton is redirected to a per-test ``tmp_path`` file so nothing
touches the real runtime root, and the default ``TestClient`` client host
(``testclient``) is treated as a loopback caller, so ``require_auth`` passes
without a configured API key.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import scheduled_routes
from src.scheduled_research.models import JobStatus, ScheduledResearchJob
from src.scheduled_research.store import ScheduledResearchJobStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduledResearchJobStore:
    """Isolate the module-level store singleton onto a temp file."""
    isolated = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", isolated)
    return isolated


@pytest.fixture
def client(store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _seed(store: ScheduledResearchJobStore, **overrides: object) -> ScheduledResearchJob:
    defaults: dict[str, object] = {
        "id": "job-seed",
        "prompt": "scan momentum names",
        "schedule": "60000",
        "next_run_at": 1_700_000_000_000,
        "status": JobStatus.PENDING,
        "created_at": 1_700_000_000_000,
    }
    defaults.update(overrides)
    job = ScheduledResearchJob(**defaults)  # type: ignore[arg-type]
    store.upsert(job)
    return job


def test_create_persists_job_and_returns_201(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "daily-scan",
            "prompt": "rank S&P 500 by 12-1 momentum",
            "schedule": "0 9 * * *",
            "config": {"universe": "sp500"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "daily-scan"
    assert body["status"] == "pending"
    assert body["config"] == {"universe": "sp500"}

    stored = store.get("daily-scan")
    assert stored is not None
    assert stored.prompt == "rank S&P 500 by 12-1 momentum"
    assert stored.schedule == "0 9 * * *"


def test_edit_preserves_next_run_when_replacing_job(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="job-seed", next_run_at=1_700_000_000_000)
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "job-seed",
            "prompt": "changed prompt",
            "schedule": "60000",
            "config": {"channels": ["feishu"]},
        },
    )

    assert response.status_code == 201
    body = response.json()
    # Re-POST without next_run_at must not reset the schedule position.
    assert body["next_run_at"] == 1_700_000_000_000
    assert body["config"] == {"channels": ["feishu"]}
    stored = store.get("job-seed")
    assert stored is not None
    assert stored.prompt == "changed prompt"


def test_create_generates_id_and_defaults_next_run_when_omitted(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={"prompt": "rebalance check", "schedule": "300000"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["next_run_at"] > 0
    assert store.get(body["id"]) is not None


def test_create_rejects_malformed_schedule_with_422(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.post(
        "/scheduled-runs",
        json={"prompt": "bad cron", "schedule": "0 99 * * *"},
    )

    assert response.status_code == 422
    assert store.list_jobs() == []


def test_list_returns_jobs_newest_first(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="older", created_at=1_700_000_000_000)
    _seed(store, id="newer", created_at=1_700_000_500_000)

    response = client.get("/scheduled-runs")

    assert response.status_code == 200
    ids = [job["id"] for job in response.json()]
    assert ids == ["newer", "older"]


def test_list_filters_by_status(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="pending-one", status=JobStatus.PENDING)
    _seed(store, id="done-one", status=JobStatus.COMPLETED)

    response = client.get("/scheduled-runs", params={"status": "completed"})

    assert response.status_code == 200
    body = response.json()
    assert [job["id"] for job in body] == ["done-one"]


def test_list_rejects_out_of_range_limit(client: TestClient):
    assert client.get("/scheduled-runs", params={"limit": 0}).status_code == 422
    assert client.get("/scheduled-runs", params={"limit": 500}).status_code == 422


def test_delete_removes_job_and_returns_204(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="cancel-me")

    response = client.delete("/scheduled-runs/cancel-me")

    assert response.status_code == 204
    assert not response.content
    assert store.get("cancel-me") is None


def test_delete_unknown_job_returns_404(
    client: TestClient, store: ScheduledResearchJobStore
):
    response = client.delete("/scheduled-runs/never-existed")

    assert response.status_code == 404


def test_delete_rejects_unsafe_job_id(
    client: TestClient, store: ScheduledResearchJobStore
):
    # A single path segment that still fails the safe-id pattern (the dot is
    # outside ``[A-Za-z0-9_-]``) is rejected by the handler before any store
    # lookup, so it returns 400 rather than the 404 used for unknown ids.
    response = client.delete("/scheduled-runs/bad.id")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /scheduled-runs/{job_id}/run (manual run-now)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[ScheduledResearchJob]:
    """Replace the dispatch callable with a no-op recording its calls."""
    calls: list[ScheduledResearchJob] = []

    async def _dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job)

    monkeypatch.setattr(
        scheduled_routes, "_dispatch_scheduled_research_job", _dispatch
    )
    return calls


def _wait_until_finished(
    store: ScheduledResearchJobStore, job_id: str, timeout_s: float = 5.0
) -> ScheduledResearchJob:
    """Poll the store until the background run-now task wrote its completion."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job is not None and job.status != JobStatus.RUNNING:
            return job
        time.sleep(0.02)
    raise AssertionError(f"run-now task for {job_id} did not finish in time")


def test_run_now_dispatches_and_persists_completion(
    client: TestClient,
    store: ScheduledResearchJobStore,
    fake_dispatch: list[ScheduledResearchJob],
):
    _seed(store, id="job-seed", status=JobStatus.COMPLETED)

    response = client.post("/scheduled-runs/job-seed/run")

    assert response.status_code == 202
    # The run is accepted asynchronously: the response snapshot is written
    # after the synchronous RUNNING flip, before the background task starts.
    assert response.json()["status"] == "running"

    finished = _wait_until_finished(store, "job-seed")
    assert len(fake_dispatch) == 1
    assert fake_dispatch[0].id == "job-seed"
    assert finished.status == JobStatus.COMPLETED
    assert finished.last_run_at is not None


def test_run_now_does_not_advance_next_run_at(
    client: TestClient,
    store: ScheduledResearchJobStore,
    fake_dispatch: list[ScheduledResearchJob],
):
    _seed(store, id="job-seed", next_run_at=1_700_000_000_000)

    response = client.post("/scheduled-runs/job-seed/run")
    assert response.status_code == 202

    finished = _wait_until_finished(store, "job-seed")
    # A manual trigger is an extra run: the schedule position is untouched.
    assert finished.next_run_at == 1_700_000_000_000


def test_run_now_records_failure_when_dispatch_raises(
    client: TestClient,
    store: ScheduledResearchJobStore,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _failing_dispatch(job: ScheduledResearchJob) -> None:
        raise RuntimeError("session runtime unavailable")

    monkeypatch.setattr(
        scheduled_routes, "_dispatch_scheduled_research_job", _failing_dispatch
    )
    _seed(store, id="job-seed")

    response = client.post("/scheduled-runs/job-seed/run")
    assert response.status_code == 202

    finished = _wait_until_finished(store, "job-seed")
    assert finished.status == JobStatus.FAILED
    assert finished.last_run_at is not None


def test_run_now_unknown_job_returns_404(client: TestClient):
    response = client.post("/scheduled-runs/never-existed/run")

    assert response.status_code == 404


def test_run_now_rejects_already_running_job_with_409(
    client: TestClient, store: ScheduledResearchJobStore
):
    _seed(store, id="job-seed", status=JobStatus.RUNNING)

    response = client.post("/scheduled-runs/job-seed/run")

    assert response.status_code == 409


def test_run_now_rejects_unsafe_job_id(client: TestClient):
    response = client.post("/scheduled-runs/bad.id/run")

    assert response.status_code == 400
