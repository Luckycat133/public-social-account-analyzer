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

