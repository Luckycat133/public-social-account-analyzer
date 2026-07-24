"""CASE-004：ISO 时间转换。

验证 normalize.parse_time 把多种时间格式统一为带时区的 datetime：
- 无时区信息 → 标注 +08:00（中国平台默认时区，见 data-schema.md §1）
- 带时区 / Z → 保留原偏移
- 不可解析 → 返回 None（即 null，禁止臆造）
"""
from datetime import datetime, timezone, timedelta

import normalize


def test_naive_iso_gets_plus08():
    dt = normalize.parse_time("2026-07-23T09:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone(timedelta(hours=8)).utcoffset(None)
    assert dt.isoformat().endswith("+08:00")


def test_iso_with_explicit_offset_kept():
    dt = normalize.parse_time("2026-07-23T09:00:00+00:00")
    assert dt is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)
    assert dt.isoformat().endswith("+00:00")


def test_iso_with_z_suffix_normalized():
    dt = normalize.parse_time("2026-07-23T09:00:00Z")
    assert dt is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_yyyymmdd_hhmmss_format():
    dt = normalize.parse_time("2026-07-23 09:00:00")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 7 and dt.day == 23
    assert dt.hour == 9 and dt.minute == 0 and dt.second == 0
    assert dt.isoformat().endswith("+08:00")


def test_yyyymmdd_only_format():
    dt = normalize.parse_time("2026-07-23")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2026, 7, 23)
    # 无时分秒时按平台默认 +08:00 标注
    assert dt.isoformat().endswith("+08:00")


def test_chinese_date_format():
    dt = normalize.parse_time("2026年7月23日")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2026, 7, 23)
    assert dt.isoformat().endswith("+08:00")


def test_md_date_uses_current_year():
    dt = normalize.parse_time("7月23日")
    assert dt is not None
    # 取当前年，时分秒为 0，时区 +08:00
    assert (dt.month, dt.day) == (7, 23)
    assert dt.year == datetime.now().year
    assert dt.isoformat().endswith("+08:00")


def test_unparseable_returns_none():
    # 多种不可解析输入都必须返回 None（null），绝不臆造时间
    assert normalize.parse_time("not-a-date") is None
    assert normalize.parse_time("") is None
    assert normalize.parse_time(None) is None
    assert normalize.parse_time("刚刚") is None


def test_unix_timestamp_converted():
    # Unix 秒级时间戳 → +08:00 datetime
    dt = normalize.parse_time(1784602500)
    assert dt is not None
    assert dt.isoformat().endswith("+08:00")
