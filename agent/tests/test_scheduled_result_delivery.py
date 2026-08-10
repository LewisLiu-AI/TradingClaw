"""Unit tests for scheduled-result channel delivery (0.1.11).

Covers the helpers added to ``src.api.scheduled_routes``: waiting for a
scheduled research run's final reply and publishing it to channel-bound chats
selected per job via ``config["channels"]``.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from src.api import scheduled_routes


class _Message:
    def __init__(self, role: str, content: str, linked_attempt_id=None) -> None:
        self.role = role
        self.content = content
        self.linked_attempt_id = linked_attempt_id


class _FakeSessionService:
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


def _job(job_id: str = "job-1", prompt: str = "盘前扫描", channels=None) -> types.SimpleNamespace:
    config = {}
    if channels:
        config["channels"] = channels
    return types.SimpleNamespace(id=job_id, prompt=prompt, config=config)


# --- _wait_for_scheduled_reply -------------------------------------------------


def test_wait_for_scheduled_reply_returns_linked_message(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(scheduled_routes, "_scheduled_run_timeout_s", lambda: 30.0)
    svc = _FakeSessionService(
        [_Message("user", "prompt"), _Message("assistant", "未关联的回答", linked_attempt_id=None)]
    )
    reply = asyncio.run(scheduled_routes._wait_for_scheduled_reply(svc, "s1", None))
    assert reply is not None
    assert reply.content == "未关联的回答"


def test_wait_for_scheduled_reply_times_out_without_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduled_routes, "_scheduled_run_timeout_s", lambda: -1000.0)
    svc = _FakeSessionService([_Message("user", "prompt")])
    reply = asyncio.run(scheduled_routes._wait_for_scheduled_reply(svc, "s1", "abc"))
    assert reply is None


# --- _deliver_scheduled_result -------------------------------------------------


def test_deliver_scheduled_result_publishes_to_selected_channels() -> None:
    runtime = _FakeRuntime(
        {"feishu:ou_123": "sess-f", "weixin:o9cq800@im.wechat": "sess-w"}
    )
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(
            _fake_host(runtime), "最终研究结果", _job(channels=["feishu"])
        )
    )
    sent = runtime.bus.sent
    assert len(sent) == 1
    assert sent[0].channel == "feishu"
    assert sent[0].chat_id == "ou_123"
    assert sent[0].content.startswith("📊 定时研究结果")
    assert "最终研究结果" in sent[0].content
    assert sent[0].metadata["_scheduled_result"] is True


def test_deliver_scheduled_result_multi_channel() -> None:
    runtime = _FakeRuntime(
        {"feishu:ou_123": "sess-f", "weixin:o9cq800@im.wechat": "sess-w"}
    )
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(
            _fake_host(runtime), "结果", _job(channels=["feishu", "weixin"])
        )
    )
    assert {m.channel for m in runtime.bus.sent} == {"feishu", "weixin"}
    assert len(runtime.bus.sent) == 2


def test_deliver_scheduled_result_skips_without_channels() -> None:
    runtime = _FakeRuntime({"feishu:ou_123": "sess-f"})
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(_fake_host(runtime), "结果", _job(channels=[]))
    )
    assert runtime.bus.sent == []


def test_deliver_scheduled_result_ignores_channel_without_bound_chat() -> None:
    runtime = _FakeRuntime({"feishu:ou_123": "sess-f"})
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(
            _fake_host(runtime), "结果", _job(channels=["weixin"])
        )
    )
    assert runtime.bus.sent == []


def test_deliver_scheduled_result_skips_without_runtime() -> None:
    host = types.SimpleNamespace(_get_channel_runtime=lambda: None)
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(host, "结果", _job(channels=["feishu"]))
    )


# --- _available_delivery_channels ---------------------------------------------


def test_available_delivery_channels_returns_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.channels.config as channels_config
    import src.channels.registry as channels_registry

    monkeypatch.setattr(
        channels_config,
        "load_channels_config",
        lambda: {
            "feishu": {"enabled": True},
            "weixin": {"enabled": True},
            "telegram": {"enabled": False},
        },
    )
    monkeypatch.setattr(
        channels_registry,
        "inspect_channels",
        lambda config: {
            "feishu": {"name": "feishu", "display_name": "飞书", "enabled": True},
            "weixin": {"name": "weixin", "display_name": "微信", "enabled": True},
            "telegram": {"name": "telegram", "display_name": "Telegram", "enabled": False},
        },
    )
    got = scheduled_routes._available_delivery_channels()
    assert [c["name"] for c in got] == ["feishu", "weixin"]
    assert got[0]["display_name"] == "飞书"
