"""Direct regression tests for the canonical CSV cell contract."""

from __future__ import annotations

import math

import pytest

import csv_contract
from csv_contract import (
    BOOLEAN_FIELDS,
    MAX_LITERAL_NODES,
    MAX_STRUCTURED_CELL_CHARS,
    NUMERIC_FIELDS,
    STRUCTURED_FIELDS,
    _safe_legacy_literal,
    canonical_json,
    deserialize_csv_cell,
    parse_hashtag_cell,
    parse_structured_object_cell,
    serialize_csv_cell,
)


def test_field_groups_cover_normalized_csv_types():
    assert {"platform_metrics", "field_visibility"} <= STRUCTURED_FIELDS
    assert {"is_pinned", "is_repost", "is_promoted"} <= BOOLEAN_FIELDS
    assert {"duration_seconds", "views", "likes", "comments"} <= NUMERIC_FIELDS


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("views", None, ""),
        ("is_pinned", True, "true"),
        ("is_pinned", False, "false"),
        ("hashtags", ["游戏", "攻略"], '["游戏","攻略"]'),
        ("platform_metrics", {"b": 2, "a": 1}, '{"a":1,"b":2}'),
        ("duration_seconds", 0.4, 0),
        ("duration_seconds", 0.6, 1),
        ("duration_seconds", math.nan, ""),
        ("duration_seconds", math.inf, ""),
    ],
)
def test_serialize_csv_cell_preserves_canonical_types(column, value, expected):
    assert serialize_csv_cell(column, value) == expected


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("views", None),
        ("is_pinned", True),
        ("is_repost", False),
        ("hashtags", ["游戏", "攻略"]),
        ("field_visibility", {"views": "visible"}),
        ("duration_seconds", 13),
    ],
)
def test_csv_cell_round_trip_is_type_stable(column, value):
    serialized = serialize_csv_cell(column, value)

    assert deserialize_csv_cell(column, serialized) == value


def test_deserialize_numeric_json_string_preserves_integer_type():
    assert deserialize_csv_cell("views", '"123"') == 123
    assert deserialize_csv_cell("views", '"-7"') == -7


def test_deserialize_rejects_nonfinite_and_invalid_typed_cells():
    warnings = []

    assert deserialize_csv_cell("views", "NaN", warning_sink=warnings.append) is None
    assert deserialize_csv_cell("is_pinned", "yes", warning_sink=warnings.append) is None
    assert len(warnings) == 2


def test_structured_parsers_accept_canonical_and_bounded_legacy_cells():
    assert parse_hashtag_cell('["游戏",2]') == ["游戏", "2"]
    assert parse_hashtag_cell("('游戏', '攻略')") == ["游戏", "攻略"]
    assert parse_structured_object_cell('{"b":2,"a":1}') == {"a": 1, "b": 2}
    assert parse_structured_object_cell("{'visible': True}") == {"visible": True}
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_safe_legacy_literal_rejects_executable_syntax():
    with pytest.raises(ValueError, match="unsupported legacy literal syntax"):
        _safe_legacy_literal("__import__('os')")


def test_safe_legacy_literal_size_limit_is_inclusive():
    at_limit = "0" + " " * (MAX_STRUCTURED_CELL_CHARS - 1)

    assert _safe_legacy_literal(at_limit) == 0
    with pytest.raises(ValueError, match="size limit"):
        _safe_legacy_literal(at_limit + " ")


def test_safe_legacy_literal_node_limit_is_inclusive():
    at_limit = "[" + ",".join("0" for _ in range(MAX_LITERAL_NODES - 3)) + "]"
    over_limit = at_limit[:-1] + ",0]"

    assert len(_safe_legacy_literal(at_limit)) == MAX_LITERAL_NODES - 3
    with pytest.raises(ValueError, match="complexity limits"):
        _safe_legacy_literal(over_limit)


def test_safe_legacy_literal_depth_limit_is_inclusive(monkeypatch):
    monkeypatch.setattr(csv_contract, "MAX_LITERAL_DEPTH", 3)

    assert _safe_legacy_literal("[[0]]") == [[0]]
    with pytest.raises(ValueError, match="complexity limits"):
        _safe_legacy_literal("[[[0]]]")
