"""MyFinance 渠道（定时结果 → App 研报）的单元测试。"""

from __future__ import annotations

import asyncio
import re
import types

import pytest

from src.api import scheduled_routes
from src.channels.bus.events import OutboundMessage
from src.channels.myfinance import (
    MyFinanceChannel,
    extract_title_and_body,
    summarize,
)


class _FakeBus:
    async def publish_outbound(self, msg) -> None:  # pragma: no cover - 不参与本测试
        raise AssertionError("channel 测试不应该往 bus 发消息")


class _StubResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"id": 42}
        self.text = "" if status_code < 300 else "boom"

    def json(self) -> dict:
        return self._payload


class _StubClient:
    """记录每次 POST 的 httpx.AsyncClient 替身。"""

    calls: list[tuple[str, dict, dict]] = []
    next_response = _StubResponse()

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url: str, json=None, headers=None):
        _StubClient.calls.append((url, json, headers or {}))
        return _StubClient.next_response


@pytest.fixture()
def stub_httpx(monkeypatch: pytest.MonkeyPatch):
    _StubClient.calls = []
    _StubClient.next_response = _StubResponse()
    monkeypatch.setattr("src.channels.myfinance.httpx.AsyncClient", _StubClient)
    return _StubClient


def _config(**overrides) -> dict:
    config = {
        "enabled": True,
        "baseUrl": "http://127.0.0.1:18889/api/v1",
        "apiToken": "mfa_test",
    }
    config.update(overrides)
    return config


def _msg(content: str) -> OutboundMessage:
    return OutboundMessage(channel="myfinance", chat_id="app", content=content)


# --- 标题/摘要解析 ---------------------------------------------------------


def test_extract_title_prefers_markdown_heading() -> None:
    text = "📊 定时研究结果 · 盘前扫描：按昨日异常成交量排名\n\n# 盘前扫描 11/09\n\n一、昨日复盘…"
    title, body = extract_title_and_body(text)
    assert title == "盘前扫描 11/09"
    # 标题行与投递前缀都不留在正文里，App 详情页只有一个标题
    assert body == "一、昨日复盘…"


def test_extract_title_falls_back_to_job_label() -> None:
    text = "📊 定时研究结果 · 使用技能 star50-warning 给科创50打分\n\n一、评分 62\n二、结论…"
    title, body = extract_title_and_body(text)
    assert title.startswith("使用技能 star50-warning 给科创50打分")
    assert re.search(r"· \d{2}-\d{2}$", title)
    assert body.startswith("一、评分")

def test_extract_title_uses_first_line_for_plain_text() -> None:
    title, _ = extract_title_and_body("科创50 昨日放量上涨，短期动量转强。\n后续关注…")
    # 没有 markdown 标题时取任务名/首段的第一个短句，并带上当天日期
    assert title.startswith("科创50 昨日放量上涨")
    assert re.search(r"· \d{2}-\d{2}$", title)


def test_extract_title_skips_chitchat_before_heading() -> None:
    text = (
        "📊 定时研究结果 · 盘前扫描：按昨日异常成交量排名\n\n"
        "数据已经全部到位。以下是完整报告。\n\n---\n\n"
        "# 盘前扫描 | 2026-11-09（周一）\n\n"
        "> **一句话定调**：周一大面积高开修复，看量能是否跟上。\n"
    )
    title, body = extract_title_and_body(text)
    assert title == "盘前扫描 | 2026-11-09（周一）"
    # 寒暄与标题行都不留在正文里
    assert body.startswith("> **一句话定调**")


def test_extract_title_clips_long_line() -> None:
    title, _ = extract_title_and_body("很长的标题" * 40)
    assert len(title) <= 60
    assert title.endswith("…") or re.search(r"· \d{2}-\d{2}$", title)


def test_summarize_prefers_call_line_from_blockquote() -> None:
    body = (
        "# 盘前扫描 | 2026-11-09\n\n"
        "> **数据基准**：A股 11/6 收盘\n"
        "> **一句话定调**：周一大面积高开修复，关键看量能能否跟上。\n\n"
        "## 一、昨日复盘\n\n指数全线低开。"
    )
    summary = summarize(body)
    assert summary.startswith("一句话定调")
    assert "量能" in summary
    assert "**" not in summary


def test_summarize_strips_markdown_and_limits_length() -> None:
    body = "# 标题\n\n**结论**：科创50 动量转强，[研报](http://x) 建议关注。\n\n第二段不该进摘要"
    summary = summarize(body)
    assert "**" not in summary
    assert "http://x" not in summary
    assert "科创50 动量转强" in summary
    assert "第二段" not in summary


# --- send -----------------------------------------------------------------


def test_send_posts_report_payload(stub_httpx) -> None:
    channel = MyFinanceChannel(_config(), _FakeBus())
    asyncio.run(channel.send(_msg("📊 定时研究结果 · 盘前扫描\n\n# 盘前扫描 11/09\n\n一、昨日复盘")))

    assert len(stub_httpx.calls) == 1
    url, payload, headers = stub_httpx.calls[0]
    assert url == "http://127.0.0.1:18889/api/v1/research-reports"
    assert headers["X-API-Token"] == "mfa_test"
    assert payload["title"] == "盘前扫描 11/09"
    assert payload["source"] == "trading_claw"
    assert payload["tags"] == "定时研报"
    assert payload["summary"]
    assert "一、昨日复盘" in payload["content"]
    assert payload["title"] not in payload["content"]
    assert "📊" not in payload["content"]


def test_send_is_idempotent_within_retry_window(stub_httpx) -> None:
    channel = MyFinanceChannel(_config(), _FakeBus())
    message = _msg("📊 定时研究结果 · 盘前扫描\n\n# 盘前扫描 11/09\n\n正文")
    asyncio.run(channel.send(message))
    asyncio.run(channel.send(message))
    assert len(stub_httpx.calls) == 1


def test_send_raises_on_rejected_push(stub_httpx) -> None:
    stub_httpx.next_response = _StubResponse(status_code=401)
    channel = MyFinanceChannel(_config(), _FakeBus())
    with pytest.raises(RuntimeError, match="401"):
        asyncio.run(channel.send(_msg("正文")))


def test_send_requires_token(stub_httpx) -> None:
    channel = MyFinanceChannel(_config(apiToken=""), _FakeBus())
    with pytest.raises(RuntimeError, match="apiToken"):
        asyncio.run(channel.send(_msg("正文")))
    assert stub_httpx.calls == []


def test_send_skips_empty_content(stub_httpx) -> None:
    channel = MyFinanceChannel(_config(), _FakeBus())
    asyncio.run(channel.send(_msg("   ")))
    assert stub_httpx.calls == []


# --- 定时投递目标 ---------------------------------------------------------


def test_scheduled_targets_default_to_app() -> None:
    channel = MyFinanceChannel(_config(), _FakeBus())
    assert channel.scheduled_targets() == ["app"]


def test_scheduled_targets_honour_configured_targets() -> None:
    channel = MyFinanceChannel(_config(targets=["phone", "tablet"]), _FakeBus())
    assert channel.scheduled_targets() == ["phone", "tablet"]


class _RecordingBus:
    def __init__(self) -> None:
        self.sent: list = []

    async def publish_outbound(self, msg) -> None:
        self.sent.append(msg)


class _Runtime:
    def __init__(self, session_map, channels) -> None:
        self.bus = _RecordingBus()
        self._session_map = session_map
        self.manager = types.SimpleNamespace(channels=channels)


def _host(runtime) -> types.SimpleNamespace:
    return types.SimpleNamespace(_get_channel_runtime=lambda: runtime)


def _job(channels: list[str]) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id="job-1",
        prompt="盘前扫描",
        config={"channels": channels},
    )


def test_deliver_uses_scheduled_targets_when_no_session(stub_httpx) -> None:
    channel = MyFinanceChannel(_config(), _FakeBus())
    runtime = _Runtime({}, {"myfinance": channel})
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(
            _host(runtime), "研报正文", _job(["myfinance"])
        )
    )
    assert len(runtime.bus.sent) == 1
    assert runtime.bus.sent[0].channel == "myfinance"
    assert runtime.bus.sent[0].chat_id == "app"
    assert runtime.bus.sent[0].metadata["job_id"] == "job-1"


def test_deliver_prefers_session_bound_chat_over_default(stub_httpx) -> None:
    channel = MyFinanceChannel(_config(), _FakeBus())
    runtime = _Runtime({"myfinance:someone": "sess-1"}, {"myfinance": channel})
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(
            _host(runtime), "研报正文", _job(["myfinance"])
        )
    )
    assert [m.chat_id for m in runtime.bus.sent] == ["someone"]


def test_deliver_skips_channel_without_targets_or_sessions(stub_httpx) -> None:
    runtime = _Runtime({}, {})
    asyncio.run(
        scheduled_routes._deliver_scheduled_result(
            _host(runtime), "研报正文", _job(["myfinance"])
        )
    )
    assert runtime.bus.sent == []
