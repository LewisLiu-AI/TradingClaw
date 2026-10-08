"""Tests for the Juliang proxy pool: extraction parsing, reuse, invalidation.

All network calls are mocked at ``requests.get`` so no test touches a live
endpoint (and none consumes quota).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backtest.loaders.juliang_proxy import JuliangProxyClient
from src.config.accessor import reset_env_config

TEST_ENV = {
    "VIBE_TRADING_JULIANG_ENABLED": "1",
    "VIBE_TRADING_JULIANG_TRADE_NO": "2047476805247018",
    "VIBE_TRADING_JULIANG_API_KEY": "test-api-key",
    "VIBE_TRADING_JULIANG_USERNAME": "test-user",
    "VIBE_TRADING_JULIANG_PASSWORD": "test-pass",
    "VIBE_TRADING_JULIANG_PROXY_LIFETIME_S": "45",
}


@pytest.fixture()
def client(monkeypatch):
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    reset_env_config()
    yield JuliangProxyClient()
    reset_env_config()


def _payload(proxy: str = "1.2.3.4:5678", surplus: int = 1000) -> dict:
    return {
        "code": 200,
        "msg": "成功",
        "data": {
            "count": 1,
            "filter_count": 0,
            "surplus_quantity": surplus,
            "proxy_list": [proxy],
        },
    }


class TestExtraction:
    def test_extract_parses_proxy_and_surplus(self, client):
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _payload(proxy="1.2.3.4:5678", surplus=42)
            entry = client.get_proxy()

        assert entry is not None
        assert entry.host == "1.2.3.4"
        assert entry.port == 5678
        assert entry.username == "test-user"
        assert entry.password == "test-pass"
        status = client.status()
        assert status["surplus_quantity"] == 42
        assert status["current_proxy"] == "1.2.3.4:5678"
        assert status["proxy_valid"] is True

    def test_extraction_accepts_dict_proxy_list(self, client):
        payload = {
            "code": 200,
            "msg": "成功",
            "data": {
                "count": 1,
                "surplus_quantity": 7,
                "proxy_list": [{"ip": "9.9.9.9", "port": 3128}],
            },
        }
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.return_value = payload
            entry = client.get_proxy()

        assert entry is not None
        assert entry.host == "9.9.9.9"
        assert entry.port == 3128

    def test_extraction_http_error_returns_none(self, client):
        with patch(
            "backtest.loaders.juliang_proxy.requests.get",
            side_effect=RuntimeError("HTTP 500"),
        ):
            entry = client.get_proxy()

        assert entry is None
        assert "HTTP 500" in (client.status()["last_error"] or "")

    def test_extraction_rejection_code_returns_none(self, client):
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"code": 400, "msg": "参数错误", "data": None}
            entry = client.get_proxy()

        assert entry is None
        assert "参数错误" in (client.status()["last_error"] or "")


class TestReuseAndInvalidation:
    def test_get_proxy_reuses_within_lifetime(self, client):
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _payload()
            first = client.get_proxy()
            second = client.get_proxy()

        # Same object returned — no re-extraction while the proxy is valid.
        assert first is second
        assert mock_get.call_count == 1

    def test_invalidate_triggers_re_extraction(self, client):
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.side_effect = [
                _payload(proxy="1.2.3.4:5678"),
                _payload(proxy="5.6.7.8:9000"),
            ]
            first = client.get_proxy()
            client.invalidate()
            second = client.get_proxy()

        assert first.host == "1.2.3.4"
        assert second.host == "5.6.7.8"
        assert mock_get.call_count == 2

    def test_expired_proxy_re_extracts(self, client):
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.side_effect = [
                _payload(proxy="1.2.3.4:5678"),
                _payload(proxy="5.6.7.8:9000"),
            ]
            first = client.get_proxy()
            # Force the entry past its lifetime deadline.
            client._current.expires_at -= 1000  # type: ignore[union-attr]
            second = client.get_proxy()

        assert second is not None
        assert second.host == "5.6.7.8"

    def test_proxies_dict_format(self, client):
        with patch("backtest.loaders.juliang_proxy.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _payload()
            entry = client.get_proxy()

        assert entry is not None
        expected = "http://test-user:test-pass@1.2.3.4:5678"
        assert entry.proxies_dict() == {"http": expected, "https": expected}


class TestConfiguration:
    # The _config() fallback reads agent/.env directly; point it at a
    # nonexistent path so the project-local .env cannot leak real config into
    # these isolation tests.
    @pytest.fixture(autouse=True)
    def _no_env_fallback(self, monkeypatch):
        from backtest.loaders.juliang_proxy import _agent_env_path

        monkeypatch.setattr(
            "backtest.loaders.juliang_proxy._agent_env_path",
            lambda: _agent_env_path().with_name("__nonexistent__.env"),
        )

    def test_unconfigured_returns_none(self, monkeypatch):
        for key in TEST_ENV:
            monkeypatch.delenv(key, raising=False)
        reset_env_config()
        client = JuliangProxyClient()

        assert client.is_enabled() is False
        assert client.get_proxy() is None

    def test_disabled_returns_none(self, monkeypatch):
        for key, value in TEST_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("VIBE_TRADING_JULIANG_ENABLED", "0")
        reset_env_config()
        client = JuliangProxyClient()

        assert client.is_enabled() is False
        assert client.get_proxy() is None

    def test_status_reports_configuration(self, client):
        status = client.status()
        assert status["configured"] is True
        assert status["enabled"] is True
