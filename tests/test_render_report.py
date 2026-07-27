"""仪表盘可视化升级（P1）单元测试：轻量内联 SVG 图表与发布节奏渲染。

离线、确定性，直接调用 render_report 纯函数。
"""
import pytest

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


def test_completed_taxonomy_report_does_not_warn_that_it_may_be_pending():
    analysis = {
        "classification_status": "completed",
        "meta": {"classification_status": "completed"},
        "posts": [{"format": "news"}, {"format": "news"}],
        "sample_boundary": {"valid": 20},
    }

    strategy_md, strategy_html = render_report.build_strategy(analysis, {})
    limits_md, limits_html = render_report.build_sample_limits(analysis, {})

    for rendered in (strategy_md, strategy_html, limits_md, limits_html):
        assert "可能为 pending-model" not in rendered
        assert "分类已完成" in rendered


def test_content_structure_labels_platform_carrier_separately_from_model_format():
    md, html = render_report.build_content_structure(
        {}, [{"content_type": "other", "is_pinned": False}]
    )

    for rendered in (md, html):
        assert "平台内容载体" in rendered
        assert "content_type" in rendered
        assert "模型分类的内容形式（format）" in rendered


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


@pytest.mark.parametrize(
    ("profile", "expected", "unexpected"),
    [
        (
            {
                "platform": "bilibili",
                "account_id": "42",
                "account_name": "B 站账号",
                "verified": False,
                "level": 6,
                "platform_metrics": {},
            },
            ("认证信息", "否", "账号等级", "6"),
            (),
        ),
        (
            {
                "platform": "douyin",
                "account_id": "sec-id",
                "account_name": "抖音账号",
                "verified": True,
                "platform_metrics": {
                    "douyin_id": "public-douyin-id",
                    "unique_id": "legacy-id",
                    "total_likes": 12345,
                },
            },
            ("认证信息", "是", "抖音号", "public-douyin-id", "获赞总量", "12,345"),
            ("legacy-id",),
        ),
        (
            {
                "platform": "weibo",
                "account_id": "wb-1",
                "account_name": "微博账号",
                "verified": None,
                "platform_metrics": {"following": 88},
            },
            ("认证信息", "—", "关注数", "88"),
            (),
        ),
    ],
)
def test_account_card_renders_platform_fields_and_tri_state_verified(
    profile, expected, unexpected
):
    md, html = render_report.build_account_card(profile)

    for rendered in (md, html):
        for value in expected:
            assert value in rendered
        for value in unexpected:
            assert value not in rendered


def test_account_card_uses_douyin_unique_id_fallback_and_dashes_for_nulls():
    profile = {
        "platform": "douyin",
        "account_id": None,
        "account_name": None,
        "verified": None,
        "followers": None,
        "post_count": None,
        "bio": None,
        "profile_url": None,
        "platform_metrics": {"unique_id": "fallback-id", "total_likes": None},
    }

    md, html = render_report.build_account_card(profile)

    assert "| 抖音号 | fallback-id |" in md
    assert "| 获赞总量 | — |" in md
    assert "| 认证信息 | — |" in md
    assert "<td>抖音号</td><td>fallback-id</td>" in html
    assert "<td>获赞总量</td><td>—</td>" in html
    assert "<td>认证信息</td><td>—</td>" in html
    assert "None" not in md
    assert "None" not in html


def test_account_card_escapes_certification_text_in_both_formats():
    profile = {
        "platform": "weibo",
        "account_name": "安全测试",
        "verified": "<script>alert('verified')</script>|[link](javascript:x)",
        "platform_metrics": {"following": None},
    }

    md, html = render_report.build_account_card(profile)

    assert "<script>" not in md
    assert "[link](javascript:x)" not in md
    assert "&lt;script&gt;" in md
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<td>关注数</td><td>—</td>" in html


def test_sample_quality_and_limits_render_all_status_counts_with_zero_defaults():
    analysis = {
        "sample_boundary": {
            "requested": 4,
            "collected": 4,
            "valid": 3,
            "missing": 1,
            "restricted": 0,
            "excluded_flagged": 0,
            "status_counts": {"SUCCESS": 2, "PARTIAL": 1},
            "time_range": {},
        }
    }
    expected_rows = (
        ("SUCCESS", "2"),
        ("PARTIAL", "1"),
        ("FAILED", "0"),
        ("DELETED", "0"),
        ("RESTRICTED", "0"),
    )

    quality = render_report.build_quality_summary(analysis)
    limits = render_report.build_sample_limits(analysis, {})

    for md, html in (quality, limits):
        for status, count in expected_rows:
            assert f"| 采集状态 {status} | {count} |" in md
            assert f"<td>采集状态 {status}</td><td>{count}</td>" in html


@pytest.mark.parametrize(
    ("status", "version", "coverage", "status_label", "version_label"),
    [
        (
            "pending-model",
            None,
            {
                "total_count": 4,
                "classified_count": 0,
                "pending_count": 4,
                "rate": 0.0,
            },
            "pending-model（待分类）",
            "—",
        ),
        (
            "completed",
            "llm-1",
            {
                "total_count": 4,
                "classified_count": 4,
                "pending_count": 0,
                "rate": 1.0,
            },
            "completed（已完成）",
            "llm-1",
        ),
    ],
)
def test_task_info_renders_complete_classification_lifecycle_in_both_formats(
    status, version, coverage, status_label, version_label
):
    analysis = {
        "meta": {
            "classification_status": status,
            "classification_version": version,
            "classification_coverage": coverage,
        },
        "classification_status": status,
        "classification_version": version,
        "classification_coverage": coverage,
    }

    md, html = render_report.build_task_info(analysis, {}, [])

    expected = (
        status_label,
        version_label,
        "分类总数 (total_count)",
        "4",
        "已分类数 (classified_count)",
        "待分类数 (pending_count)",
        "分类覆盖率 (rate)",
        "0.0000" if status == "pending-model" else "1.0000",
    )
    for rendered in (md, html):
        for value in expected:
            assert value in rendered
    if status == "pending-model":
        assert "classification_version = pending-model" not in md
        assert "classification_version = pending-model" not in html


def test_content_patterns_separate_pending_from_model_unknown_and_other():
    analysis = {
        "posts": [
            {"topic": None, "format": None, "funnel_stage": None, "hook_type": None},
            {
                "topic": "unknown",
                "format": "other",
                "funnel_stage": "unknown",
                "hook_type": "unknown",
            },
            {
                "topic": "<script>topic</script>|[x](javascript:y)",
                "format": "tutorial",
                "funnel_stage": "education",
                "hook_type": "question",
            },
        ]
    }

    md, html = render_report.build_content_patterns(analysis)

    for rendered in (md, html):
        assert "待分类" in rendered
        assert "unknown（模型无法判断）" in rendered
        assert "other" in rendered
        assert "未分类/unknown" not in rendered
        assert "<script>" not in rendered
    assert "&lt;script&gt;topic&lt;/script&gt;" in md
    assert "&lt;script&gt;topic&lt;/script&gt;" in html


def test_content_patterns_render_comment_evidence_contract_in_both_formats():
    analysis = {
        "meta": {"platform": "douyin"},
        "posts": [],
        "comment_analysis": {
            "schema_version": 1,
            "status": "collected_pending_model",
            "requested": True,
            "sampled_comment_count": 2,
            "eligible_parent_posts": 3,
            "covered_parent_posts": 1,
            "parent_coverage_rate": 1 / 3,
            "collection_ledger": {
                "attempted_posts": 3,
                "comments_collected": 2,
                "empty_results": 1,
                "failures": 1,
                "per_post_limit": 20,
                "stop_reason": None,
            },
            "field_coverage": {
                "author": {"present": 1, "total": 2, "rate": 0.5},
                "text": {"present": 2, "total": 2, "rate": 1.0},
                "likes": {"present": 1, "total": 2, "rate": 0.5},
                "published_at": {"present": 0, "total": 2, "rate": 0.0},
                "collected_at": {"present": 2, "total": 2, "rate": 1.0},
            },
            "representative_selection": {
                "max_parent_posts": 3,
                "max_per_parent": 1,
                "order": "visible_likes_desc_then_source_line",
            },
            "representative_comments": [
                {
                    "comment_id": "c1",
                    "parent_post_id": "1001",
                    "parent_post_url": "https://www.douyin.com/video/1001",
                    "author": None,
                    "text": "公开问题",
                    "likes": None,
                    "published_at": None,
                    "collected_at": "2026-07-03T10:00:00+08:00",
                    "source_artifact": "source/comments.jsonl",
                    "source_line": 2,
                }
            ],
            "semantic": {
                "status": "pending-model",
                "model_version": None,
                "insights": None,
            },
            "limitations": ["仅为公开评论样本。"],
        },
    }

    md, html = render_report.build_content_patterns(analysis)

    for rendered in (md, html):
        for expected in (
            "评论证据",
            "collected_pending_model",
            "2",
            "1/3",
            "0.3333",
            "attempted_posts",
            "comments_collected",
            "empty_results",
            "failures",
            "per_post_limit",
            "stop_reason",
            "字段覆盖率",
            "author",
            "published_at",
            "代表评论",
            "c1",
            "公开问题",
            "source/comments.jsonl:2",
            "pending-model",
            "语义洞察待模型处理",
            "仅为公开评论样本。",
        ):
            assert expected in rendered
        assert "高频问题" not in rendered
        assert "争议点" not in rendered
        assert "需求洞察" not in rendered
    assert "—" in md
    assert "—" in html
    assert (
        "[作品 1001](https://www.douyin.com/video/1001)" in md
    )
    assert (
        'href="https://www.douyin.com/video/1001"' in html
    )


def test_comment_report_escapes_hostile_fields_and_drops_noncanonical_link():
    hostile = '<script>alert(1)</script>|![x](javascript:y)'
    analysis = {
        "meta": {"platform": "douyin"},
        "posts": [],
        "comment_analysis": {
            "schema_version": 1,
            "status": "collected_pending_model",
            "requested": True,
            "sampled_comment_count": 1,
            "eligible_parent_posts": 1,
            "covered_parent_posts": 1,
            "parent_coverage_rate": 1.0,
            "collection_ledger": {
                "attempted_posts": 1,
                "comments_collected": 1,
                "empty_results": 0,
                "failures": 0,
                "per_post_limit": 20,
                "stop_reason": None,
            },
            "field_coverage": {},
            "representative_selection": {
                "max_parent_posts": 3,
                "max_per_parent": 1,
                "order": "visible_likes_desc_then_source_line",
            },
            "representative_comments": [{
                "comment_id": hostile,
                "parent_post_id": hostile,
                "parent_post_url": "https://evil.example/video/1001",
                "author": hostile,
                "text": hostile,
                "likes": 1,
                "published_at": None,
                "collected_at": None,
                "source_artifact": "source/comments.jsonl",
                "source_line": 1,
            }],
            "semantic": {
                "status": "pending-model",
                "model_version": None,
                "insights": None,
            },
            "limitations": [hostile],
        },
    }

    md, html = render_report.build_content_patterns(analysis)

    for rendered in (md, html):
        assert "<script>" not in rendered
        assert "https://evil.example" not in rendered
    assert "[x](javascript:" not in md
    assert 'href="javascript:' not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in md
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "href=" not in html


def _auditable_performance_item(**overrides):
    item = {
        "platform": "douyin",
        "post_id": "1001",
        "title": "审计样本",
        "post_url": "https://www.douyin.com/video/1001",
        "evidence_url": "https://www.douyin.com/video/1001",
        "item_url_known": True,
        "url_kind": "item",
        "published_at": "2026-07-01T12:30:00+08:00",
        "main_metric": "likes",
        "value": 42,
        "relative_to_main_median": 1.25,
        "metrics": {
            "views": 1000,
            "likes": 42,
            "comments": 3,
            "favorites": 4,
            "shares": 5,
            "coins": None,
            "danmaku": None,
        },
        "collected_at": "2026-07-02T09:00:00+08:00",
        "collection_source": None,
        "rank": 1,
    }
    item.update(overrides)
    return item


def test_performance_rows_render_complete_audit_contract_in_both_formats():
    analysis = {
        "meta": {"main_sort_metric": "likes"},
        "high_performance": [_auditable_performance_item()],
        "low_performance": [],
    }

    md, html = render_report.build_high_performance(analysis)

    expected = (
        "1001",
        "审计样本",
        "item（作品链接）",
        "2026-07-01T12:30:00+08:00",
        "likes",
        "点赞: 42",
        "1.2500",
        "views=1,000",
        "likes=42",
        "comments=3",
        "favorites=4",
        "shares=5",
        "coins=—",
        "danmaku=—",
        "2026-07-02T09:00:00+08:00",
    )
    for rendered in (md, html):
        for value in expected:
            assert value in rendered
    assert "[作品链接](https://www.douyin.com/video/1001)" in md
    assert 'href="https://www.douyin.com/video/1001"' in html


def test_profile_index_evidence_is_never_rendered_as_an_item_link():
    profile_anchor = "https://www.douyin.com/user/profile-owner"
    item = _auditable_performance_item(
        post_id="idx-1",
        title="索引样本",
        post_url=None,
        evidence_url=profile_anchor,
        item_url_known=False,
        url_kind="profile_index",
    )
    analysis = {
        "meta": {"main_sort_metric": "likes"},
        "high_performance": [item],
        "low_performance": [],
    }

    md, html = render_report.build_high_performance(analysis)

    for rendered in (md, html):
        assert "profile_index" in rendered
        assert "主页证据锚点" in rendered
        assert "不是作品链接" in rendered
    assert f"[索引样本]({profile_anchor})" not in md
    assert f'<a href="{profile_anchor}">索引样本</a>' not in html
    assert "item（作品链接）" not in md
    assert "item（作品链接）" not in html


@pytest.mark.parametrize(
    "candidate",
    [
        "https://outside.example/video/1001",
        "https://www.douyin.com/user/1001",
        "https://www.douyin.com/video/9999",
    ],
)
def test_safe_https_without_platform_path_and_parent_binding_is_not_an_item_link(
    candidate
):
    item = _auditable_performance_item(
        post_url=candidate,
        evidence_url=candidate,
    )
    analysis = {
        "meta": {"platform": "douyin", "main_sort_metric": "likes"},
        "high_performance": [item],
        "low_performance": [],
        "posts": [],
    }
    template = "<html><body>" + "".join(
        f"{{{{{name}}}}}" for name in render_report.PLACEHOLDERS
    ) + "</body></html>"

    result = render_report.render_in_memory(
        profile={"platform": "douyin"},
        posts_csv=[],
        analysis=analysis,
        template=template,
    )

    assert "item（无安全作品链接）" in result.markdown
    assert "item（无安全作品链接）" in result.html
    assert f"]({candidate})" not in result.markdown
    assert f'href="{candidate}"' not in result.html


@pytest.mark.parametrize(
    "candidate",
    [
        "https://outside.example/user/profile-owner",
        "https://www.douyin.com/video/1001",
    ],
)
def test_profile_index_anchor_requires_a_canonical_douyin_profile(candidate):
    item = _auditable_performance_item(
        post_id="idx-1",
        post_url=None,
        evidence_url=candidate,
        item_url_known=False,
        url_kind="profile_index",
    )
    analysis = {
        "meta": {"platform": "douyin", "main_sort_metric": "likes"},
        "high_performance": [item],
        "low_performance": [],
    }

    md, html = render_report.build_high_performance(analysis)

    assert "profile_index（主页证据锚点，不是作品链接）" in md
    assert "profile_index（主页证据锚点，不是作品链接）" in html
    assert f"]({candidate})" not in md
    assert f'href="{candidate}"' not in html


def test_core_insights_render_source_statements_and_every_evidence_row():
    item = _auditable_performance_item()
    analysis = {
        "meta": {"platform": "douyin", "main_sort_metric": "likes"},
        "high_performance": [item],
        "low_performance": [],
        "core_insights": [
            {
                "id": "performance-high",
                "kind": "high_performance",
                "statement": "高表现组按 likes 确定性排名。",
                "main_metric": "likes",
                "evidence": [
                    {
                        "post_id": "1002",
                        "url": "https://www.douyin.com/video/1002",
                        "url_kind": "item",
                        "collected_at": "2026-07-03T10:00:00+08:00",
                        "metrics": item["metrics"],
                        "rank": 2,
                        "value": 41,
                    }
                ],
            }
        ],
    }

    md, html = render_report.build_high_performance(analysis)

    expected = (
        "performance-high",
        "高表现组按 likes 确定性排名。",
        "1002",
        "item（作品链接）",
        "rank=2",
        "likes=41",
        "2026-07-03T10:00:00+08:00",
    )
    for rendered in (md, html):
        for value in expected:
            assert value in rendered


def test_performance_and_insight_fields_escape_markup_and_reject_unsafe_urls():
    malicious_url = "javascript:alert(1)"
    item = _auditable_performance_item(
        title="<script>alert('title')</script>|[x](javascript:y)",
        post_url=malicious_url,
        evidence_url=malicious_url,
        metrics={
            "views": "<img src=x onerror=alert(1)>",
            "likes": 42,
            "comments": 3,
            "favorites": 4,
            "shares": 5,
            "coins": None,
            "danmaku": None,
        },
    )
    analysis = {
        "meta": {"main_sort_metric": "likes"},
        "high_performance": [item],
        "low_performance": [],
        "core_insights": [
            {
                "id": "performance-high",
                "kind": "high_performance",
                "statement": "<svg onload=alert('statement')>",
                "main_metric": "likes",
                "evidence": [
                    {
                        "post_id": "1001",
                        "url": malicious_url,
                        "url_kind": "item",
                        "collected_at": item["collected_at"],
                        "metrics": item["metrics"],
                        "rank": 1,
                        "value": 42,
                    }
                ],
            }
        ],
    }

    md, html = render_report.build_high_performance(analysis)

    assert "<script>" not in md
    assert "<img" not in md
    assert "<svg" not in md
    assert "](javascript:alert" not in md
    assert "javascript:alert%281%29" not in md
    assert "<script>" not in html
    assert "<img" not in html
    assert "<svg" not in html
    assert 'href="javascript:' not in html
    assert "&lt;script&gt;" in md
    assert "&lt;script&gt;" in html


def _template_with_existing_placeholders():
    return "<html><body>" + "".join(
        f"{{{{{name}}}}}" for name in render_report.PLACEHOLDERS
    ) + "</body></html>"


@pytest.mark.parametrize(
    "candidate",
    [
        "https://outside.example/video/1001",
        "https://www.douyin.com/video/9999",
        "https://www.douyin.com/user/1001",
    ],
)
def test_sources_do_not_link_or_reference_unbound_https_item_candidates(candidate):
    analysis = {
        "meta": {"platform": "douyin"},
        "posts": [
            {
                "platform": "douyin",
                "post_id": "1001",
                "post_url": candidate,
                "item_url_known": True,
                "url_kind": "item",
            }
        ],
        "high_performance": [],
        "low_performance": [],
    }

    result = render_report.render_in_memory(
        profile={"platform": "douyin"},
        posts_csv=[],
        analysis=analysis,
        template=_template_with_existing_placeholders(),
    )

    assert f"]({candidate})" not in result.markdown
    assert f'href="{candidate}"' not in result.html


def test_sources_keep_canonical_jingxuan_item_link_bound_to_parent_id():
    post_id = "7646342441319408036"
    url = f"https://jingxuan.douyin.com/m/video/{post_id}"
    analysis = {
        "meta": {
            "platform": "douyin",
            "collection_source": "douyin_jingxuan",
        },
        "posts": [
            {
                "platform": "douyin",
                "post_id": post_id,
                "post_url": url,
                "item_url_known": True,
                "url_kind": "item",
                "collection_source": "douyin_jingxuan",
            }
        ],
        "high_performance": [],
        "low_performance": [],
    }

    result = render_report.render_in_memory(
        profile={"platform": "douyin"},
        posts_csv=[{"post_url": url}],
        analysis=analysis,
        template=_template_with_existing_placeholders(),
    )

    assert f"[{post_id}]({url})" in result.markdown
    assert f'href="{url}"' in result.html


def test_sources_keep_profile_index_homepage_only_as_account_source():
    profile_url = "https://www.douyin.com/user/profile-owner"
    analysis = {
        "meta": {
            "platform": "douyin",
            "collection_source": "douyin_search_index",
        },
        "posts": [
            {
                "platform": "douyin",
                "post_id": "idx-1",
                "post_url": None,
                "evidence_url": profile_url,
                "item_url_known": False,
                "url_kind": "profile_index",
                "collection_source": "douyin_search_index",
            }
        ],
        "high_performance": [],
        "low_performance": [],
    }

    result = render_report.render_in_memory(
        profile={"platform": "douyin", "profile_url": profile_url},
        posts_csv=[],
        analysis=analysis,
        template=_template_with_existing_placeholders(),
    )
    sources_md, sources_html = render_report.build_sources(
        analysis, {"profile_url": profile_url}
    )

    assert result.diagnostics == ()
    assert sources_md.count(f"]({profile_url})") == 1
    assert sources_html.count(f'href="{profile_url}"') == 1
    assert "idx-1" not in sources_md
