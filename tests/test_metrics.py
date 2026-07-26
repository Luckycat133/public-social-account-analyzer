"""CASE-008（中位数）、CASE-009（分位数 p25/p75）、CASE-010（分母为零互动率 null）、
以及相对中位数表现在 median 为 0/null 时跳过（analysis-rules.md §4）。

离线、确定性，直接调用 analyze 纯函数。
"""
import json
from datetime import datetime

import analyze
import normalize
import pytest


# ---------------------------------------------------------------------------
# CASE-008：中位数计算
# ---------------------------------------------------------------------------
def test_median_even_count():
    # 偶数个：线性插值，numpy 默认行为
    assert analyze.percentile([1, 2, 3, 4], 0.5) == 2.5


def test_median_odd_count():
    assert analyze.percentile([1, 2, 3, 4, 5], 0.5) == 3.0


def test_median_single_value():
    # 单条时中位数即该值本身
    assert analyze.percentile([7], 0.5) == 7.0


def test_compute_medians_over_posts():
    posts = [
        {"views": 100, "likes": 10, "comments": 1, "favorites": 1, "shares": 1, "coins": 1, "danmaku": 1},
        {"views": 200, "likes": 20, "comments": 2, "favorites": 2, "shares": 2, "coins": 2, "danmaku": 2},
        {"views": 300, "likes": 30, "comments": 3, "favorites": 3, "shares": 3, "coins": 3, "danmaku": 3},
    ]
    medians = analyze.compute_medians(posts)
    assert medians["views"] == 200.0
    assert medians["likes"] == 20.0


def _high_low_post(index: int, views) -> dict:
    return {
        "platform": "douyin",
        "post_id": str(index),
        "post_url": f"https://www.douyin.com/video/{index}",
        "title": f"作品 {index}",
        "collection_status": "SUCCESS",
        "views": views,
        "likes": None,
        "comments": None,
        "favorites": None,
        "shares": None,
        "coins": None,
        "danmaku": None,
    }


@pytest.mark.parametrize(
    ("measured_count", "expected_group_size", "expected_median"),
    [
        (15, 3, 8.0),
        (16, 4, 8.5),
        (19, 4, 10.0),
        (20, 4, 10.5),
    ],
)
def test_high_low_uses_ceil_twenty_percent_of_measured_posts(
    measured_count, expected_group_size, expected_median
):
    posts = [
        _high_low_post(index, index + 1)
        for index in range(measured_count)
    ]

    result = analyze.compute_high_low(posts, "views")

    assert result is not None
    assert result["measured_count"] == measured_count
    assert result["main_metric_median"] == expected_median
    assert result["group_size"] == expected_group_size
    assert len(result["high"]) == expected_group_size
    assert len(result["low"]) == expected_group_size


def test_high_low_insufficient_reason_uses_measured_not_valid_count():
    rows = [
        _high_low_post(index, index + 1 if index < 14 else None)
        for index in range(20)
    ]

    result = analyze.analyze_in_memory(
        {"platform": "douyin", "followers": 100},
        rows,
        {"platform": "douyin", "analysis_goal": "播放表现"},
    ).analysis

    assert result["sample_boundary"]["valid"] == 20
    assert result["performance_meta"]["status"] == "INSUFFICIENT_SAMPLE"
    assert result["performance_meta"]["measured_count"] == 14
    assert result["performance_meta"]["main_metric_median"] == 7.5
    assert "主指标实测样本 14 < 15" in result["performance_meta"]["reason"]


def test_high_low_counts_zero_as_measured_and_excludes_null_values():
    posts = [
        _high_low_post(index, 0 if index < 15 else None)
        for index in range(20)
    ]

    result = analyze.compute_high_low(posts, "views")

    assert result is not None
    assert result["measured_count"] == 15
    assert result["main_metric_median"] == 0.0
    assert result["group_size"] == 3
    selected = result["high"] + result["low"]
    assert all(int(item["post_id"]) < 15 for item in selected)
    assert all(item["relative_to_main_median"] is None for item in selected)
    assert [item["rank"] for item in result["high"]] == [1, 2, 3]
    assert [item["rank"] for item in result["low"]] == [13, 14, 15]


def test_high_low_ties_use_source_rank_then_post_id_independent_of_input_order():
    posts = []
    for source_rank in range(1, 9):
        for suffix in ("b", "a"):
            post = _high_low_post(len(posts), 100)
            post["post_id"] = f"rank-{source_rank}-{suffix}"
            post["source_rank"] = source_rank
            posts.append(post)
    for post_id, source_rank in (
        ("invalid-d", None),
        ("invalid-c", 0),
        ("invalid-b", False),
        ("invalid-a", "1"),
    ):
        post = _high_low_post(len(posts), 100)
        post["post_id"] = post_id
        post["source_rank"] = source_rank
        posts.append(post)

    forward = analyze.compute_high_low(posts, "views")
    reversed_input = analyze.compute_high_low(list(reversed(posts)), "views")

    assert forward == reversed_input
    assert forward is not None
    assert [item["post_id"] for item in forward["high"]] == [
        "rank-1-a",
        "rank-1-b",
        "rank-2-a",
        "rank-2-b",
    ]
    assert [item["post_id"] for item in forward["low"]] == [
        "invalid-a",
        "invalid-b",
        "invalid-c",
        "invalid-d",
    ]
    assert [item["rank"] for item in forward["high"]] == [1, 2, 3, 4]
    assert [item["rank"] for item in forward["low"]] == [17, 18, 19, 20]
    high_ids = {item["post_id"] for item in forward["high"]}
    low_ids = {item["post_id"] for item in forward["low"]}
    assert high_ids.isdisjoint(low_ids)


def test_high_low_ties_use_platform_after_same_post_id():
    douyin = _high_low_post(0, 100)
    douyin.update(
        {
            "platform": "douyin",
            "post_id": "shared-id",
            "post_url": "https://www.douyin.com/video/100",
            "source_rank": 1,
        }
    )
    weibo = _high_low_post(1, 100)
    weibo.update(
        {
            "platform": "weibo",
            "post_id": "shared-id",
            "post_url": "https://weibo.com/123/shared-id",
            "source_rank": 1,
        }
    )
    posts = [weibo, douyin]
    for index in range(2, 15):
        post = _high_low_post(index, 100 - index)
        post["source_rank"] = index + 1
        posts.append(post)

    forward = analyze.compute_high_low(posts, "views")
    reversed_input = analyze.compute_high_low(list(reversed(posts)), "views")

    assert forward == reversed_input
    assert forward is not None
    assert [item["platform"] for item in forward["high"][:2]] == [
        "douyin",
        "weibo",
    ]


def test_high_low_item_has_exact_schema_provenance_and_relative_to_median():
    published_at = datetime.fromisoformat("2026-07-01T08:30:00+08:00")
    posts = []
    for index in range(15):
        post = _high_low_post(index, 100 + index)
        post.update(
            {
                "platform": "douyin",
                "source_url": f"https://www.douyin.com/video/{index}",
                "published_at": published_at,
                "published_at_precision": "datetime",
                "collection_status_source": "declared",
                "collected_at": "2026-07-02T09:00:00+08:00",
                "collection_source": "douyin_web",
                "platform_post_id_known": True,
                "local_record_key": False,
                "item_url_known": True,
                "source_rank": index + 1,
                "duration_seconds": 30 + index,
                "hashtags": ["topic", f"tag-{index}"],
                "content_type": "video",
                "is_pinned": False,
                "is_repost": False,
                "is_promoted": False,
                "platform_metrics": {"raw_views": 100 + index},
                "field_visibility": {"views": "visible"},
                "likes": 10 + index,
                "comments": 2,
                "favorites": 3,
                "shares": 4,
                "coins": None,
                "danmaku": None,
            }
        )
        posts.append(post)

    result = analyze.compute_high_low(posts, "views")

    assert result is not None
    item = result["high"][0]
    assert set(item) == {
        "platform",
        "post_id",
        "title",
        "post_url",
        "evidence_url",
        "source_url",
        "published_at",
        "published_at_precision",
        "collection_status",
        "collection_status_source",
        "collected_at",
        "collection_source",
        "platform_post_id_known",
        "local_record_key",
        "item_url_known",
        "source_rank",
        "metrics",
        "value",
        "rank",
        "reason",
        "relative_to_main_median",
        "duration_seconds",
        "hashtags",
        "content_type",
        "is_pinned",
        "is_repost",
        "is_promoted",
        "platform_metrics",
        "field_visibility",
        "main_metric",
    }
    assert item["platform"] == "douyin"
    assert item["post_id"] == "14"
    assert item["title"] == "作品 14"
    assert item["post_url"] == "https://www.douyin.com/video/14"
    assert item["source_url"] == "https://www.douyin.com/video/14"
    assert item["evidence_url"] == "https://www.douyin.com/video/14"
    assert item["published_at"] == published_at.isoformat()
    assert item["published_at_precision"] == "datetime"
    assert item["collection_status"] == "SUCCESS"
    assert item["collection_status_source"] == "declared"
    assert item["collected_at"] == "2026-07-02T09:00:00+08:00"
    assert item["collection_source"] == "douyin_web"
    assert item["platform_post_id_known"] is True
    assert item["local_record_key"] is False
    assert item["item_url_known"] is True
    assert item["source_rank"] == 15
    assert item["metrics"] == {
        "views": 114,
        "likes": 24,
        "comments": 2,
        "favorites": 3,
        "shares": 4,
        "coins": None,
        "danmaku": None,
    }
    assert item["value"] == 114
    assert item["rank"] == 1
    assert item["reason"] == "主指标 views = 114"
    assert item["relative_to_main_median"] == 1.0654
    assert item["duration_seconds"] == 44
    assert item["hashtags"] == ["topic", "tag-14"]
    assert item["content_type"] == "video"
    assert item["is_pinned"] is False
    assert item["is_repost"] is False
    assert item["is_promoted"] is False
    assert item["platform_metrics"] == {"raw_views": 114}
    assert item["field_visibility"] == {"views": "visible"}
    assert item["main_metric"] == "views"


def test_high_low_unknown_item_url_suppresses_post_url_but_keeps_source_anchor():
    posts = [_high_low_post(index, index + 1) for index in range(15)]
    source_anchor = "https://www.douyin.com/user/example"
    posts[-1]["item_url_known"] = False
    posts[-1]["source_url"] = source_anchor

    result = analyze.compute_high_low(posts, "views")

    assert result is not None
    item = result["high"][0]
    assert item["post_url"] is None
    assert item["source_url"] == source_anchor
    assert item["evidence_url"] == source_anchor
    assert item["item_url_known"] is False


def test_successful_performance_meta_exposes_measured_count_and_median():
    rows = [_high_low_post(index, index + 1) for index in range(15)]

    result = analyze.analyze_in_memory(
        {"platform": "douyin", "followers": 100},
        rows,
        {"platform": "douyin", "analysis_goal": "播放表现"},
    ).analysis

    assert result["performance_meta"]["status"] == "ok"
    assert result["performance_meta"]["measured_count"] == 15
    assert result["performance_meta"]["main_metric_median"] == 8.0


def test_legacy_cli_high_low_matches_in_memory(tmp_path):
    profile = {"platform": "douyin", "followers": 100}
    rows = [_high_low_post(index, index + 1) for index in range(15)]
    for row in rows:
        row["collected_at"] = "2026-07-02T09:00:00+08:00"
    expected = analyze.analyze_in_memory(
        profile,
        rows,
        {"platform": "douyin", "analysis_goal": "播放表现"},
    ).analysis
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False), encoding="utf-8"
    )
    normalize.write_csv(rows, str(tmp_path / "normalized-posts.csv"))

    exit_code = analyze.main(
        ["--input", str(tmp_path), "--analysis-goal", "播放表现"]
    )
    actual = json.loads(
        (tmp_path / "analysis.json").read_text(encoding="utf-8")
    )

    assert exit_code == 0
    assert actual["high_performance"] == expected["high_performance"]
    assert actual["low_performance"] == expected["low_performance"]
    assert actual["performance_meta"] == expected["performance_meta"]


def test_build_posts_normalizes_blank_collected_at_to_none():
    row = _high_low_post(1, 1)
    row["collected_at"] = ""

    post = analyze.build_posts([row])[0]

    assert post["collected_at"] is None


# ---------------------------------------------------------------------------
# CASE-009：分位数计算 p25 / p75
# ---------------------------------------------------------------------------
def test_percentile_p25():
    assert analyze.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9], 0.25) == 3.0


def test_percentile_p75():
    assert analyze.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9], 0.75) == 7.0


def test_percentile_ordering():
    vals = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    p25 = analyze.percentile(vals, 0.25)
    med = analyze.percentile(vals, 0.5)
    p75 = analyze.percentile(vals, 0.75)
    assert p25 <= med <= p75


# ---------------------------------------------------------------------------
# CASE-010：分母为零 → 互动率 null（不除零）
# ---------------------------------------------------------------------------
def test_view_based_rate_zero_views_is_null():
    post = {"views": 0, "likes": 5, "comments": 1, "favorites": 0, "shares": 2}
    assert analyze.view_based_rate(post) is None


def test_view_based_rate_null_views_is_null():
    post = {"views": None, "likes": 5, "comments": 1, "favorites": 0, "shares": 2}
    assert analyze.view_based_rate(post) is None


def test_view_based_rate_normal():
    post = {"views": 100, "likes": 10, "comments": 5, "favorites": 0, "shares": 5}
    # 分子 = 10+5+0+5 = 20；20/100 = 0.2
    assert analyze.view_based_rate(post) == 0.2


def test_all_unknown_engagement_components_stay_null():
    post = {
        "views": 100,
        "likes": None,
        "comments": None,
        "favorites": None,
        "shares": None,
    }
    assert analyze.engagement_numerator(post) is None
    assert analyze.view_based_rate(post) is None


def test_partially_visible_engagement_sums_only_known_components():
    post = {
        "views": 100,
        "likes": 7,
        "comments": None,
        "favorites": None,
        "shares": None,
    }
    assert analyze.engagement_numerator(post) == 7
    assert analyze.view_based_rate(post) == 0.07


# ---------------------------------------------------------------------------
# 相对中位数表现：median 为 0 / null 时该指标置 null（禁止用 0 做分母）
# ---------------------------------------------------------------------------
def _sample_posts():
    return [
        {
            "post_id": "1",
            "post_url": "u1",
            "published_at": datetime(2026, 1, 1),
            "views": 200,
            "likes": 20,
            "comments": 5,
            "favorites": 2,
            "shares": 3,
            "coins": 1,
            "danmaku": 4,
        },
        {
            "post_id": "2",
            "post_url": "u2",
            "published_at": datetime(2026, 1, 2),
            "views": 100,
            "likes": 10,
            "comments": 2,
            "favorites": 1,
            "shares": 1,
            "coins": 0,
            "danmaku": 2,
        },
    ]


def test_relative_performance_normal():
    posts = _sample_posts()
    medians = analyze.compute_medians(posts)  # views median = 150.0
    recs = analyze.build_post_records(posts, medians, followers=1000)
    # 200 / 150 = 1.3333
    assert recs[0]["relative_performance"]["views"] == 1.3333


def test_relative_performance_skips_when_median_zero():
    posts = _sample_posts()
    medians = analyze.compute_medians(posts)
    medians["views"] = 0.0  # 中位数为 0
    recs = analyze.build_post_records(posts, medians, followers=1000)
    assert recs[0]["relative_performance"]["views"] is None


def test_relative_performance_skips_when_median_null():
    posts = _sample_posts()
    medians = analyze.compute_medians(posts)
    medians["views"] = None  # 中位数缺失
    recs = analyze.build_post_records(posts, medians, followers=1000)
    assert recs[0]["relative_performance"]["views"] is None


# ---------------------------------------------------------------------------
# P0 深度互动率拆分（混合口径）：深度认可率=(投币+收藏)/播放，社群讨论率=(评论+弹幕)/播放
# ---------------------------------------------------------------------------
def test_deep_approval_rate_normal():
    # (coins + favorites) / views = (10 + 5) / 100 = 0.15
    post = {"views": 100, "coins": 10, "favorites": 5, "likes": 50}
    assert analyze.deep_approval_rate(post) == 0.15


def test_deep_approval_rate_uses_views_denominator_not_likes():
    # 混合口径：分母应为 views，而非 likes
    post = {"views": 100, "coins": 10, "favorites": 5, "likes": 1000}
    assert analyze.deep_approval_rate(post) == 0.15


def test_deep_approval_rate_zero_views_is_null():
    post = {"views": 0, "coins": 10, "favorites": 5, "likes": 50}
    assert analyze.deep_approval_rate(post) is None


def test_deep_approval_rate_null_views_is_null():
    post = {"views": None, "coins": 10, "favorites": 5, "likes": 50}
    assert analyze.deep_approval_rate(post) is None


def test_deep_approval_rate_all_unknown_components_stay_null():
    post = {"views": 100, "coins": None, "favorites": None, "likes": 50}
    assert analyze.deep_approval_rate(post) is None


def test_deep_approval_rate_uses_zero_only_after_one_component_is_known():
    post = {"views": 100, "coins": 0, "favorites": None, "likes": 50}
    assert analyze.deep_approval_rate(post) == 0.0


def test_community_discussion_rate_normal():
    # (comments + danmaku) / views = (5 + 3) / 100 = 0.08
    post = {"views": 100, "comments": 5, "danmaku": 3}
    assert analyze.community_discussion_rate(post) == 0.08


def test_community_discussion_rate_no_danmaku():
    post = {"views": 100, "comments": 5, "danmaku": 0}
    assert analyze.community_discussion_rate(post) == 0.05


def test_community_discussion_rate_zero_views_is_null():
    post = {"views": 0, "comments": 5, "danmaku": 3}
    assert analyze.community_discussion_rate(post) is None


def test_community_discussion_rate_all_unknown_components_stay_null():
    post = {"views": 100, "comments": None, "danmaku": None}
    assert analyze.community_discussion_rate(post) is None


def test_community_discussion_rate_uses_zero_only_after_one_component_is_known():
    post = {"views": 100, "comments": 0, "danmaku": None}
    assert analyze.community_discussion_rate(post) == 0.0


def test_engagement_note_discloses_null_numerator_policy():
    note = analyze.compute_engagement([], {})["denominator_note"]

    assert "分子全部为 null 时比率为 null" in note
    assert "至少一项已知时其余 null 按 0" in note


# ---------------------------------------------------------------------------
# P0 四分位距散布比（IQR Ratio）：metric_stats 计算 iqr 与 dispersion_ratio
# ---------------------------------------------------------------------------
def test_metric_stats_iqr_and_dispersion():
    vals = [1, 2, 3, 4, 5]
    st = analyze.metric_stats(vals, valid_count=5)
    assert st["median"] == 3.0
    assert st["p25"] == 2.0
    assert st["p75"] == 4.0
    assert st["iqr"] == 2.0
    # dispersion_ratio = iqr / median = 2/3，保留 4 位小数
    assert st["dispersion_ratio"] == round(2 / 3, 4)


def test_metric_stats_iqr_zero_median_dispersion_null():
    # median 为 0 时 dispersion_ratio 置 null（禁止用 0 做分母）
    vals = [0, 0, 0, 0, 0]
    st = analyze.metric_stats(vals, valid_count=5)
    assert st["median"] == 0.0
    assert st["iqr"] == 0.0
    assert st["dispersion_ratio"] is None


def test_metric_stats_empty_dispersion_null():
    st = analyze.metric_stats([], valid_count=5)
    assert st["iqr"] is None
    assert st["dispersion_ratio"] is None
