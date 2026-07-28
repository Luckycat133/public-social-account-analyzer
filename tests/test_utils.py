"""Behavioral contracts for collector utility helpers."""

from datetime import datetime, timedelta, timezone

import pytest

from collectors import _constants
from collectors._utils import now_iso, parse_int, ts_to_iso


def test_beijing_timezone_is_fixed_utc_plus_eight():
    assert getattr(_constants, "BEIJING_TZ", None) == timezone(timedelta(hours=8))


def test_now_iso_uses_beijing_timezone():
    parsed = datetime.fromisoformat(now_iso())

    assert parsed.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (False, None),
        (12, 12),
        (-3, -3),
        (12.9, 12),
        ("1.2万", 12_000),
        ("3.4亿", 340_000_000),
        ("1,234+", 1_234),
        ("", None),
        ("not-a-number", None),
    ],
)
def test_parse_int_supported_values(value, expected):
    assert parse_int(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_parse_int_rejects_nonfinite_numbers(value):
    assert parse_int(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1_700_000_000, "2023-11-15T06:13:20+08:00"),
        (1_700_000_000_000, "2023-11-15T06:13:20+08:00"),
        ("1700000000", "2023-11-15T06:13:20+08:00"),
        (None, None),
        (0, None),
        (True, None),
        ("invalid", None),
    ],
)
def test_ts_to_iso_supported_values(value, expected):
    assert ts_to_iso(value) == expected
