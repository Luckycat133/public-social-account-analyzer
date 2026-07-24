"""仪表盘可视化升级（P1）单元测试：轻量内联 SVG 图表与发布节奏渲染。

离线、确定性，直接调用 render_report 纯函数。
"""
import render_report


# ---------------------------------------------------------------------------
# 发布时段分布（24 小时柱状图）
# ---------------------------------------------------------------------------
def test_hour_distribution_empty_returns_empty():
    assert render_report.svg_post_hour_distribution({}) == ""


def test_hour_distribution_renders_bars():
    dist = {str(h): (3 if h == 9 else (1 if h == 20 else 0)) for h in range(24)}
    svg = render_report.svg_post_hour_distribution(dist)
    assert "<svg" in svg and "</svg>" in svg
    # 应有 24 根柱子（rect）
    assert svg.count("<rect") == 24
    # 峰值时段 09:00 计 3 条，tooltip 中出现
    assert "09:00 — 3 条" in svg


# ---------------------------------------------------------------------------
# 发布节奏章节接入时段分布（MD + HTML 双输出）
# ---------------------------------------------------------------------------
def _sample_analysis():
    return {
        "publish_cadence": {
            "total_posts": 5,
            "coverage_days": 5,
            "coverage_weeks": 1,
            "weekly_avg": 5,
            "median_interval_hours": 24,
            "longest_gap_hours": 48,
            "interval_unit": "hours",
            "weekday_weekend": {
                "weekday_count": 3, "weekend_count": 2,
                "weekday_pct": 0.6, "weekend_pct": 0.4,
            },
            "weekday_distribution": {str(i): (1 if i in (0, 1, 2) else 0) for i in range(7)},
            "hour_distribution": {str(h): (5 if h == 20 else (2 if h == 21 else 0)) for h in range(24)},
            "monthly_distribution": {},
            "seasonal_intensity": None,
            "break_month_share": None,
            "seasonal_note": None,
        },
        "posts": [],
    }


def test_build_publish_cadence_includes_hour_distribution():
    md, html = render_report.build_publish_cadence(_sample_analysis())
    # MD 含峰值时段摘要
    assert "发布时段分布" in md
    assert "20:00（5 条）" in md
    assert "白天(06:00" in md and "深夜(22:00" in md
    # HTML 含内联 SVG 图表
    assert "发布时段分布（24 小时）" in html
    assert "<svg" in html


def test_high_performance_renders_analyzer_value_field():
    analysis = {
        "meta": {"main_sort_metric": "likes"},
        "high_performance": [
            {
                "post_id": "idx-example",
                "title": "财政贴息政策解读",
                "post_url": None,
                "evidence_url": "https://www.douyin.com/user/example",
                "item_url_known": False,
                "value": 3791,
                "rank": 1,
                "reason": "主指标 likes = 3791",
            }
        ],
        "low_performance": [],
    }

    md, html = render_report.build_high_performance(analysis)

    assert "点赞: 3,791" in md
    assert "点赞: 3,791" in html
    assert "财政贴息政策解读" in md
    assert "财政贴息政策解读" in html
    assert "href=" not in html


def test_radar_is_suppressed_when_only_one_metric_is_visible():
    high = [{"metrics": {"likes": 10, "views": None, "comments": None}}]
    low = [{"metrics": {"likes": 2, "views": None, "comments": None}}]

    assert render_report.svg_high_low_radar(
        high, low, ["views", "likes", "comments"]
    ) == ""


def test_markdown_table_escapes_untrusted_markup_but_keeps_trusted_links():
    hostile = (
        "账号|越界 ![pixel](https://tracker.example/pixel.png) "
        "[点击](javascript:alert(1)) <img src=https://tracker.example/x>"
    )

    table = render_report.md_table(
        ["字段", "值"],
        [
            ["账号名称", hostile],
            [
                "账号主页",
                render_report.link_md(
                    "https://www.douyin.com/user/example",
                    "https://www.douyin.com/user/example",
                ),
            ],
        ],
    )

    assert "账号\\|越界" in table
    assert "![pixel](" not in table
    assert "[点击](javascript:" not in table
    assert "<img" not in table
    assert (
        "[https://www.douyin.com/user/example]"
        "(https://www.douyin.com/user/example)"
    ) in table


def test_high_and_low_performance_render_index_metric_note():
    analysis = {
        "meta": {
            "main_sort_metric": "likes",
            "collection_source": "douyin_search_index",
        },
        "performance_meta": {
            "metric_note": (
                "搜索索引只确认了卡片可见点赞数；"
                "不把缺失的评论、收藏、分享推算为总互动。"
            )
        },
        "high_performance": [
            {
                "post_id": "idx-example",
                "title": "索引标题",
                "post_url": None,
                "item_url_known": False,
                "value": 3791,
            }
        ],
        "low_performance": [],
    }

    high_md, high_html = render_report.build_high_performance(analysis)
    low_md, low_html = render_report.build_low_performance(analysis)

    for rendered in (high_md, high_html, low_md, low_html):
        assert "搜索索引只确认了卡片可见点赞数" in rendered
    assert "索引可见点赞: 3,791" in high_md
    assert "索引可见点赞: 3,791" in high_html


def test_non_exhaustive_index_cadence_is_labeled_as_sample_distribution():
    analysis = _sample_analysis()
    analysis["meta"] = {
        "collection_source": "douyin_jingxuan",
        "evidence_is_exhaustive": False,
    }
    analysis["publish_cadence"]["cadence_inference_allowed"] = False
    analysis["publish_cadence"]["weekly_avg"] = None
    analysis["publish_cadence"]["median_interval_hours"] = None
    analysis["publish_cadence"]["longest_gap_hours"] = None

    md, html = render_report.build_publish_cadence(analysis)

    for rendered in (md, html):
        assert "可见样本数量" in rendered
        assert "仅描述可见样本的日期分布" in rendered
        assert "总发布数量" not in rendered


def test_non_exhaustive_index_skips_cadence_based_scheduling_advice():
    analysis = _sample_analysis()
    analysis["meta"] = {
        "collection_source": "douyin_jingxuan",
        "evidence_is_exhaustive": False,
    }
    analysis["publish_cadence"]["cadence_inference_allowed"] = False
    analysis["sample_boundary"] = {"valid": 20}

    md, html = render_report.build_strategy(analysis, {})

    assert md == render_report.EMPTY_MD
    assert html == render_report.EMPTY_HTML
    assert "优先排播" not in md
    assert "稳定更新锚点" not in md
