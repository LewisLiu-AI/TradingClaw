"""Tests for the easy-tdx MCP server wrapper (agent/src/tools/easytdx_mcp_server.py).

Hermetic by default: subprocess calls are monkeypatched, no TDX network access.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp.exceptions import ToolError

from src.tools import easytdx_mcp_server as srv
from src.tools.easytdx_mcp_server import parse_symbol, parse_symbols


class TestParseSymbol:
    def test_explicit_market_space(self) -> None:
        assert parse_symbol("SZ 000001") == ("SZ", "000001")
        assert parse_symbol("sh 600519") == ("SH", "600519")

    def test_explicit_market_glued(self) -> None:
        assert parse_symbol("SH600519") == ("SH", "600519")

    def test_suffix_form(self) -> None:
        assert parse_symbol("000001.SZ") == ("SZ", "000001")
        assert parse_symbol("600519.SH") == ("SH", "600519")
        assert parse_symbol("835174.BJ") == ("BJ", "835174")

    def test_bare_code_heuristics(self) -> None:
        assert parse_symbol("600519") == ("SH", "600519")
        assert parse_symbol("688017") == ("SH", "688017")
        assert parse_symbol("000001") == ("SZ", "000001")
        assert parse_symbol("300750") == ("SZ", "300750")
        assert parse_symbol("835174") == ("BJ", "835174")
        assert parse_symbol("430047") == ("BJ", "430047")

    def test_fund_and_bond_prefixes(self) -> None:
        assert parse_symbol("510300") == ("SH", "510300")
        assert parse_symbol("159915") == ("SZ", "159915")
        assert parse_symbol("113050") == ("SH", "113050")
        assert parse_symbol("123456") == ("SZ", "123456")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ToolError):
            parse_symbol("xyz")

    def test_multi_symbol_string(self) -> None:
        assert parse_symbols("000001,600519") == "SZ 000001,SH 600519"
        assert parse_symbols("SZ 000001, 600519.SH") == "SZ 000001,SH 600519"


class TestRunCli:
    def test_parses_stdout_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload: list[dict[str, Any]] = [{"close": 11.8900003433, "name": "平安银行"}]

        class Proc:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = "正在测速标准服务器...\n"

        monkeypatch.setattr(srv.subprocess, "run", lambda *a, **k: Proc())
        result = srv._run_cli(["quote", "SZ 000001"])
        # float32 noise from the TDX protocol is rounded for context economy
        assert result[0]["close"] == 11.89

    def test_nonzero_exit_raises_tool_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Proc:
            returncode = 2
            stdout = ""
            stderr = "连接超时\nplease retry\n"

        monkeypatch.setattr(srv.subprocess, "run", lambda *a, **k: Proc())
        with pytest.raises(ToolError, match="退出码 2"):
            srv._run_cli(["quote", "SZ 000001"])

    def test_invalid_json_raises_tool_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Proc:
            returncode = 0
            stdout = "not json"
            stderr = ""

        monkeypatch.setattr(srv.subprocess, "run", lambda *a, **k: Proc())
        with pytest.raises(ToolError, match="不是 JSON"):
            srv._run_cli(["market-stat"])

    def test_uses_same_interpreter_module_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The CLI must run via ``sys.executable -m easy_tdx`` (venv-portable, no PATH)."""
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], **kwargs: Any) -> Any:
            captured["argv"] = argv

            class Proc:
                returncode = 0
                stdout = "[]"
                stderr = ""

            return Proc()

        monkeypatch.setattr(srv.subprocess, "run", fake_run)
        srv._run_cli(["market-stat"])
        assert captured["argv"][:3] == [srv.sys.executable, "-m", "easy_tdx"]


@pytest.mark.asyncio
async def test_tools_registered() -> None:
    """Regression: expected easytdx tool surface stays exposed over MCP."""
    from fastmcp import Client

    expected = {
        "ping", "quote", "kline", "quote_list", "tick", "transaction",
        "board_ranking", "board_members", "belong_board", "market_stat",
        "unusual", "capital_flow", "indicator", "chanlun", "symbol_info",
        "finance_info", "announcement", "f10",
    }
    async with Client(srv.mcp) as client:
        tools = {tool.name for tool in await client.list_tools()}
    assert expected <= tools

    async with Client(srv.mcp) as client:
        quote_tool = next(t for t in await client.list_tools() if t.name == "quote")
    ann = quote_tool.annotations
    read_only = getattr(ann, "read_only_hint", None) if ann is not None else None
    if read_only is None and ann is not None:  # fastmcp 3.x field name
        read_only = getattr(ann, "readOnlyHint", None)
    assert read_only
