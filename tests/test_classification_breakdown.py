"""FR-011/FR-012 deterministic classification-analysis contracts."""

from __future__ import annotations

import copy

from analysis import analyze
import pytest
from analysis import render_report


def _row(index: int, views, **overrides) -> dict:
    post_id = f"{index:02d}"
    row = {
        "platform": "douyin",
        "post_id": post_id,
        "post_url": f"https://www.douyin.com/video/{post_id}",
        "published_at": f"2026-07-{index:02d}T08:00:00+08:00",
        "content_type": "video",
        "title": f"作品 {post_id}",
        "duration_seconds": 30,
        "hashtags": [],
        "is_pinned": False,
        "is_repost": False,
        "is_promoted": False,
        "collection_status": "SUCCESS",
        "collected_at": "2026-07-20T09:00:00+08:00",
        "views": views,
        "likes": None,
        "comments": None,
        "favorites": None,
        "shares": None,
        "coins": None,
        "danmaku": None,
    }
    row.update(overrides)
    return row


def _classification(post_id: str, **overrides) -> dict:
    result = {
        "post_id": post_id,
        "topic": "中间主题",
        "format": "commentary",
        "funnel_stage": "awareness",
        "hook_type": "question",
        "series_name": None,
        "is_original": None,
        "has_product_placement": None,
        "analysis_labels": [],
        "classification_confidence": 0.9,
    }
    result.update(overrides)
    return result


def _analyze(rows: list[dict], classifications=None) -> dict:
    return analyze.analyze_in_memory(
        {
            "platform": "douyin",
            "account_name": "测试账号",
            "profile_url": "https://www.douyin.com/user/example",
            "followers": None,
        },
        rows,
        {"platform": "douyin", "analysis_goal": "播放表现"},
        classification_results=classifications,
    ).analysis


def _feature(comparison: dict, field: str) -> dict:
    return next(item for item in comparison["features"] if item["field"] == field)


def _validate_contracts(
    result: dict,
    *,
    breakdown: dict | None = None,
    comparison: dict | None = None,
) -> None:
    analyze.validate_deterministic_analysis_contracts(
        breakdown or result["classification_breakdown"],
        comparison or result["high_low_feature_comparison"],
        {
            "classification_status": result["classification_status"],
            "classification_version": result["classification_version"],
            "classification_coverage": result["classification_coverage"],
        },
        result["performance_meta"],
        result["high_performance"],
        result["low_performance"],
    )


class _IterationCountingList(list):
    def __init__(self, values):
        super().__init__(values)
        self.iteration_count = 0

    def __iter__(self):
        self.iteration_count += 1
        return super().__iter__()


def _matrix_fixture() -> tuple[list[dict], list[dict]]:
    rows = [
        _row(1, 0),
        _row(2, None),
        _row(3, 10),
        _row(4, 20),
    ]
    classifications = [
        _classification("01", topic="主题甲", format="tutorial"),
        _classification("02", topic="主题甲", format="vlog"),
        _classification("03", topic="主题乙", format="tutorial"),
        _classification("04", topic="unknown", format="other"),
    ]
    return rows, classifications


def _feature_fixture() -> tuple[list[dict], list[dict]]:
    rows = [_row(index, index) for index in range(1, 16)]
    by_id = {row["post_id"]: row for row in rows}
    by_id["15"].update(duration_seconds=14, hashtags=["共同标签", "高组标签", "共同标签"])
    by_id["14"].update(duration_seconds=15, hashtags=["共同标签"])
    by_id["13"].update(duration_seconds=None, hashtags=[])
    by_id["03"].update(duration_seconds=59, hashtags=["共同标签", "低组标签"])
    by_id["02"].update(duration_seconds=60, hashtags=[])
    by_id["01"].update(duration_seconds=180, hashtags=["低组标签"])

    classifications = [_classification(row["post_id"]) for row in rows]
    by_classification = {item["post_id"]: item for item in classifications}
    by_classification["15"].update(
        topic="共同主题",
        format="tutorial",
        funnel_stage="education",
        hook_type="result_first",
        series_name="共同栏目",
        is_original=False,
        has_product_placement=False,
    )
    by_classification["14"].update(
        topic="共同主题",
        format="tutorial",
        funnel_stage="education",
        hook_type="result_first",
        series_name="共同栏目",
        is_original=True,
        has_product_placement=False,
    )
    by_classification["13"].update(
        topic="高组主题",
        format="tutorial",
        funnel_stage="conversion",
        hook_type="authority",
        series_name="高组栏目",
        is_original=False,
        has_product_placement=True,
    )
    by_classification["03"].update(
        topic="共同主题",
        format="tutorial",
        funnel_stage="education",
        hook_type="result_first",
        series_name="共同栏目",
        is_original=False,
        has_product_placement=False,
    )
    by_classification["02"].update(
        topic="低组主题",
        format="vlog",
        funnel_stage="retention",
        hook_type="story",
        series_name="低组栏目",
        is_original=False,
        has_product_placement=None,
    )
    by_classification["01"].update(
        topic="低组主题",
        format="vlog",
        funnel_stage="retention",
        hook_type="story",
        series_name=None,
        is_original=True,
        has_product_placement=True,
    )
    return rows, classifications


def test_pending_classification_exposes_empty_versioned_contracts_without_partial_aggregation():
    result = _analyze([_row(index, index) for index in range(1, 16)])

    assert result["classification_breakdown"] == {
        "schema_version": 1,
        "status": "pending-model",
        "classification_version": None,
        "main_metric": "views",
        "total_post_count": 15,
        "measured_post_count": 15,
        "missing_metric_count": 0,
        "topic_format_matrix": {"topics": [], "formats": [], "rows": []},
        "dimension_performance": {"topic": [], "format": []},
        "limitations": [
            "完整分类结果缺失；主题-形式矩阵与分类维度表现未计算。"
        ],
    }
    comparison = result["high_low_feature_comparison"]
    assert comparison["schema_version"] == 1
    assert comparison["status"] == "pending-model"
    assert comparison["groups"] == {
        "high": {"count": 0, "post_ids": []},
        "low": {"count": 0, "post_ids": []},
    }
    assert comparison["features"] == []


def test_pending_contract_metric_count_does_not_collapse_duplicate_post_ids():
    result = _analyze([_row(1, 0), _row(1, 10)])

    assert result["performance_meta"]["measured_count"] == 2
    assert result["classification_breakdown"]["measured_post_count"] == 2
    assert result["classification_breakdown"]["missing_metric_count"] == 0
    assert result["high_low_feature_comparison"]["measured_count"] == 2


def test_complete_classification_builds_full_topic_format_matrix_and_transparent_bucket_metrics():
    rows, classifications = _matrix_fixture()

    breakdown = _analyze(rows, classifications)["classification_breakdown"]

    assert breakdown["status"] == "completed"
    assert breakdown["classification_version"] == "llm-1"
    assert breakdown["main_metric"] == "views"
    assert breakdown["total_post_count"] == 4
    assert breakdown["measured_post_count"] == 3
    assert breakdown["missing_metric_count"] == 1
    assert breakdown["topic_format_matrix"] == {
        "topics": ["unknown", "主题乙", "主题甲"],
        "formats": ["tutorial", "vlog", "other"],
        "rows": [
            {"topic": "unknown", "post_count": 1, "counts": [0, 0, 1]},
            {"topic": "主题乙", "post_count": 1, "counts": [1, 0, 0]},
            {"topic": "主题甲", "post_count": 2, "counts": [1, 1, 0]},
        ],
    }
    assert breakdown["dimension_performance"]["topic"] == [
        {
            "value": "unknown",
            "post_count": 1,
            "measured_count": 1,
            "missing_count": 0,
            "measurement_rate": 1.0,
            "main_metric_median": 20.0,
        },
        {
            "value": "主题乙",
            "post_count": 1,
            "measured_count": 1,
            "missing_count": 0,
            "measurement_rate": 1.0,
            "main_metric_median": 10.0,
        },
        {
            "value": "主题甲",
            "post_count": 2,
            "measured_count": 1,
            "missing_count": 1,
            "measurement_rate": 0.5,
            "main_metric_median": 0.0,
        },
    ]
    assert breakdown["dimension_performance"]["format"] == [
        {
            "value": "tutorial",
            "post_count": 2,
            "measured_count": 2,
            "missing_count": 0,
            "measurement_rate": 1.0,
            "main_metric_median": 5.0,
        },
        {
            "value": "vlog",
            "post_count": 1,
            "measured_count": 0,
            "missing_count": 1,
            "measurement_rate": 0.0,
            "main_metric_median": None,
        },
        {
            "value": "other",
            "post_count": 1,
            "measured_count": 1,
            "missing_count": 0,
            "measurement_rate": 1.0,
            "main_metric_median": 20.0,
        },
    ]


def test_classification_breakdown_is_independent_of_post_and_result_input_order():
    rows, classifications = _matrix_fixture()

    forward = _analyze(rows, classifications)["classification_breakdown"]
    reverse = _analyze(
        list(reversed(rows)), list(reversed(classifications))
    )["classification_breakdown"]

    assert reverse == forward


def test_classification_breakdown_aggregates_post_records_in_one_auditable_pass():
    size = 250
    post_records = _IterationCountingList(
        {
            "post_id": str(index),
            "topic": f"topic-{index:04d}",
            "format": "tutorial" if index % 2 else "vlog",
        }
        for index in range(size)
    )
    valid = [
        {"post_id": str(index), "views": index}
        for index in range(size)
    ]
    classification = {
        "classification_status": "completed",
        "classification_version": "llm-1",
        "classification_coverage": {
            "total_count": size,
            "classified_count": size,
            "pending_count": 0,
            "rate": 1.0,
        },
    }

    breakdown = analyze.compute_classification_breakdown(
        post_records,
        valid,
        "views",
        classification,
    )

    assert breakdown["total_post_count"] == size
    assert len(breakdown["topic_format_matrix"]["rows"]) == size
    assert post_records.iteration_count == 1


def test_completed_classification_with_all_null_metrics_keeps_medians_null_not_zero():
    rows = [_row(index, None) for index in range(1, 4)]
    classifications = [
        _classification(row["post_id"], topic="空值主题", format="tutorial")
        for row in rows
    ]

    result = _analyze(rows, classifications)
    bucket = result["classification_breakdown"]["dimension_performance"]["topic"][0]

    assert result["classification_breakdown"]["measured_post_count"] == 0
    assert bucket == {
        "value": "空值主题",
        "post_count": 3,
        "measured_count": 0,
        "missing_count": 3,
        "measurement_rate": 0.0,
        "main_metric_median": None,
    }
    assert result["high_low_feature_comparison"]["status"] == "insufficient-sample"
    assert result["high_low_feature_comparison"]["measured_count"] == 0


def test_high_low_feature_comparison_joins_exact_selected_posts_without_mutating_groups():
    rows, classifications = _feature_fixture()

    result = _analyze(rows, classifications)
    comparison = result["high_low_feature_comparison"]

    assert comparison["status"] == "completed"
    assert comparison["main_metric"] == "views"
    assert comparison["measured_count"] == 15
    assert comparison["groups"] == {
        "high": {"count": 3, "post_ids": ["15", "14", "13"]},
        "low": {"count": 3, "post_ids": ["03", "02", "01"]},
    }
    assert all("topic" not in item for item in result["high_performance"])
    assert all("topic" not in item for item in result["low_performance"])
    assert [item["id"] for item in result["core_insights"]] == [
        "performance-high",
        "performance-low",
    ]


def test_high_low_feature_comparison_reports_common_and_side_only_taxonomy_values():
    rows, classifications = _feature_fixture()
    comparison = _analyze(rows, classifications)["high_low_feature_comparison"]

    topic = _feature(comparison, "topic")

    assert topic["common_values"] == ["共同主题"]
    assert topic["high_only_values"] == ["高组主题"]
    assert topic["low_only_values"] == ["低组主题"]
    assert topic["values"] == [
        {
            "value": "共同主题",
            "high_count": 2,
            "high_rate": 0.6667,
            "low_count": 1,
            "low_rate": 0.3333,
            "rate_delta": 0.3334,
        },
        {
            "value": "低组主题",
            "high_count": 0,
            "high_rate": 0.0,
            "low_count": 2,
            "low_rate": 0.6667,
            "rate_delta": -0.6667,
        },
        {
            "value": "高组主题",
            "high_count": 1,
            "high_rate": 0.3333,
            "low_count": 0,
            "low_rate": 0.0,
            "rate_delta": 0.3333,
        },
    ]


def test_high_low_feature_comparison_treats_false_as_known_and_null_as_missing():
    rows, classifications = _feature_fixture()
    comparison = _analyze(rows, classifications)["high_low_feature_comparison"]

    original = _feature(comparison, "is_original")
    placement = _feature(comparison, "has_product_placement")

    assert original["high_known_count"] == 3
    assert original["high_missing_count"] == 0
    assert original["low_known_count"] == 3
    assert original["common_values"] == [False, True]
    assert original["values"][0]["value"] is False
    assert original["values"][0]["high_count"] == 2
    assert original["values"][0]["low_count"] == 2
    assert placement["low_known_count"] == 2
    assert placement["low_missing_count"] == 1
    assert False in placement["common_values"]


def test_high_low_hashtags_deduplicate_per_post_and_treat_empty_arrays_as_missing():
    rows, classifications = _feature_fixture()
    hashtags = _feature(
        _analyze(rows, classifications)["high_low_feature_comparison"],
        "hashtags",
    )

    assert hashtags["value_mode"] == "multi"
    assert hashtags["high_known_count"] == 2
    assert hashtags["high_missing_count"] == 1
    assert hashtags["low_known_count"] == 2
    assert hashtags["low_missing_count"] == 1
    assert hashtags["common_values"] == ["共同标签"]
    assert hashtags["high_only_values"] == ["高组标签"]
    assert hashtags["low_only_values"] == ["低组标签"]
    common = next(item for item in hashtags["values"] if item["value"] == "共同标签")
    assert common == {
        "value": "共同标签",
        "high_count": 2,
        "high_rate": 1.0,
        "low_count": 1,
        "low_rate": 0.5,
        "rate_delta": 0.5,
    }


def test_high_low_duration_uses_fixed_boundaries_order_and_missing_count():
    rows, classifications = _feature_fixture()
    comparison = _analyze(rows, classifications)["high_low_feature_comparison"]
    duration = _feature(comparison, "duration_bucket")

    assert comparison["duration_buckets"] == [
        "lt_15s",
        "15_29s",
        "30_59s",
        "60_179s",
        "gte_180s",
    ]
    assert duration["high_known_count"] == 2
    assert duration["high_missing_count"] == 1
    assert duration["low_known_count"] == 3
    assert duration["low_missing_count"] == 0
    assert [item["value"] for item in duration["values"]] == comparison[
        "duration_buckets"
    ]
    assert duration["common_values"] == []
    assert duration["high_only_values"] == ["lt_15s", "15_29s"]
    assert duration["low_only_values"] == ["30_59s", "60_179s", "gte_180s"]


def test_duration_bucket_contract_covers_every_boundary_and_rejects_invalid_values():
    assert [
        analyze._duration_bucket(value)
        for value in (0, 14, 15, 29, 30, 59, 60, 179, 180)
    ] == [
        "lt_15s",
        "lt_15s",
        "15_29s",
        "15_29s",
        "30_59s",
        "30_59s",
        "60_179s",
        "60_179s",
        "gte_180s",
    ]
    assert analyze._duration_bucket(None) is None
    assert analyze._duration_bucket(-1) is None
    assert analyze._duration_bucket(True) is None


def test_high_low_feature_comparison_is_deterministic_under_reversed_input():
    rows, classifications = _feature_fixture()

    forward = _analyze(rows, classifications)["high_low_feature_comparison"]
    reverse = _analyze(
        list(reversed(rows)), list(reversed(classifications))
    )["high_low_feature_comparison"]

    assert reverse == forward


def test_complete_classification_with_insufficient_sample_emits_no_features():
    rows = [_row(index, index) for index in range(1, 15)]
    classifications = [_classification(row["post_id"]) for row in rows]

    comparison = _analyze(rows, classifications)["high_low_feature_comparison"]

    assert comparison["status"] == "insufficient-sample"
    assert comparison["measured_count"] == 14
    assert comparison["groups"] == {
        "high": {"count": 0, "post_ids": []},
        "low": {"count": 0, "post_ids": []},
    }
    assert comparison["features"] == []
    assert comparison["limitations"] == [
        "主指标实测样本 14 < 15；未生成高低组结构化特征。"
    ]


def test_contract_validator_rejects_matrix_count_contradictions():
    rows, classifications = _feature_fixture()
    result = _analyze(rows, classifications)
    broken = copy.deepcopy(result["classification_breakdown"])
    broken["topic_format_matrix"]["rows"][0]["counts"][0] += 1

    with pytest.raises(
        ValueError,
        match="deterministic analysis contract is inconsistent",
    ):
        analyze.validate_deterministic_analysis_contracts(
            broken,
            result["high_low_feature_comparison"],
            {
                "classification_status": result["classification_status"],
                "classification_version": result["classification_version"],
                "classification_coverage": result["classification_coverage"],
            },
            result["performance_meta"],
            result["high_performance"],
            result["low_performance"],
        )


def test_contract_validator_rejects_feature_count_contradictions():
    rows, classifications = _feature_fixture()
    result = _analyze(rows, classifications)
    broken = copy.deepcopy(result["high_low_feature_comparison"])
    broken["features"][0]["values"][0]["high_count"] = 99

    with pytest.raises(
        ValueError,
        match="deterministic analysis contract is inconsistent",
    ):
        analyze.validate_deterministic_analysis_contracts(
            result["classification_breakdown"],
            broken,
            {
                "classification_status": result["classification_status"],
                "classification_version": result["classification_version"],
                "classification_coverage": result["classification_coverage"],
            },
            result["performance_meta"],
            result["high_performance"],
            result["low_performance"],
        )


@pytest.mark.parametrize(
    ("target", "field", "replacement"),
    [
        ("breakdown", "main_metric", "likes"),
        ("comparison", "main_metric", "likes"),
        ("comparison", "measured_count", 14),
    ],
)
def test_contract_validator_binds_metric_metadata_to_performance_meta(
    target, field, replacement
):
    rows, classifications = _feature_fixture()
    result = _analyze(rows, classifications)
    broken_breakdown = copy.deepcopy(result["classification_breakdown"])
    broken_comparison = copy.deepcopy(result["high_low_feature_comparison"])
    contract = (
        broken_breakdown if target == "breakdown" else broken_comparison
    )
    contract[field] = replacement

    with pytest.raises(
        ValueError,
        match="deterministic analysis contract is inconsistent",
    ):
        _validate_contracts(
            result,
            breakdown=broken_breakdown,
            comparison=broken_comparison,
        )


@pytest.mark.parametrize("mutation", ["topic-row", "format-column"])
def test_contract_validator_rejects_plausible_matrix_redistribution(mutation):
    rows, classifications = _matrix_fixture()
    result = _analyze(rows, classifications)
    broken = copy.deepcopy(result["classification_breakdown"])
    matrix_rows = broken["topic_format_matrix"]["rows"]
    if mutation == "topic-row":
        matrix_rows[1].update(post_count=2, counts=[2, 0, 0])
        matrix_rows[2].update(post_count=1, counts=[0, 1, 0])
    else:
        matrix_rows[0]["counts"] = [0, 1, 0]

    with pytest.raises(
        ValueError,
        match="deterministic analysis contract is inconsistent",
    ):
        _validate_contracts(result, breakdown=broken)


def _render_contracts() -> dict:
    hostile = "主题|<script>alert(1)</script>"
    value = "标签|<img src=x>![x](javascript:y)"
    return {
        "posts": [],
        "classification_breakdown": {
            "schema_version": 1,
            "status": "completed",
            "classification_version": "llm-1",
            "main_metric": "views",
            "total_post_count": 1,
            "measured_post_count": 1,
            "missing_metric_count": 0,
            "topic_format_matrix": {
                "topics": [hostile],
                "formats": ["tutorial"],
                "rows": [{"topic": hostile, "post_count": 1, "counts": [1]}],
            },
            "dimension_performance": {
                "topic": [
                    {
                        "value": hostile,
                        "post_count": 1,
                        "measured_count": 1,
                        "missing_count": 0,
                        "measurement_rate": 1.0,
                        "main_metric_median": 0.0,
                    }
                ],
                "format": [],
            },
            "limitations": [],
        },
        "high_low_feature_comparison": {
            "schema_version": 1,
            "status": "completed",
            "main_metric": "views",
            "measured_count": 15,
            "groups": {
                "high": {"count": 3, "post_ids": ["15", "14", "13"]},
                "low": {"count": 3, "post_ids": ["03", "02", "01"]},
            },
            "duration_buckets": [
                "lt_15s",
                "15_29s",
                "30_59s",
                "60_179s",
                "gte_180s",
            ],
            "features": [
                {
                    "field": "hashtags",
                    "value_mode": "multi",
                    "high_known_count": 3,
                    "high_missing_count": 0,
                    "low_known_count": 3,
                    "low_missing_count": 0,
                    "common_values": [value],
                    "high_only_values": [],
                    "low_only_values": [],
                    "values": [
                        {
                            "value": value,
                            "high_count": 1,
                            "high_rate": 0.3333,
                            "low_count": 1,
                            "low_rate": 0.3333,
                            "rate_delta": 0.0,
                        }
                    ],
                }
            ],
            "limitations": ["仅描述结构化字段，不构成因果结论。"],
        },
    }


def test_content_patterns_render_new_json_contracts_with_same_numbers_in_markdown_and_html():
    md, html = render_report.build_content_patterns(_render_contracts())

    for rendered in (md, html):
        assert "主题 × 形式计数矩阵" in rendered
        assert "分类维度主指标表现" in rendered
        assert "高低组结构化特征对比" in rendered
        assert "views" in rendered
        assert "0" in rendered
        assert "0.3333" in rendered


def test_content_patterns_escape_hostile_matrix_and_feature_values_in_both_formats():
    md, html = render_report.build_content_patterns(_render_contracts())

    for rendered in (md, html):
        assert "<script>" not in rendered
        assert "<img" not in rendered
        assert "![x](javascript:y)" not in rendered
        assert "href=\"javascript:" not in rendered
        assert "&lt;script&gt;" in rendered
        assert "&lt;img src=x&gt;" in rendered
    assert "主题\\|" in md
    assert "标签\\|" in md


def test_content_patterns_render_pending_and_insufficient_states_without_empty_tables():
    pending = _render_contracts()
    pending["classification_breakdown"] = {
        **pending["classification_breakdown"],
        "status": "pending-model",
        "topic_format_matrix": {"topics": [], "formats": [], "rows": []},
        "dimension_performance": {"topic": [], "format": []},
        "limitations": ["完整分类结果缺失；主题-形式矩阵与分类维度表现未计算。"],
    }
    pending["high_low_feature_comparison"] = {
        **pending["high_low_feature_comparison"],
        "status": "pending-model",
        "features": [],
        "limitations": ["完整分类结果缺失；高低组结构化特征未计算。"],
    }
    pending_md, pending_html = render_report.build_content_patterns(pending)

    insufficient = copy.deepcopy(pending)
    insufficient["high_low_feature_comparison"].update(
        status="insufficient-sample",
        measured_count=14,
        limitations=["主指标实测样本 14 < 15；未生成高低组结构化特征。"],
    )
    insufficient_md, insufficient_html = render_report.build_content_patterns(
        insufficient
    )

    for rendered in (pending_md, pending_html):
        assert "完整分类结果缺失" in rendered
        assert "主题 × 形式计数矩阵" not in rendered
    for rendered in (insufficient_md, insufficient_html):
        assert "主指标实测样本 14 &lt; 15" in rendered or "主指标实测样本 14 < 15" in rendered
        assert "高低组结构化特征对比" not in rendered


def test_content_patterns_remain_compatible_with_legacy_json_missing_new_keys():
    md, html = render_report.build_content_patterns({"posts": []})

    assert md == render_report.EMPTY_MD
    assert html == render_report.EMPTY_HTML
