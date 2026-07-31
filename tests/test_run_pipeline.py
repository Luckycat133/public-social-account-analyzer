"""Focused contracts for pipeline guards and delivery sanitization."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import immutable_workspace as workspace
import run_pipeline as pipeline


def _sealed_zero_post_collection(tmp_path):
    collection = tmp_path / "collection"
    artifacts = {
        "source/profile.json": json.dumps({
            "platform": "douyin",
            "account_id": "verified-profile-id",
            "account_name": "可核验账号",
            "profile_url": "https://www.douyin.com/user/verified-profile-id",
            "followers": 123,
            "field_visibility": {
                "account_id": "visible",
                "account_name": "visible",
                "followers": "visible",
            },
        }).encode(),
        "source/posts.jsonl": b"",
        "task.json": json.dumps({
            "task_id": "douyin-evidence-only",
            "platform": "douyin",
            "profile_url": "https://www.douyin.com/user/verified-profile-id",
            "analysis_goal": "分析内容策略",
            "task_status": "PARTIAL",
            "stop_reason": "PARSER_FAILED",
            "collected_count": 0,
        }).encode(),
    }
    reservation = workspace.ImmutableWorkspace.reserve(
        collection,
        allowed_artifacts=pipeline.COLLECTION_ARTIFACTS,
    )
    try:
        for relative, payload in artifacts.items():
            with reservation.open_binary(relative) as handle:
                handle.write(payload)
        reservation.commit()
    finally:
        reservation.close()
    return collection


def test_classification_requires_tax_prompt():
    with pytest.raises(
        pipeline.PipelineError,
        match="classification-results requires --with-llm-tax",
    ):
        pipeline.validate_pipeline_inputs(
            "unused-collection",
            classification_results_path="unused-results.json",
        )


def test_delivery_validation_requires_requested_business_results():
    with pytest.raises(
        pipeline.PipelineError,
        match="business insight results are required for delivery validation",
    ):
        pipeline.validate_pipeline_inputs(
            "unused-collection",
            require_business_insights=True,
        )


def test_delivery_validation_requires_requested_comment_results():
    with pytest.raises(
        pipeline.PipelineError,
        match="comment insight results are required for delivery validation",
    ):
        pipeline.validate_pipeline_inputs(
            "unused-collection",
            require_comment_insights=True,
        )


def test_final_delivery_gate_rejects_business_draft_without_results():
    with pytest.raises(
        pipeline.PipelineError,
        match="business insight results are required for final delivery",
    ):
        pipeline.run_pipeline(
            "unused-collection",
            "unused-output",
            with_taxonomy_prompt=True,
            classification_results_path="unused-results.json",
            with_business_insights=True,
            require_delivery_ready=True,
        )


def test_final_delivery_gate_rejects_taxonomy_draft_without_results():
    with pytest.raises(
        pipeline.PipelineError,
        match="classification results are required for final delivery",
    ):
        pipeline.run_pipeline(
            "unused-collection",
            "unused-output",
            with_taxonomy_prompt=True,
            require_delivery_ready=True,
        )


def test_final_delivery_gate_always_requires_classification_results():
    with pytest.raises(
        pipeline.PipelineError,
        match="classification results are required for final delivery",
    ):
        pipeline.run_pipeline(
            "unused-collection",
            "unused-output",
            require_delivery_ready=True,
        )


def test_stop_reason_safe_label():
    summary = pipeline._delivery_summary(
        {
            "meta": {"stop_reason": "remote-secret-text"},
            "sample_boundary": {},
        },
        task_status="PARTIAL",
    )
    assert summary["stop_reason"] == "INVALID"
    assert "remote-secret-text" not in str(summary)


def test_optional_artifact_co_occurrence():
    actual = workspace.ANALYSIS_REQUIRED_ARTIFACTS | {
        "taxonomy-result-template.json"
    }
    artifacts = {relative: b"" for relative in actual}
    with pytest.raises(
        pipeline.PipelineError,
        match=r"taxonomy-result-template\.json requires taxonomy-prompt\.md",
    ):
        pipeline._validate_output_payloads(
            artifacts,
            expected_artifacts=frozenset(actual),
        )


def test_field_coverage_consistent():
    summary = pipeline._delivery_summary(
        {
            "posts": [
                {"metrics": {"views": 10, "likes": None}},
                {"metrics": {"views": None, "likes": 0}},
            ],
            "sample_boundary": {
                "field_coverage": {"views": 1.0, "likes": 1.0},
            },
        },
        task_status="COMPLETED",
    )

    assert summary["field_coverage"] == {
        "views": 0.5,
        "likes": 0.5,
        "comments": 0.0,
        "favorites": 0.0,
        "shares": 0.0,
        "coins": 0.0,
        "danmaku": 0.0,
    }


def test_partial_model_workspace_is_not_delivery_ready():
    summary = pipeline._delivery_summary(
        {
            "meta": {},
            "sample_boundary": {},
            "classification_status": "completed",
            "business_insight_required": True,
            "business_insight_status": "pending-model",
        },
        task_status="PARTIAL",
    )

    assert summary["delivery_ready"] is False
    assert "不得作为最终策略报告交付" in pipeline._final_response(summary)


def test_deterministic_analysis_is_a_delivery_ready_light_report():
    summary = pipeline._delivery_summary(
        {
            "meta": {},
            "sample_boundary": {"valid": 12},
            "classification_status": "pending-model",
            "business_insight_required": False,
            "comment_insight_required": False,
        },
        task_status="PARTIAL",
    )

    assert summary["delivery_kind"] == "light"
    assert summary["delivery_ready"] is True
    assert summary["strategy_ready"] is False
    assert "不得作为最终策略报告交付" not in pipeline._final_response(summary)


def test_evidence_only_cli_delivers_a_sealed_zero_post_result(tmp_path):
    collection = _sealed_zero_post_collection(tmp_path)
    output = tmp_path / "evidence-delivery"

    completed = subprocess.run(
        [
            sys.executable,
            pipeline.__file__,
            "--input",
            str(collection),
            "--output",
            str(output),
            "--evidence-only",
        ],
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(
        (output / "delivery-summary.json").read_text(encoding="utf-8")
    )
    response = (output / "final-response.md").read_text(encoding="utf-8")
    assert summary["delivery_kind"] == "evidence_only"
    assert summary["delivery_ready"] is True
    assert summary["strategy_ready"] is False
    assert summary["task_status"] == "PARTIAL"
    assert summary["stop_reason"] == "PARSER_FAILED"
    assert summary["sample"]["collected"] == 0
    assert "未生成账号内容策略结论" in response
    assert "公开页面快照，不代表账号后台真实曝光和转化" in response
    assert (output / ".complete").is_file()
