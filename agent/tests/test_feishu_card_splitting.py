"""Unit tests for Feishu card payload splitting (0.1.11).

Feishu rejects interactive messages whose serialized JSON exceeds ~30 KB.
Long scheduled-research results must arrive as several cards instead of
being dropped at the API level or truncated upstream.
"""

from __future__ import annotations

import json

from src.channels.bus.queue import MessageBus
from src.channels.feishu import FeishuChannel


def _channel() -> FeishuChannel:
    return FeishuChannel({"enabled": False}, MessageBus())


def _flatten_markdown(groups: list[list[dict]]) -> str:
    parts = []
    for group in groups:
        for element in group:
            if element.get("tag") == "markdown":
                parts.append(element.get("content", ""))
    return "\n".join(parts)


# --- _split_card_elements -------------------------------------------------------


def test_short_content_stays_single_card() -> None:
    elements = _channel()._build_card_elements("一小段普通结论")
    groups = _channel()._split_card_elements(elements)
    assert len(groups) == 1
    assert FeishuChannel._card_payload_size(groups[0]) <= FeishuChannel._CARD_JSON_MAX_BYTES


def test_oversized_content_splits_into_cards_within_limit() -> None:
    content = "盘前分析结论段落，包含足够多的中文字符以撑大体积。" * 1200
    groups = _channel()._split_card_elements(_channel()._build_card_elements(content))
    assert len(groups) > 1
    for group in groups:
        assert FeishuChannel._card_payload_size(group) <= FeishuChannel._CARD_JSON_MAX_BYTES
    # No content may be lost across the split.
    flattened = _flatten_markdown(groups)
    assert flattened.startswith("盘前分析结论段落")
    assert len(flattened) >= len(content) * 0.99


def test_oversized_content_keeps_tail_marker() -> None:
    content = "指标数据行。\n" * 4000 + "结尾结论标记END"
    groups = _channel()._split_card_elements(_channel()._build_card_elements(content))
    assert len(groups) > 1
    for group in groups:
        assert FeishuChannel._card_payload_size(group) <= FeishuChannel._CARD_JSON_MAX_BYTES
    assert groups[-1][-1].get("content", "").endswith("结尾结论标记END")


def test_multiple_tables_still_one_table_per_card() -> None:
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    content = f"{table}\n中间文字\n\n{table}\n尾部文字\n\n{table}"
    groups = _channel()._split_card_elements(_channel()._build_card_elements(content))
    assert len(groups) == 3
    for group in groups:
        assert sum(1 for el in group if el.get("tag") == "table") == 1


def test_oversized_table_splits_by_rows_within_limit() -> None:
    rows = "\n".join(f"| 指标{i} | 数值{i} | 备注{i} |" for i in range(3000))
    table = f"| 指标 | 数值 | 备注 |\n| --- | --- | --- |\n{rows}"
    groups = _channel()._split_card_elements(_channel()._build_card_elements(table))
    assert len(groups) > 1
    total_rows = 0
    for group in groups:
        assert FeishuChannel._card_payload_size(group) <= FeishuChannel._CARD_JSON_MAX_BYTES
        tables = [el for el in group if el.get("tag") == "table"]
        assert len(tables) == 1
        assert tables[0]["columns"][0]["display_name"] == "指标"
        total_rows += len(tables[0]["rows"])
    assert total_rows == 3000


# --- _split_text_by_bytes -------------------------------------------------------


def test_split_text_by_bytes_prefers_line_boundaries() -> None:
    text = "\n".join("指标行" * 40 for _ in range(100))
    max_bytes = 4096
    pieces = FeishuChannel._split_text_by_bytes(text, max_bytes)
    assert len(pieces) > 1
    for piece in pieces:
        assert FeishuChannel._json_escaped_size(piece) + 2 <= max_bytes
    assert "\n".join(pieces) == text


def test_split_text_by_bytes_hard_cuts_oversized_line() -> None:
    text = "长" * 5000
    max_bytes = 3000
    pieces = FeishuChannel._split_text_by_bytes(text, max_bytes)
    assert len(pieces) > 1
    assert "".join(pieces) == text
    for piece in pieces:
        assert FeishuChannel._json_escaped_size(piece) + 2 <= max_bytes


# --- regression: send-path element building stays JSON-serializable -------------


def test_split_groups_serialize_to_valid_card_json() -> None:
    content = "结论文字。" * 2000 + "\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    for group in _channel()._split_card_elements(_channel()._build_card_elements(content)):
        card = {"config": {"wide_screen_mode": True}, "elements": group}
        assert json.loads(json.dumps(card, ensure_ascii=False))["elements"] == group
