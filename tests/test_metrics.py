"""CASE-008（中位数）、CASE-009（分位数 p25/p75）、CASE-010（分母为零互动率 null）、
以及相对中位数表现在 median 为 0/null 时跳过（analysis-rules.md §4）。

离线、确定性，直接调用 analyze 纯函数。
"""
from datetime import datetime

import analyze


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


def test_deep_approval_rate_null_components_treated_as_zero():
    # coins/favorites 为 null 时按 0 计入分子
    post = {"views": 100, "coins": None, "favorites": None, "likes": 50}
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


def test_community_discussion_rate_null_components_treated_as_zero():
    post = {"views": 100, "comments": None, "danmaku": None}
    assert analyze.community_discussion_rate(post) == 0.0


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
