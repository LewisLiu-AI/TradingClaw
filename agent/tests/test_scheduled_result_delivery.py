"""Unit tests for scheduled-result channel delivery.

Covers the helpers added to ``src.api.scheduled_routes``: waiting for a
scheduled research run's final reply and publishing it to every channel-bound
chat (Feishu/WeChat users that paired with the bot).
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

import pytest

from src.api import scheduled_routes


class _Message:
    def __init__(self, role: str, content: str, linked_attempt_id=None) -> None:
        self.role = role
        self.content = content
        self.linked_attempt_id = linked_attempt_id


class _FakeSessionService:
    """Minimal stand-in exposing just ``get_messages``."""

    def __init__(self, messages) -> None:
        self._messages = messages

    def get_messages(self, session_id: str, limit: int = 100):
        return self._messages


class _FakeBus:
    def __init__(self) -> None:
        self.sent: list = []

    async def publish_outbound(self, msg) -> None:
        self.sent.append(msg)


class _FakeRuntime:
    def __init__(self, session_map) -> None:
        self.bus = _FakeBus()
        self._session_map = session_map


def _fake_host(runtime) -> types.SimpleNamespace:
    return types.SimpleNamespace(_get_channel_runtime=lambda: runtime)


def _job(job_id: str = "job-1", prompt: str = "盘前扫描") -> types.SimpleNamespace:
    return types.SimpleNamespace(id=job_id, prompt=prompt)


def test_wait_for_scheduled_reply_returns_linked_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns the assistant message linked to the attempt id."""
    monkeypatch.setattr(scheduled_routes, "_scheduled_run_timeout_s", lambda: 30.0)
    svc = _FakeSessionService(
        [
            _Message("user", "prompt"),
            _Message("assistant", "旧回答", linked_attempt_id="old"),
            _Message("assistant", "这是结果", linked_attempt_id="abc"),
        ]
    )
    reply = asyncio.run(scheduled_routes._wait_for_scheduled_reply(svc, "s1", "abc"))
    assert reply is not None
    assert reply.content == "这是结果"


def test_wait_for_scheduled_reply_falls_back_to_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falls back to the most recent assistant message when nothing links."""
    monkeypatch.setattr(scheduled_routes, "_scheduled_run_timeout_s", lambda: 30.0)
    svc = _FakeSessionService(
        [
            _Message("user", "prompt"),
            _Message("assistant", "未关联的回答", linked_attempt_id=None),
        ]
    )
    reply = asyncio.run(scheduled_routes._wait_for_scheduled_reply(svc, "s1", None))
    assert reply is not None
    assert reply.content == "未关联的回答"


def test_wait_for_scheduled_reply_times_out_without_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns None when no assistant message exists within the timeout."""
    # A past deadline means the loop never spins and no sleep is incurred.
    monkeypatch.setattr(scheduled_routes, "_scheduled_run_timeout_s", lambda: -1000.0)
    svc = _FakeSessionService([_Message("user", "prompt")])
    reply = asyncio.run(scheduled_routes._wait_for_scheduled_reply(svc, "s1", "abc"))
    assert reply is None


def test_deliver_scheduled_result_publishes_to_bound_channels() -> None:
    """Publishes one outbound message per channel-bound chat."""
    runtime = _FakeRuntime(
        {"feishu:ou_123": "sess-f", "weixin:o9cq800@im.wechat": "sess-w"}
    )
    host = _fake_host(runtime)
    asyncio.run(scheduled_routes._deliver_scheduled_result(host, "最终研究结果", _job()))

    sent = runtime.bus.sent
    assert len(sent) == 2
    by_channel = {m.channel: m for m in sent}
    assert "feishu" in by_channel and "weixin" in by_channel
    assert by_channel["feishu"].chat_id == "ou_123"
    assert by_channel["weixin"].chat_id == "o9cq800@im.wechat"
    for msg in sent:
        assert msg.content.startswith("📊 定时研究结果")
        assert "最终研究结果" in msg.content
        assert msg.metadata["_scheduled_result"] is True
        assert msg.metadata["job_id"] == "job-1"


def test_deliver_scheduled_result_skips_without_runtime() -> None:
    """No-op when the host has no channel runtime wired."""
    host = types.SimpleNamespace(_get_channel_runtime=lambda: None)
    asyncio.run(scheduled_routes._deliver_scheduled_result(host, "结果", _job()))
    # Would raise on a missing bus if it tried to publish.


def test_deliver_scheduled_result_skips_without_bound_chats() -> None:
    """No-op when the session map is empty."""
    runtime = _FakeRuntime({})
    host = _fake_host(runtime)
    asyncio.run(scheduled_routes._deliver_scheduled_result(host, "结果", _job()))
    assert runtime.bus.sent == []


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1", True),
        ("true", True),
        ("on", True),
        ("", False),
        ("0", False),
        ("no", False),
    ],
)
def test_scheduled_channel_delivery_enabled(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("VIBE_TRADING_SCHEDULED_DELIVER_CHANNELS", value)
    assert scheduled_routes._scheduled_channel_delivery_enabled() is expected
