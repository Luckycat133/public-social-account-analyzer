"""Regression gates for model handoff quality and lifecycle semantics."""

from __future__ import annotations

import importlib
import pytest


def _post(index: int, *, views: int = 100) -> dict:
    return {
        "platform": "bilibili",
        "post_id": str(index),
        "post_url": f"https://www.bilibili.com/video/BV{index:010d}",
        "title": f"公开内容方法 {index}",
        "text": f"先说明问题，再给出步骤 {index}",
        "hashtags": ["内容方法"],
        "collection_status": "SUCCESS",
        "collected_at": "2026-07-01T08:00:00+08:00",
        "views": views,
        "likes": 10,
        "comments": 2,
        "favorites": 1,
        "shares": 1,
        "coins": 1,
        "danmaku": 1,
        "platform_metrics": {},
    }


def _classification(post: dict, topic: str) -> dict:
    return {
        "post_id": post["post_id"],
        "topic": topic,
        "format": "tutorial",
        "funnel_stage": "education",
        "hook_type": "unknown",
        "series_name": None,
        "is_original": None,
        "has_product_placement": None,
        "analysis_labels": [],
        "classification_confidence": 0.8,
    }


def test_taxonomy_quality_rejects_one_topic_per_post_fragmentation():
    analyze = importlib.import_module("analyze")
    posts = [_post(index) for index in range(1, 16)]
    results = [
        _classification(post, f"主题{chr(0x4e00 + index)}")
        for index, post in enumerate(posts)
    ]

    with pytest.raises(ValueError, match="taxonomy quality"):
        analyze.validate_classification_results(posts, results)


def test_comment_semantic_is_not_applicable_without_public_comments():
    analyze = importlib.import_module("analyze")
    result = analyze.analyze_comments_in_memory(
        [_post(1)],
        {"include_comments": False},
        platform="bilibili",
    )

    assert result["semantic"] == {
        "status": "not-applicable",
        "model_version": None,
        "insights": None,
    }


def test_performance_axes_exclude_tiny_denominator_from_efficiency():
    analyze = importlib.import_module("analyze")
    posts = [_post(index, views=100 + index * 10) for index in range(1, 21)]
    posts[0].update(views=1, likes=1000, comments=1000, favorites=1000, shares=1000)

    axes = analyze.compute_performance_axes(posts)

    assert axes["reach"]["main_metric"] == "views"
    assert axes["reach"]["status"] == "ok"
    assert axes["engagement_efficiency"]["main_metric"] == "view_based_engagement_rate"
    assert axes["engagement_efficiency"]["denominator_floor"] > 1
    selected_ids = {
        item["post_id"]
        for side in ("high", "low")
        for item in axes["engagement_efficiency"][side]
    }
    assert "1" not in selected_ids


def test_dynamic_business_inventory_stays_within_evidence_driven_ranges():
    analyze = importlib.import_module("analyze")
    posts = [_post(index) for index in range(1, 16)]
    for index, post in enumerate(posts):
        post["topic"] = ("内容方法", "账号定位", "选题复盘")[index % 3]

    template = analyze.build_business_result_template(posts, [], [], "a" * 64, "b" * 64)

    assert 3 <= len(template["topic_ideas"]) <= 8
    assert 2 <= len(template["content_modes"]) <= 5
    assert 2 <= len(template["experiments"]) <= 4
    assert len(template["topic_ideas"]) == 3


def test_model_prompts_reference_compact_artifacts_instead_of_embedding_records():
    analyze = importlib.import_module("analyze")
    posts = [_post(index) for index in range(1, 31)]

    taxonomy = analyze.build_taxonomy_prompt(posts, 1000)
    business = analyze.build_business_insights_prompt(
        {"account_name": "示例"}, posts, [], [], "a" * 64, "b" * 64
    )

    assert "taxonomy-input.jsonl" in taxonomy
    assert "taxonomy-result-template.json" in taxonomy
    assert "business-evidence-catalog.jsonl" in business
    assert "business-result-template.json" in business
    assert len(taxonomy) < 8000
    assert len(business) < 10000


def test_batch_validator_reports_multiple_taxonomy_errors():
    validator = importlib.import_module("validate_model_results")
    posts = [_post(1), _post(2)]
    errors = validator.collect_taxonomy_errors(posts, [{
        "post_id": "missing",
        "format": "movie",
        "funnel_stage": "sale",
        "hook_type": "magic",
        "classification_confidence": 2,
    }])

    assert len(errors) >= 6
    assert any("missing fields" in error for error in errors)
    assert any("coverage" in error for error in errors)


def test_collect_entry_resolves_bilibili_short_profile_only():
    collect = importlib.import_module("collect")

    assert collect.canonicalize_entry_url(
        "https://b23.tv/profile", lambda _url: "https://space.bilibili.com/123?from=share"
    ) == "https://space.bilibili.com/123"
    with pytest.raises(ValueError):
        collect.canonicalize_entry_url(
            "https://b23.tv/video", lambda _url: "https://www.bilibili.com/video/BV1xx"
        )


def test_semantic_support_guard_rejects_broad_and_demographic_leaps():
    analyze = importlib.import_module("analyze")
    evidence = [{"post_id": "1", "excerpt": "创作者分享学习方法"}]

    with pytest.raises(ValueError, match="semantic support"):
        analyze._validate_business_claim_support(
            {"statement": "这一需求已验证", "evidence": evidence}, "claim"
        )


def test_batch_taxonomy_validator_reports_public_evidence_conflicts_together():
    validator = importlib.import_module("validate_model_results")
    post = _post(1)
    post.update(is_repost=False, platform_metrics={"series_name": "公开系列"})
    result = _classification(post, "过长的主题名称超过十个汉字")
    result.update(
        hook_type="question",
        series_name="模型系列",
        is_original=False,
        classification_version=1,
    )

    errors = validator.collect_taxonomy_errors([post], [result])

    assert any("topic" in error for error in errors)
    assert any("hook_type lacks public evidence" in error for error in errors)
    assert any("series_name conflicts" in error for error in errors)
    assert any("is_original conflicts" in error for error in errors)
    assert any("classification_version" in error for error in errors)


def test_batch_business_validator_reports_source_group_lead_and_limitation_errors():
    validator = importlib.import_module("validate_model_results")
    posts = [_post(1), _post(2), _post(3)]
    posts[2]["text"] = "前" * 130 + "步骤 3"
    results = {
        "schema_version": 1,
        "performance_patterns": [
            {
                "id": "high-opening",
                "observability": "supported",
                "basis": "caption_lead",
                "statement": "样本特征",
                "evidence": [
                    {"post_id": "2", "source_field": "text", "excerpt": "不存在摘录\u0001"},
                    {"post_id": "3", "source_field": "text", "excerpt": "步骤 3"},
                ],
                "limitation": "字符串不允许",
            }
        ],
        "topic_ideas": [],
        "content_modes": [],
        "experiments": [],
    }

    errors = validator.collect_business_errors(
        results,
        posts=posts,
        high_ids={"1"},
        low_ids={"2", "3"},
    )

    assert any("control character" in error for error in errors)
    assert any("not source-bound" in error for error in errors)
    assert sum("wrong performance group" in error for error in errors) == 2
    assert any("caption lead" in error for error in errors)
    assert any("limitation must be null" in error for error in errors)


def test_business_evidence_id_is_resolved_to_exact_catalog_excerpt():
    analyze = importlib.import_module("analyze")
    post = _post(1)

    resolved = analyze._validate_business_evidence(
        {"evidence_id": "1:title"}, {"1": post}, "claim"
    )

    assert resolved["post_id"] == "1"
    assert resolved["source_field"] == "title"
    assert resolved["excerpt"] == "公开内容方法 1"


def test_business_template_uses_evidence_ids_and_context_exposes_group_options():
    analyze = importlib.import_module("analyze")
    posts = [_post(index) for index in range(1, 7)]
    high = [{"post_id": str(index)} for index in (1, 2, 3)]
    low = [{"post_id": str(index)} for index in (4, 5, 6)]

    template = analyze.build_business_result_template(
        posts, high, low, "a" * 64, "b" * 64
    )
    context = analyze.build_business_context(posts, high, low)

    assert template["account_positioning"]["target_audience"]["evidence"] == [
        {"evidence_id": "<choose from business-evidence-catalog.jsonl>"}
    ]
    assert template["performance_patterns"][0]["limitation"] is None
    assert context["performance_evidence_options"]["high-title"] == [
        "1:title", "2:title", "3:title"
    ]
    assert context["performance_evidence_options"]["low-opening"] == [
        "4:text", "5:text", "6:text"
    ]
    with pytest.raises(ValueError, match="demographic claim"):
        analyze._validate_business_claim_support(
            {
                "statement": "主要受众是中学生",
                "evidence": [
                    {"post_id": str(index), "excerpt": "创作者分享学习方法"}
                    for index in range(1, 4)
                ],
            },
            "claim",
        )


def test_business_semantic_guard_rejects_creator_identity_and_causal_pattern():
    analyze = importlib.import_module("analyze")
    evidence = [{"post_id": "1", "excerpt": "作为学生党，我分享动画制作过程"}]

    with pytest.raises(ValueError, match="creator identity"):
        analyze._validate_business_claim_support(
            {"statement": "主要受众是学生党创作者", "evidence": evidence},
            "target audience",
        )
    with pytest.raises(ValueError, match="causal claim"):
        analyze._validate_business_statement_support(
            "这种标题更能吸引用户并增加专业感", evidence, "pattern"
        )


def test_taxonomy_format_covers_animation_and_gameplay():
    analyze = importlib.import_module("analyze")

    assert {"animation", "gameplay"} <= analyze._TAX_FORMAT


def test_batch_business_validator_cannot_pass_when_authoritative_contract_fails():
    validator = importlib.import_module("validate_model_results")

    errors = validator.collect_business_errors(
        {
            "schema_version": 1,
            "topic_ideas": [{"id": f"topic-{index:02d}", "evidence": [{}]}
                            for index in range(1, 4)],
            "content_modes": [{"id": f"mode-{index:02d}", "evidence": [{}]}
                              for index in range(1, 3)],
            "experiments": [{"id": f"experiment-{index:02d}", "evidence": [{}]}
                            for index in range(1, 3)],
        },
        posts=[_post(index) for index in range(1, 7)],
        high_ids={"1", "2", "3"},
        low_ids={"4", "5", "6"},
        expected_collection_digest="a" * 64,
        expected_classification_digest="b" * 64,
    )

    assert any("authoritative contract" in error for error in errors)
