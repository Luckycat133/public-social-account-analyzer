#!/usr/bin/env python3
"""Immutable, zero-dependency derived-analysis pipeline."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from analyze import AnalysisResult, analyze_in_memory
from immutable_workspace import (
    ANALYSIS_ARTIFACTS,
    ANALYSIS_OPTIONAL_ARTIFACTS,
    ANALYSIS_REQUIRED_ARTIFACTS,
    DEFAULT_MAX_ARTIFACT_BYTES,
    FORMAT,
    ImmutableWorkspace,
    VerifiedWorkspaceReader,
    WorkspaceCommitIndeterminate,
    WorkspaceError,
    WorkspaceExistsError,
    preflight_workspace_target,
    reject_workspace_overlap,
)
from normalize import NormalizationResult, normalize_in_memory
from render_report import RenderResult, render_in_memory
from task_contract import (
    TaskContractError,
    new_task_id,
    validate_analysis_goal,
)


COLLECTION_ARTIFACTS = frozenset(
    {
        "source/profile.json",
        "source/posts.jsonl",
        "source/comments.jsonl",
        "source/index-evidence.json",
        "normalized-posts.csv",
        "task.json",
        "collection-report.md",
    }
)
COLLECTION_REQUIRED_ARTIFACTS = frozenset(
    {"source/profile.json", "source/posts.jsonl", "task.json"}
)
COLLECTION_OPTIONAL_EVIDENCE = {
    "source/comments.jsonl": "source/comments.jsonl",
    "source/index-evidence.json": "source/index-evidence.json",
}


class PipelineError(RuntimeError):
    """A pre-commit phase failed; no analysis workspace was published."""


@dataclass(frozen=True)
class PipelineResult:
    workspace: str
    commit_sha256: str
    task_status: str
    phase_results: dict[str, str]


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"{label} must be a JSON object")
    return value


def _classification_json(payload: bytes) -> list[dict[str, Any]]:
    def reject_constant(value: str):
        raise ValueError(f"non-standard numeric constant {value}")

    try:
        value = json.loads(
            payload.decode("utf-8"), parse_constant=reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PipelineError(
            "classification results are not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, list):
        raise PipelineError("classification results must be a JSON array")
    return value


def _read_classification_results(path: str) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        with open(path, "rb") as handle:
            payload = handle.read(DEFAULT_MAX_ARTIFACT_BYTES + 1)
    except (OSError, TypeError, ValueError) as exc:
        raise PipelineError("classification results cannot be read") from exc
    if len(payload) > DEFAULT_MAX_ARTIFACT_BYTES:
        raise PipelineError("classification results are too large")
    return payload, _classification_json(payload)


def _validate_jsonl(payload: bytes, label: str) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PipelineError(f"{label} is not UTF-8") from exc
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"{label} line {lineno} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise PipelineError(f"{label} line {lineno} must be an object")


def _json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PipelineError("pipeline JSON output is invalid") from exc


def _phase(name: str, function: Callable, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except PipelineError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PipelineError(f"{name} failed: {exc}") from exc


def _normalization_status(result: NormalizationResult) -> str:
    coverage = result.coverage
    lossless = (
        coverage.get("parse_errors") == 0
        and coverage.get("duplicate_count") == 0
        and coverage.get("input_line_count") == coverage.get("raw_count")
        and coverage.get("raw_count") == coverage.get("post_count")
        and coverage.get("post_count") == coverage.get("valid_count")
        and not coverage.get("errors")
    )
    return "COMPLETED" if lossless else "PARTIAL"


def _analysis_status(result: AnalysisResult) -> str:
    status = result.analysis.get("classification_status")
    return "COMPLETED" if status not in {None, "pending-model"} else "PARTIAL"


def _validate_output_payloads(
    artifacts: dict[str, bytes], *, expected_artifacts: frozenset[str]
) -> None:
    actual = frozenset(artifacts)
    if actual != expected_artifacts:
        raise PipelineError("analysis artifact inventory is invalid")
    if not ANALYSIS_REQUIRED_ARTIFACTS.issubset(actual):
        raise PipelineError("analysis artifact inventory is incomplete")
    if not actual.issubset(ANALYSIS_ARTIFACTS):
        raise PipelineError("analysis artifact inventory is not allowlisted")

    for relative in (
        "source/profile.json",
        "source/collection-task.json",
        "source/collection-provenance.json",
        "normalized-coverage.json",
        "analysis.json",
        "task.json",
    ):
        _json_object(artifacts[relative], relative)
    _validate_jsonl(artifacts["source/posts.jsonl"], "source/posts.jsonl")
    if "source/comments.jsonl" in artifacts:
        _validate_jsonl(
            artifacts["source/comments.jsonl"], "source/comments.jsonl"
        )
    if "source/index-evidence.json" in artifacts:
        _json_object(
            artifacts["source/index-evidence.json"],
            "source/index-evidence.json",
        )
    if "source/classification-results.json" in artifacts:
        _classification_json(artifacts["source/classification-results.json"])

    try:
        csv_rows = list(
            csv.DictReader(
                io.StringIO(artifacts["normalized-posts.csv"].decode("utf-8"))
            )
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PipelineError("normalized-posts.csv is invalid") from exc
    analysis = _json_object(artifacts["analysis.json"], "analysis.json")
    valid = (analysis.get("sample_boundary") or {}).get("valid")
    if not csv_rows or not isinstance(valid, int) or valid < 1:
        raise PipelineError("analysis has no analyzable rows")
    for relative in (
        "account-analysis-report.md",
        "dashboard.html",
        "pipeline-report.md",
    ):
        try:
            text = artifacts[relative].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PipelineError(f"{relative} is not UTF-8") from exc
        if not text.strip():
            raise PipelineError(f"{relative} is empty")


def _pipeline_report(
    *,
    task_status: str,
    partial_reasons: list[str],
    phase_results: dict[str, str],
    source_digest: str,
    normalization: NormalizationResult,
) -> str:
    lines = [
        "# Derived analysis pipeline report",
        "",
        f"- task_status: {task_status}",
        "- partial_reasons: "
        + (", ".join(partial_reasons) if partial_reasons else "none"),
        f"- collection_commit_sha256: {source_digest}",
        f"- normalized_rows: {normalization.coverage['post_count']}",
        f"- analyzable_rows: {normalization.coverage['valid_count']}",
        "",
        "## Phase results",
        "",
    ]
    lines.extend(f"- {name}: {status}" for name, status in phase_results.items())
    return "\n".join(lines) + "\n"


def _load_default_template() -> str:
    path = Path(__file__).resolve().parent.parent / "assets" / "report-template.html"
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipelineError("report template cannot be read") from exc
    if not template:
        raise PipelineError("report template is empty")
    return template


def run_pipeline(
    collection_dir: str,
    output_dir: str,
    *,
    template_text: str | None = None,
    with_taxonomy_prompt: bool = False,
    classification_results_path: str | None = None,
) -> PipelineResult:
    """Verify a sealed collection and commit a separate derived workspace."""
    output = preflight_workspace_target(output_dir)
    reject_workspace_overlap(collection_dir, output)
    if template_text is None:
        template_text = _load_default_template()
    if not isinstance(template_text, str) or not template_text:
        raise PipelineError("report template is missing or empty")
    classification_payload: bytes | None = None
    classification_results: list[dict[str, Any]] | None = None
    if classification_results_path is not None:
        classification_payload, classification_results = (
            _read_classification_results(classification_results_path)
        )

    try:
        reader_context = VerifiedWorkspaceReader.open(
            collection_dir, allowed_artifacts=COLLECTION_ARTIFACTS
        )
    except WorkspaceError as exc:
        raise PipelineError(f"collection verification failed: {exc}") from exc

    with reader_context as reader:
        manifested = {
            item["path"] for item in reader.manifest.get("artifacts", [])
        }
        missing = COLLECTION_REQUIRED_ARTIFACTS - manifested
        if missing:
            raise PipelineError(
                "collection is missing required input: " + ", ".join(sorted(missing))
            )

        reads = {
            relative: reader.read(relative)
            for relative in sorted(COLLECTION_REQUIRED_ARTIFACTS)
        }
        for relative in COLLECTION_OPTIONAL_EVIDENCE:
            if relative in manifested:
                reads[relative] = reader.read(relative)
        if any(
            artifact.source_digest != reader.source_digest
            or artifact.source_format != FORMAT
            for artifact in reads.values()
        ):
            raise PipelineError("collection reads do not share one commit digest")

        profile_payload = reads["source/profile.json"].payload
        posts_payload = reads["source/posts.jsonl"].payload
        task_payload = reads["task.json"].payload
        assert profile_payload is not None
        assert posts_payload is not None
        assert task_payload is not None
        profile = _json_object(profile_payload, "source/profile.json")
        source_task = _json_object(task_payload, "task.json")
        source_task_id = source_task.get("task_id")
        if not isinstance(source_task_id, str) or not source_task_id:
            raise PipelineError("collection task_id is missing")
        upstream_status = source_task.get("task_status")
        if upstream_status not in {"COMPLETED", "PARTIAL"}:
            raise PipelineError("collection task_status is not analyzable")
        platform = profile.get("platform") or source_task.get("platform")
        if not isinstance(platform, str) or not platform:
            raise PipelineError("collection platform is missing")
        try:
            analysis_goal = validate_analysis_goal(
                source_task.get("analysis_goal")
            )
            derived_task_id = new_task_id(platform)
        except TaskContractError as exc:
            raise PipelineError(f"collection task contract is invalid: {exc}") from exc

        for relative in COLLECTION_OPTIONAL_EVIDENCE:
            artifact = reads.get(relative)
            if artifact is None or artifact.payload is None:
                continue
            if relative.endswith(".jsonl"):
                _validate_jsonl(artifact.payload, relative)
            else:
                _json_object(artifact.payload, relative)

        normalization = _phase(
            "NORMALIZE", normalize_in_memory, profile, posts_payload
        )
        if normalization.coverage.get("valid_count", 0) < 1:
            raise PipelineError("NORMALIZE failed: no analyzable rows")
        normalization_status = _normalization_status(normalization)

        analysis_params = dict(source_task)
        analysis_params["task_id"] = derived_task_id
        analysis_params["analysis_goal"] = analysis_goal
        analysis = _phase(
            "ANALYZE",
            analyze_in_memory,
            profile,
            normalization.rows,
            analysis_params,
            classification_results=classification_results,
            with_taxonomy_prompt=with_taxonomy_prompt,
        )
        if (analysis.analysis.get("sample_boundary") or {}).get("valid", 0) < 1:
            raise PipelineError("ANALYZE failed: no analyzable rows")
        analysis_status = _analysis_status(analysis)

        partial_reasons: list[str] = []
        if upstream_status != "COMPLETED":
            partial_reasons.append("UPSTREAM_COLLECTION_PARTIAL")
        if normalization_status != "COMPLETED":
            partial_reasons.append("NORMALIZATION_PARTIAL")
        if analysis_status != "COMPLETED":
            if analysis.analysis.get("classification_status") == "pending-model":
                partial_reasons.append("PENDING_CLASSIFICATION")
            else:
                partial_reasons.append("ANALYSIS_PARTIAL")
        task_status = "PARTIAL" if partial_reasons else "COMPLETED"
        analysis_payload = dict(analysis.analysis)
        analysis_payload["meta"] = {
            **(analysis.analysis.get("meta") or {}),
            "task_status": task_status,
            "partial_reasons": list(partial_reasons),
        }
        analysis = AnalysisResult(
            analysis=analysis_payload,
            taxonomy_prompt=analysis.taxonomy_prompt,
        )

        rendered = _phase(
            "RENDER",
            render_in_memory,
            profile=profile,
            posts_csv=normalization.rows,
            analysis=analysis.analysis,
            template=template_text,
        )
        assert isinstance(rendered, RenderResult)

        phase_results = {
            "collection_input": "VERIFIED",
            "normalization": normalization_status,
            "analysis": analysis_status,
            "render": "COMPLETED",
            "validation": "COMPLETED",
        }
        provenance = {
            "source_format": reader.source_format,
            "source_task_id": source_task_id,
            "collection_commit_sha256": reader.source_digest,
            "source_manifest_artifacts": [
                {
                    "path": item["path"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                }
                for item in reader.manifest["artifacts"]
            ],
        }
        task = {
            "task_id": derived_task_id,
            "platform": platform,
            "analysis_goal": analysis_goal,
            "task_status": task_status,
            "partial_reasons": partial_reasons,
            "source_task_id": source_task_id,
            "collection_commit_sha256": reader.source_digest,
            "phase_results": phase_results,
        }

        artifacts: dict[str, bytes] = {
            "source/profile.json": profile_payload,
            "source/posts.jsonl": posts_payload,
            "source/collection-task.json": task_payload,
            "source/collection-provenance.json": _json_bytes(provenance),
            "normalized-posts.csv": normalization.csv_text.encode("utf-8"),
            "normalized-coverage.json": _json_bytes(normalization.coverage),
            "analysis.json": _json_bytes(analysis.analysis),
            "account-analysis-report.md": rendered.markdown.encode("utf-8"),
            "dashboard.html": rendered.html.encode("utf-8"),
            "task.json": _json_bytes(task),
            "pipeline-report.md": _pipeline_report(
                task_status=task_status,
                partial_reasons=partial_reasons,
                phase_results=phase_results,
                source_digest=reader.source_digest,
                normalization=normalization,
            ).encode("utf-8"),
        }
        for source_relative, output_relative in COLLECTION_OPTIONAL_EVIDENCE.items():
            artifact = reads.get(source_relative)
            if artifact is not None and artifact.payload is not None:
                artifacts[output_relative] = artifact.payload
        if analysis.taxonomy_prompt is not None:
            artifacts["taxonomy-prompt.md"] = analysis.taxonomy_prompt.encode(
                "utf-8"
            )
        if classification_payload is not None:
            artifacts["source/classification-results.json"] = (
                classification_payload
            )

        expected_artifacts = ANALYSIS_REQUIRED_ARTIFACTS | frozenset(
            relative
            for relative in ANALYSIS_OPTIONAL_ARTIFACTS
            if relative in artifacts
        )
        _phase(
            "VALIDATE",
            _validate_output_payloads,
            artifacts,
            expected_artifacts=expected_artifacts,
        )
        reader.verify_unchanged()

        reservation = ImmutableWorkspace.reserve(
            output, allowed_artifacts=ANALYSIS_ARTIFACTS
        )
        try:
            for relative in sorted(artifacts):
                with reservation.open_binary(relative) as handle:
                    handle.write(artifacts[relative])
            reader.verify_unchanged()
            commit_sha256 = reservation.commit()
        finally:
            reservation.close()

    return PipelineResult(
        workspace=os.path.abspath(output),
        commit_sha256=commit_sha256,
        task_status=task_status,
        phase_results=phase_results,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从已提交采集工作区创建独立、不可变的分析工作区"
    )
    parser.add_argument("--input", required=True, help="已提交的采集工作区")
    parser.add_argument("--output", required=True, help="不存在的分析输出目录")
    parser.add_argument("--template", default=None, help="可选 HTML 模板")
    parser.add_argument(
        "--with-llm-tax",
        action="store_true",
        help="生成 taxonomy-prompt.md（不调用模型）",
    )
    parser.add_argument(
        "--classification-results",
        default=None,
        help="可选的完整语义分类 JSON；验证后原字节纳入分析工作区",
    )
    args = parser.parse_args(argv)
    try:
        template = (
            Path(args.template).read_text(encoding="utf-8")
            if args.template
            else None
        )
        result = run_pipeline(
            args.input,
            args.output,
            template_text=template,
            with_taxonomy_prompt=args.with_llm_tax,
            classification_results_path=args.classification_results,
        )
    except WorkspaceCommitIndeterminate:
        print("[INDETERMINATE] analysis commit could not be confirmed", file=sys.stderr)
        return 4
    except (PipelineError, WorkspaceError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    print(
        f"analysis workspace committed: {result.workspace} "
        f"task_status={result.task_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
