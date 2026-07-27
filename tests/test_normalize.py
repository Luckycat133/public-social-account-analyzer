"""CASE-001（null 与 0）、CASE-002（同平台去重）、CASE-003（跨平台保留）、CASE-004（ISO 时间）、CASE-005（中文数字单位）、CASE-011（字段覆盖率）。

全部离线、确定性，直接调用 normalize 纯函数：
- parse_metric：页面显示 0 → 0（visible）；页面未显示 → None（hidden）。
- parse_metric：中文单位 万/亿 → 整数换算。
- parse_time：多种时间格式统一为带时区的 datetime。
- dedup_posts：按 (platform, post_id) 唯一键去重。
- compute_metric_coverage：各指标在有效样本中非 null 比例。
"""
import csv
import copy
import io
import json
from datetime import datetime, timezone, timedelta

import pytest

import analyze
import normalize


# ---------------------------------------------------------------------------
# CASE-001：null 与 0 必须区分
# ---------------------------------------------------------------------------
def test_likes_shown_zero_is_zero_not_null():
    value, status = normalize.parse_metric("0")
    assert value == 0
    assert status == "visible"  # 页面明确显示 0 → 真实零值，非 hidden


def test_views_missing_is_null():
    value, status = normalize.parse_metric(None)
    assert value is None
    assert status == "hidden"  # 未显示该字段 → null，绝不写 0


def test_likes_zero_int_passthrough():
    value, status = normalize.parse_metric(0)
    assert value == 0
    assert status == "visible"


# ---------------------------------------------------------------------------
# CASE-005：中文数字单位转换
# ---------------------------------------------------------------------------
def test_chinese_wan_1_2():
    value, _ = normalize.parse_metric("1.2万")
    assert value == 12000


def test_chinese_wan_10():
    value, _ = normalize.parse_metric("10万")
    assert value == 100000


def test_chinese_yi_3_4():
    value, _ = normalize.parse_metric("3.4亿")
    assert value == 340000000


def test_chinese_wan_with_noise():
    # 含「播放」「赞」等噪声字符时仍正确换算
    value, status = normalize.parse_metric("12.3万播放")
    assert value == 123000
    assert status == "visible"


# ---------------------------------------------------------------------------
# CASE-011：字段覆盖率（各指标非 null 比例）
# ---------------------------------------------------------------------------
def _row_with_visibility(overrides):
    vis = {f: "hidden" for f in normalize.METRIC_FIELDS}
    vis.update(overrides)
    return {"_visibility": vis}


def test_field_coverage_present_rate():
    rows = [
        _row_with_visibility({"views": "visible", "likes": "visible"}),
        _row_with_visibility({"views": "visible"}),
        _row_with_visibility({}),  # 全 hidden
    ]
    cov = normalize.compute_metric_coverage(rows)
    assert cov["views"]["present"] == 2
    assert cov["views"]["missing"] == 1
    assert cov["views"]["missing_rate"] == round(1 / 3, 4)
    assert cov["likes"]["present"] == 1
    assert cov["likes"]["missing"] == 2


def test_field_coverage_all_hidden():
    rows = [_row_with_visibility({}), _row_with_visibility({})]
    cov = normalize.compute_metric_coverage(rows)
    for f in normalize.METRIC_FIELDS:
        assert cov[f]["present"] == 0
        assert cov[f]["missing_rate"] == 1.0


def test_field_coverage_via_normalize_pipeline():
    # 端到端走 normalize_post：likes=0 算 visible，views 缺失算 hidden
    raw_posts = [
        {"platform": "bilibili", "post_id": "1", "views": 100, "likes": 0},
        {"platform": "bilibili", "post_id": "2"},  # views/likes 均未给
    ]
    rows = [normalize.normalize_post(p)[0] for p in raw_posts]
    cov = normalize.compute_metric_coverage(rows)
    # views: 1 条 visible，1 条 hidden
    assert cov["views"]["present"] == 1 and cov["views"]["missing"] == 1
    # likes: 0 是真实零值，仍计入 present
    assert cov["likes"]["present"] == 1 and cov["likes"]["missing"] == 1


def test_normalized_csv_uses_canonical_json_without_losing_platform_fields():
    raw = {
        "platform": "bilibili",
        "post_id": "BV1contract",
        "post_url": "https://www.bilibili.com/video/BV1contract",
        "published_at": "2026-07-01T09:30:00+08:00",
        "content_type": "video",
        "title": "完整字段保真",
        "text": "正文",
        "duration_seconds": 42,
        "hashtags": ["标签|一", "标签,二"],
        "is_pinned": None,
        "is_repost": False,
        "is_promoted": False,
        "collection_status": "SUCCESS",
        "collected_at": "2026-07-02T10:00:00+08:00",
        "source_url": "https://www.bilibili.com/video/BV1contract",
        "views": 123,
        "likes": None,
        "comments": 4,
        "favorites": 5,
        "shares": 6,
        "coins": 7,
        "danmaku": 8,
        "field_visibility": {
            "title": "partial",
            "duration_seconds": "visible",
            "views": "partial",
            "custom_platform_field": "hidden",
        },
        "platform_metrics": {
            "partition": "知识",
            "dynamic": {"is_dynamic": True},
            "detail_status": "SUCCESS",
            "trace": [None, True, "x"],
        },
    }
    untouched = copy.deepcopy(raw)

    result = normalize.normalize_in_memory(
        None, (json.dumps(raw, ensure_ascii=False) + "\n").encode("utf-8")
    )
    memory_row = result.rows[0]
    csv_row = next(csv.DictReader(io.StringIO(result.csv_text)))

    assert memory_row["hashtags"] == ["标签|一", "标签,二"]
    assert memory_row["platform_metrics"] == raw["platform_metrics"]
    assert memory_row["field_visibility"]["views"] == "partial"
    assert memory_row["field_visibility"]["likes"] == "hidden"
    assert memory_row["field_visibility"]["title"] == "partial"
    assert memory_row["field_visibility"]["duration_seconds"] == "visible"
    assert memory_row["field_visibility"]["custom_platform_field"] == "hidden"
    assert raw == untouched
    assert csv_row["hashtags"] == '["标签|一","标签,二"]'
    assert csv_row["platform_metrics"] == (
        '{"detail_status":"SUCCESS","dynamic":{"is_dynamic":true},'
        '"partition":"知识","trace":[null,true,"x"]}'
    )
    assert csv_row["field_visibility"] == json.dumps(
        json.loads(csv_row["field_visibility"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert csv_row["is_pinned"] == ""
    assert csv_row["is_repost"] == "false"
    assert csv_row["is_promoted"] == "false"

    for row in (memory_row, csv_row):
        post = analyze.build_posts([row])[0]
        assert post["published_at"].isoformat() == "2026-07-01T09:30:00+08:00"
        assert post["content_type"] == "video"
        assert post["title"] == "完整字段保真"
        assert post["text"] == "正文"
        assert post["duration_seconds"] == 42
        assert post["hashtags"] == ["标签|一", "标签,二"]
        assert post["collection_status"] == "SUCCESS"
        assert post["collected_at"] == "2026-07-02T10:00:00+08:00"
        assert post["source_url"] == raw["source_url"]
        assert {field: post[field] for field in normalize.METRIC_FIELDS} == {
            "views": 123,
            "likes": None,
            "comments": 4,
            "favorites": 5,
            "shares": 6,
            "coins": 7,
            "danmaku": 8,
        }
        assert post["platform_metrics"] == raw["platform_metrics"]
        assert post["field_visibility"]["views"] == "partial"
        assert post["field_visibility"]["likes"] == "hidden"
        assert post["field_visibility"]["title"] == "partial"
        assert post["field_visibility"]["duration_seconds"] == "visible"
        assert post["field_visibility"]["custom_platform_field"] == "hidden"
        assert post["is_pinned"] is None
        assert post["is_repost"] is False
        assert post["is_promoted"] is False

    analysis_result = analyze.analyze_in_memory(
        {"platform": "bilibili", "followers": 100},
        [memory_row],
        {"task_id": "round-trip", "platform": "bilibili"},
    )
    analysis_post = analysis_result.analysis["posts"][0]
    assert analysis_post["hashtags"] == ["标签|一", "标签,二"]
    assert analysis_post["platform_metrics"] == raw["platform_metrics"]
    assert analysis_post["field_visibility"] == memory_row["field_visibility"]
    assert analysis_post["collected_at"] == "2026-07-02T10:00:00+08:00"
    assert analysis_post["source_url"] == raw["source_url"]
    assert analysis_post["is_pinned"] is None
    assert analysis_post["is_repost"] is False
    assert analysis_post["is_promoted"] is False


def test_analyzer_preserves_true_flag_and_excludes_it_from_default_sample():
    post = analyze.build_posts(
        [
            {
                "platform": "douyin",
                "post_id": "promoted",
                "is_promoted": True,
                "collection_status": "SUCCESS",
            }
        ]
    )[0]

    _, valid, flagged, _, _ = analyze.split_samples([post])

    assert post["is_promoted"] is True
    assert valid == []
    assert [item["post_id"] for item in flagged] == ["promoted"]


@pytest.mark.parametrize("legacy_hashtags", ["甲|乙", "甲,乙", "甲;乙"])
def test_analyzer_backward_reads_legacy_hashtags_and_missing_json_columns(
    legacy_hashtags,
):
    post = analyze.build_posts(
        [
            {
                "platform": "douyin",
                "post_id": "1",
                "hashtags": legacy_hashtags,
                "is_pinned": "false",
                "is_repost": "true",
                "is_promoted": "",
                "collection_status": "SUCCESS",
            }
        ]
    )[0]

    assert post["hashtags"] == ["甲", "乙"]
    assert post["platform_metrics"] == {}
    assert post["field_visibility"] == {}
    assert post["is_pinned"] is False
    assert post["is_repost"] is True
    assert post["is_promoted"] is None
    assert post["local_record_key"] is False


@pytest.mark.parametrize("raw", [None, "", "unknown", object()])
def test_unknown_public_flags_normalize_to_null(raw):
    assert normalize.to_bool_flag(raw) is None


@pytest.mark.parametrize(
    ("raw_status", "source"),
    [(None, "inferred_missing"), ("NOT_A_STATUS", "inferred_invalid")],
)
def test_missing_or_invalid_collection_status_is_partial_with_warning(
    raw_status, source
):
    raw = {
        "platform": "douyin",
        "post_id": "status-contract",
        "post_url": "https://www.douyin.com/video/1234567890",
        "views": 10,
    }
    if raw_status is not None:
        raw["collection_status"] = raw_status

    result = normalize.normalize_in_memory(
        None, (json.dumps(raw) + "\n").encode("utf-8")
    )

    assert result.rows[0]["collection_status"] == "PARTIAL"
    assert result.rows[0]["collection_status_source"] == source
    assert result.coverage["warning_count"] == 1
    warning = result.coverage["warnings"][0]
    assert warning["warning_code"] == "COLLECTION_STATUS_INFERRED"
    assert warning["field"] == "collection_status"
    assert warning["inference_source"] == source


def test_collector_inferred_status_survives_normalization_with_warning():
    from collectors.bilibili import BilibiliCollector

    collected = BilibiliCollector().normalize_post(
        {"platform": "douyin", "post_id": "source-status"}
    )

    result = normalize.normalize_in_memory(
        None, (json.dumps(collected) + "\n").encode("utf-8")
    )

    assert result.rows[0]["collection_status"] == "PARTIAL"
    assert result.rows[0]["collection_status_source"] == "inferred_missing"
    assert result.coverage["warning_count"] == 1
    assert result.coverage["warnings"][0]["inference_source"] == (
        "inferred_missing"
    )


def test_inferred_status_source_cannot_be_attached_to_declared_success():
    raw = {
        "platform": "douyin",
        "post_id": "status-source-mismatch",
        "collection_status": "SUCCESS",
        "collection_status_source": "inferred_missing",
    }

    result = normalize.normalize_in_memory(
        None, (json.dumps(raw) + "\n").encode("utf-8")
    )

    assert result.rows[0]["collection_status"] == "SUCCESS"
    assert result.rows[0]["collection_status_source"] == "declared"
    assert result.coverage["warning_count"] == 0


@pytest.mark.parametrize(
    ("raw_status", "source"),
    [(None, "inferred_missing"), ("NOT_A_STATUS", "inferred_invalid")],
)
def test_analyzer_backward_reads_untrusted_legacy_status_as_partial(
    raw_status, source
):
    row = {
        "platform": "douyin",
        "post_id": "legacy-status",
        "collection_status": raw_status,
    }

    post = analyze.build_posts([row])[0]
    _, valid, _, _, _ = analyze.split_samples([post])

    assert post["collection_status"] == "PARTIAL"
    assert post["collection_status_source"] == source
    assert [item["post_id"] for item in valid] == ["legacy-status"]


def test_invalid_field_visibility_is_replaced_by_derived_value_with_warning():
    raw = {
        "platform": "douyin",
        "post_id": "visibility-contract",
        "post_url": "https://www.douyin.com/video/1234567890",
        "collection_status": "SUCCESS",
        "views": 10,
        "field_visibility": {
            "views": "invented-state",
            "title": "visible",
        },
    }

    result = normalize.normalize_in_memory(
        None, (json.dumps(raw) + "\n").encode("utf-8")
    )

    assert result.rows[0]["field_visibility"]["views"] == "visible"
    assert result.rows[0]["field_visibility"]["title"] == "visible"
    assert result.coverage["warning_count"] == 1
    warning = result.coverage["warnings"][0]
    assert warning["warning_code"] == "FIELD_VISIBILITY_INVALID"
    assert warning["field"] == "field_visibility.views"


# ---------------------------------------------------------------------------
# CASE-002：同平台同 post_id 去重与 CASE-003：跨平台相同 post_id 保留
# ---------------------------------------------------------------------------
def test_same_platform_same_post_id_dedup():
    raw = [
        {"platform": "bilibili", "post_id": "BV123", "title": "first"},
        {"platform": "bilibili", "post_id": "BV123", "title": "dup"},
        {"platform": "bilibili", "post_id": "BV456"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 2
    assert dup == 1
    assert kept[0]["title"] == "first"
    ids = [(p["platform"], p["post_id"]) for p in kept]
    assert ids == [("bilibili", "BV123"), ("bilibili", "BV456")]


def test_cross_platform_same_post_id_kept():
    raw = [
        {"platform": "bilibili", "post_id": "123"},
        {"platform": "douyin", "post_id": "123"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 2
    assert dup == 0
    platforms = sorted(p["platform"] for p in kept)
    assert platforms == ["bilibili", "douyin"]


def test_no_duplicate_when_unique():
    raw = [
        {"platform": "bilibili", "post_id": "BV1"},
        {"platform": "bilibili", "post_id": "BV2"},
        {"platform": "douyin", "post_id": "DV1"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 3
    assert dup == 0


def test_missing_post_id_not_collapsed():
    raw = [
        {"platform": "bilibili"},
        {"platform": "bilibili"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 2
    assert dup == 0


# ---------------------------------------------------------------------------
# CASE-004：ISO 时间转换
# ---------------------------------------------------------------------------
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
    assert dt.isoformat().endswith("+08:00")


def test_chinese_date_format():
    dt = normalize.parse_time("2026年7月23日")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2026, 7, 23)
    assert dt.isoformat().endswith("+08:00")


def test_md_date_uses_current_year():
    dt = normalize.parse_time("7月23日")
    assert dt is not None
    assert (dt.month, dt.day) == (7, 23)
    assert dt.year == datetime.now().year
    assert dt.isoformat().endswith("+08:00")


def test_unparseable_returns_none():
    assert normalize.parse_time("not-a-date") is None
    assert normalize.parse_time("") is None
    assert normalize.parse_time(None) is None
    assert normalize.parse_time("刚刚") is None


def test_unix_timestamp_converted():
    dt = normalize.parse_time(1784602500)
    assert dt is not None
    assert dt.isoformat().endswith("+08:00")


def test_reversed_collection_range_fails_before_workspace_creation(
    monkeypatch, tmp_path
):
    import collect

    class DateAdapter:
        platform = "douyin"

        def supports(self, url):
            return True

    out = tmp_path / "must-not-exist"
    monkeypatch.setattr(collect, "_load_adapters", lambda: [DateAdapter()])

    rc = collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        date_from="2026-07-25",
        date_to="2026-07-24",
    )

    assert rc == 2
    assert not out.exists()
