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
