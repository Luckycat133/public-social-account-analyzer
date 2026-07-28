"""Focused contracts for pipeline guards and delivery sanitization."""

from __future__ import annotations

import pytest

import immutable_workspace as workspace
import run_pipeline as pipeline


def test_classification_requires_tax_prompt():
    with pytest.raises(
        pipeline.PipelineError,
        match="classification-results requires --with-llm-tax",
    ):
        pipeline.validate_pipeline_inputs(
            "unused-collection",
            classification_results_path="unused-results.json",
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
