#!/usr/bin/env python3
"""Prepare and verify external human truth for PRD AC-03 and AC-06.

This tool deliberately separates three claims:

* immutable-workspace/provenance integrity;
* source-to-normalized pipeline consistency;
* accuracy against values independently observed by a human on public pages.

Only the last claim can pass AC-03.  ``prepare`` creates an empty, deterministic
review form outside both sealed workspaces; ``verify`` scores a completed form.
The tool never opens a network connection and never modifies either workspace.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "skill" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from csv_contract import deserialize_csv_row  # noqa: E402
from collectors.url_policy import canonical_item_url  # noqa: E402
from immutable_workspace import (  # noqa: E402
    ANALYSIS_ARTIFACTS,
    FORMAT,
    VerifiedWorkspaceReader,
    WorkspaceError,
    reject_workspace_overlap,
)
from normalize import CSV_COLUMNS, normalize_in_memory  # noqa: E402


TRUTH_SCHEMA = "public-social-account-analyzer/external-truth-v1"
SELECTION_METHOD = "commit-sha256-v1"
AC03_TARGET = 0.95
MIN_POST_SAMPLE = 10
MIN_MANUAL_INSIGHTS = 3
MAX_TRUTH_BYTES = 4 * 1024 * 1024

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
COLLECTION_REQUIRED = frozenset(
    {"source/profile.json", "source/posts.jsonl", "task.json"}
)
ANALYSIS_REQUIRED = frozenset(
    {
        "source/profile.json",
        "source/posts.jsonl",
        "source/collection-task.json",
        "source/collection-provenance.json",
        "normalized-posts.csv",
        "normalized-coverage.json",
        "analysis.json",
        "account-analysis-report.md",
        "dashboard.html",
        "task.json",
        "pipeline-report.md",
    }
)
PROFILE_FIELDS = (
    "account_id",
    "account_name",
    "bio",
    "verified",
    "followers",
    "post_count",
)
DOUYIN_PROFILE_FIELDS = PROFILE_FIELDS + ("platform_metrics.total_likes",)
POST_CORE_FIELDS = (
    "post_id",
    "post_url",
    "title",
    "text",
    "published_at",
    "content_type",
)
POST_SHARED_METRIC_FIELDS = (
    "views",
    "likes",
    "comments",
)
PLATFORM_POST_FIELDS = {
    "bilibili": POST_CORE_FIELDS
    + (
        "duration_seconds",
        "hashtags",
    )
    + POST_SHARED_METRIC_FIELDS
    + (
        "favorites",
        "shares",
        "coins",
        "danmaku",
    ),
    "douyin": POST_CORE_FIELDS
    + ("duration_seconds", "hashtags")
    + POST_SHARED_METRIC_FIELDS
    + ("favorites", "shares"),
    "weibo": POST_CORE_FIELDS
    + ("hashtags",)
    + POST_SHARED_METRIC_FIELDS
    + ("shares",),
}
OBSERVATION_FIELDS = frozenset({"state", "page_text", "value"})
OBSERVATION_STATES = frozenset({"visible", "not_visible"})
_MARKDOWN_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKDOWN_FENCED_CODE = re.compile(
    r"(?:^|\n)(?:```|~~~).*?(?:\n(?:```|~~~)(?:\n|$)|\Z)",
    re.DOTALL,
)
_MARKDOWN_INLINE_LINK = re.compile(
    r"(?<!!)\[[^\]\r\n]*\]\(\s*(https?://[^\s)]+)\s*\)"
)


class AcceptanceError(ValueError):
    """The workspaces or truth artifact cannot support an acceptance score."""


@dataclass(frozen=True)
class BoundSnapshot:
    collection_digest: str
    analysis_digest: str
    platform: str
    profile: dict[str, Any]
    source_posts: list[dict[str, Any]]
    normalized_posts: list[dict[str, Any]]
    analysis: dict[str, Any]
    collection_task: dict[str, Any]
    analysis_task: dict[str, Any]
    markdown: str
    html: str


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard numeric constant {value}")


def _strict_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"), parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceError(f"{label} is not strict UTF-8 JSON") from exc


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    value = _strict_json(payload, label)
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label} must be a JSON object")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AcceptanceError(f"{label} is not UTF-8") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = _strict_json(line.encode("utf-8"), f"{label}:{line_number}")
        if not isinstance(value, dict):
            raise AcceptanceError(f"{label}:{line_number} must be an object")
        rows.append(value)
    return rows


def _csv_rows(payload: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
        raw_rows = list(csv.DictReader(io.StringIO(text)))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise AcceptanceError(f"{label} is not valid UTF-8 CSV") from exc
    try:
        return [deserialize_csv_row(row) for row in raw_rows]
    except (TypeError, ValueError) as exc:
        raise AcceptanceError(f"{label} contains an invalid row") from exc


def _payload(reader: VerifiedWorkspaceReader, relative: str) -> bytes:
    artifact = reader.read(relative)
    if artifact.payload is None:
        raise AcceptanceError(f"{relative} is missing")
    return artifact.payload


def _manifested(reader: VerifiedWorkspaceReader) -> set[str]:
    return {item["path"] for item in reader.manifest.get("artifacts", [])}


@contextmanager
def _bound_snapshot(
    collection_dir: Path | str, analysis_dir: Path | str
) -> Iterator[BoundSnapshot]:
    stack = ExitStack()
    try:
        collection = stack.enter_context(
            VerifiedWorkspaceReader.open(
                str(collection_dir), allowed_artifacts=COLLECTION_ARTIFACTS
            )
        )
        analysis_reader = stack.enter_context(
            VerifiedWorkspaceReader.open(
                str(analysis_dir), allowed_artifacts=ANALYSIS_ARTIFACTS
            )
        )
    except WorkspaceError as exc:
        stack.close()
        raise AcceptanceError(f"workspace verification failed: {exc}") from exc

    with stack:
        if not COLLECTION_REQUIRED.issubset(_manifested(collection)):
            raise AcceptanceError("collection workspace is incomplete")
        if not ANALYSIS_REQUIRED.issubset(_manifested(analysis_reader)):
            raise AcceptanceError("analysis workspace is incomplete")

        collection_profile = _payload(collection, "source/profile.json")
        collection_posts = _payload(collection, "source/posts.jsonl")
        collection_task = _payload(collection, "task.json")
        if _payload(analysis_reader, "source/profile.json") != collection_profile:
            raise AcceptanceError("analysis profile is not bound to collection")
        if _payload(analysis_reader, "source/posts.jsonl") != collection_posts:
            raise AcceptanceError("analysis posts are not bound to collection")
        if (
            _payload(analysis_reader, "source/collection-task.json")
            != collection_task
        ):
            raise AcceptanceError("analysis task source is not bound to collection")

        provenance = _json_object(
            _payload(analysis_reader, "source/collection-provenance.json"),
            "source/collection-provenance.json",
        )
        source_task = _json_object(collection_task, "collection task.json")
        derived_task = _json_object(
            _payload(analysis_reader, "task.json"), "analysis task.json"
        )
        if not (
            provenance.get("source_format") == FORMAT
            and provenance.get("collection_commit_sha256")
            == collection.source_digest
            and provenance.get("source_task_id") == source_task.get("task_id")
            and derived_task.get("collection_commit_sha256")
            == collection.source_digest
            and derived_task.get("source_task_id") == source_task.get("task_id")
        ):
            raise AcceptanceError("analysis provenance does not bind collection")
        expected_source_inventory = [
            {
                "path": item["path"],
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in collection.manifest["artifacts"]
        ]
        if provenance.get("source_manifest_artifacts") != expected_source_inventory:
            raise AcceptanceError(
                "analysis provenance manifest inventory does not bind collection"
            )

        profile = _json_object(collection_profile, "source/profile.json")
        platform = profile.get("platform") or source_task.get("platform")
        if not isinstance(platform, str) or platform not in {
            "bilibili",
            "douyin",
            "weibo",
        }:
            raise AcceptanceError("workspace platform is invalid")
        if derived_task.get("platform") != platform:
            raise AcceptanceError("analysis platform does not bind collection")
        source_status = source_task.get("task_status")
        source_is_partial = source_status == "PARTIAL"
        source_stop_reason = source_task.get("stop_reason")
        if not (
            isinstance(source_task.get("task_id"), str)
            and bool(source_task["task_id"])
            and source_status in {"COMPLETED", "PARTIAL"}
            and (
                not source_is_partial
                or (
                    isinstance(source_stop_reason, str)
                    and bool(source_stop_reason)
                )
            )
            and source_task.get("platform") == platform
            and source_task.get("profile_url") == profile.get("profile_url")
        ):
            raise AcceptanceError("collection task is not assessable or coherent")
        phase_results = derived_task.get("phase_results")
        derived_status = derived_task.get("task_status")
        partial_reasons = derived_task.get("partial_reasons")
        phases_are_assessable = (
            isinstance(phase_results, dict)
            and set(phase_results)
            == {
                "collection_input",
                "normalization",
                "analysis",
                "render",
                "validation",
            }
            and phase_results.get("collection_input") == "VERIFIED"
            and phase_results.get("normalization")
            in {"COMPLETED", "PARTIAL"}
            and phase_results.get("analysis") in {"COMPLETED", "PARTIAL"}
            and phase_results.get("render") == "COMPLETED"
            and phase_results.get("validation") == "COMPLETED"
        )
        derived_is_partial = derived_status == "PARTIAL"
        partial_reasons_are_valid = (
            isinstance(partial_reasons, list)
            and all(
                isinstance(reason, str) and bool(reason)
                for reason in partial_reasons
            )
            and len(partial_reasons) == len(set(partial_reasons))
            and (
                (derived_is_partial and bool(partial_reasons))
                or (derived_status == "COMPLETED" and not partial_reasons)
            )
        )
        upstream_status_is_bound = (
            not source_is_partial
            or (
                derived_is_partial
                and isinstance(partial_reasons, list)
                and "UPSTREAM_COLLECTION_PARTIAL" in partial_reasons
            )
        )
        completed_status_is_coherent = (
            derived_status != "COMPLETED"
            or (
                isinstance(phase_results, dict)
                and source_status == "COMPLETED"
                and phase_results.get("normalization") == "COMPLETED"
                and phase_results.get("analysis") == "COMPLETED"
            )
        )
        if not (
            isinstance(derived_task.get("task_id"), str)
            and bool(derived_task["task_id"])
            and derived_status in {"COMPLETED", "PARTIAL"}
            and phases_are_assessable
            and partial_reasons_are_valid
            and upstream_status_is_bound
            and completed_status_is_coherent
        ):
            raise AcceptanceError("analysis task is not completed or coherent")

        analysis_payload = _json_object(
            _payload(analysis_reader, "analysis.json"), "analysis.json"
        )
        coverage = analysis_payload.get("evidence_coverage")
        if not isinstance(coverage, dict):
            raise AcceptanceError("analysis evidence coverage is missing")
        selected_count = coverage.get("selected_count")
        complete_count = coverage.get("complete_count")
        missing_count = coverage.get("missing_count")
        missing_ids = coverage.get("missing_post_ids")
        rate = coverage.get("rate")
        coverage_is_complete = (
            type(selected_count) is int
            and type(complete_count) is int
            and type(missing_count) is int
            and selected_count >= 0
            and complete_count == selected_count
            and missing_count == 0
            and isinstance(missing_ids, list)
            and missing_ids == []
            and coverage.get("status") == "COMPLETE"
            and (
                (selected_count == 0 and rate is None)
                or (selected_count > 0 and rate == 1.0)
            )
        )
        raw_core_insights = analysis_payload.get("core_insights")
        core_evidence_count = (
            sum(
                len(item.get("evidence", []))
                for item in raw_core_insights
                if isinstance(item, dict)
                and isinstance(item.get("evidence"), list)
            )
            if isinstance(raw_core_insights, list)
            else -1
        )
        if not coverage_is_complete or selected_count != core_evidence_count:
            raise AcceptanceError("analysis evidence coverage is incoherent")

        try:
            markdown = _payload(
                analysis_reader, "account-analysis-report.md"
            ).decode("utf-8")
            html = _payload(analysis_reader, "dashboard.html").decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AcceptanceError("rendered report is not UTF-8") from exc

        snapshot = BoundSnapshot(
            collection_digest=collection.source_digest,
            analysis_digest=analysis_reader.source_digest,
            platform=platform,
            profile=profile,
            source_posts=_jsonl(collection_posts, "source/posts.jsonl"),
            normalized_posts=_csv_rows(
                _payload(analysis_reader, "normalized-posts.csv"),
                "normalized-posts.csv",
            ),
            analysis=analysis_payload,
            collection_task=source_task,
            analysis_task=derived_task,
            markdown=markdown,
            html=html,
        )
        yield snapshot
        try:
            collection.verify_unchanged()
            analysis_reader.verify_unchanged()
        except WorkspaceError as exc:
            raise AcceptanceError("workspace changed during acceptance") from exc


def _profile_fields(platform: str) -> tuple[str, ...]:
    return DOUYIN_PROFILE_FIELDS if platform == "douyin" else PROFILE_FIELDS


def _post_fields(platform: str) -> tuple[str, ...]:
    try:
        return PLATFORM_POST_FIELDS[platform]
    except KeyError as exc:
        raise AcceptanceError("workspace platform is unsupported") from exc


def _blank_observation() -> dict[str, Any]:
    return {"state": None, "page_text": None, "value": None}


def _eligible_posts(snapshot: BoundSnapshot) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in snapshot.normalized_posts:
        post_id = row.get("post_id")
        if (
            not isinstance(post_id, str)
            or not post_id
            or post_id in seen
            or row.get("collection_status") != "SUCCESS"
        ):
            continue
        canonical_url = canonical_item_url(
            snapshot.platform, row.get("post_url"), post_id
        )
        if canonical_url is None:
            continue
        seen.add(post_id)
        eligible.append({**row, "post_url": canonical_url})
    return eligible


def _selection_key(snapshot: BoundSnapshot, post_id: str) -> str:
    material = (
        snapshot.collection_digest
        + "\0"
        + snapshot.platform
        + "\0"
        + post_id
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _core_insights(snapshot: BoundSnapshot) -> list[dict[str, Any]]:
    value = snapshot.analysis.get("core_insights")
    if value is None:
        value = []
    if not isinstance(value, list):
        raise AcceptanceError("core insights must be a list")
    insights = list(value)
    business = snapshot.analysis.get("business_insights")
    if (
        snapshot.analysis.get("business_insight_status") == "completed"
        and isinstance(business, dict)
    ):
        positioning = business.get("account_positioning")
        if not isinstance(positioning, dict):
            raise AcceptanceError("completed business positioning is missing")
        for field in (
            "target_audience",
            "content_domain",
            "value_proposition",
            "persona_expression",
            "follow_reason",
        ):
            claim = positioning.get(field)
            if not (
                isinstance(claim, dict)
                and isinstance(claim.get("statement"), str)
                and bool(claim["statement"])
                and isinstance(claim.get("evidence"), list)
            ):
                raise AcceptanceError(
                    f"completed business positioning {field} is invalid"
                )
            insights.append(
                {
                    "id": f"positioning-{field}",
                    "statement": claim["statement"],
                    "evidence": [
                        {
                            "post_id": evidence.get("post_id"),
                            "url": evidence.get("url"),
                        }
                        for evidence in claim["evidence"]
                        if isinstance(evidence, dict)
                    ],
                }
            )
    seen: set[str] = set()
    for index, insight in enumerate(insights, start=1):
        if not (
            isinstance(insight, dict)
            and isinstance(insight.get("id"), str)
            and bool(insight["id"])
            and isinstance(insight.get("statement"), str)
            and bool(insight["statement"])
            and isinstance(insight.get("evidence"), list)
        ):
            raise AcceptanceError(f"core insight {index} is invalid")
        if insight["id"] in seen:
            raise AcceptanceError("core insight IDs must be unique")
        seen.add(insight["id"])
    return insights


def prepare_truth(
    collection_dir: Path | str,
    analysis_dir: Path | str,
    *,
    sample_size: int = MIN_POST_SAMPLE,
) -> dict[str, Any]:
    """Create an empty deterministic review form; never copy expected values."""
    if (
        isinstance(sample_size, bool)
        or not isinstance(sample_size, int)
        or sample_size < MIN_POST_SAMPLE
        or sample_size > 100
    ):
        raise AcceptanceError("sample size must be an integer from 10 to 100")

    with _bound_snapshot(collection_dir, analysis_dir) as snapshot:
        eligible = sorted(
            _eligible_posts(snapshot),
            key=lambda row: _selection_key(snapshot, row["post_id"]),
        )
        if len(eligible) < sample_size:
            raise AcceptanceError(
                f"fewer than {sample_size} eligible SUCCESS posts"
            )
        selected = eligible[:sample_size]
        insights: list[dict[str, Any]] = []
        for raw_insight in _core_insights(snapshot):
            if not isinstance(raw_insight, dict):
                continue
            insight_id = raw_insight.get("id")
            statement = raw_insight.get("statement")
            evidence = raw_insight.get("evidence")
            if not (
                isinstance(insight_id, str)
                and insight_id
                and isinstance(statement, str)
                and statement
                and isinstance(evidence, list)
            ):
                continue
            prepared_evidence = []
            for raw_evidence in evidence:
                if not isinstance(raw_evidence, dict):
                    continue
                prepared_evidence.append(
                    {
                        "post_id": raw_evidence.get("post_id"),
                        "url": raw_evidence.get("url"),
                        "opened": None,
                        "owner_matches_profile": None,
                        "content_matches_post": None,
                    }
                )
            insights.append(
                {
                    "insight_id": insight_id,
                    "statement": statement,
                    "statement_verdict": None,
                    "evidence": prepared_evidence,
                    "note": "",
                }
            )

        return {
            "schema": TRUTH_SCHEMA,
            "platform": snapshot.platform,
            "collection_commit_sha256": snapshot.collection_digest,
            "analysis_commit_sha256": snapshot.analysis_digest,
            "reviewer": {"id": None, "reviewed_at": None},
            "selection": {
                "method": SELECTION_METHOD,
                "sample_size": sample_size,
                "post_ids": [row["post_id"] for row in selected],
            },
            "profile": {
                "page_url": snapshot.profile.get("profile_url"),
                "observed_at": None,
                "fields": {
                    field: _blank_observation()
                    for field in _profile_fields(snapshot.platform)
                },
            },
            "posts": [
                {
                    "post_id": row["post_id"],
                    "page_url": row["post_url"],
                    "observed_at": None,
                    "fields": {
                        field: _blank_observation()
                        for field in _post_fields(snapshot.platform)
                    },
                }
                for row in selected
            ],
            "insights": insights,
        }


def _timezone_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _safe_reviewer(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and not any(ord(char) < 32 for char in value)
    )


def _nested_value(value: dict[str, Any], dotted_field: str) -> Any:
    current: Any = value
    for part in dotted_field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _visibility(value: dict[str, Any], dotted_field: str) -> Any:
    visibility = value.get("field_visibility")
    if not isinstance(visibility, dict):
        return None
    return visibility.get(dotted_field.split(".")[-1])


def _validate_observation(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != OBSERVATION_FIELDS:
        raise AcceptanceError(f"{label} observation inventory is invalid")
    state = value.get("state")
    if state not in OBSERVATION_STATES:
        raise AcceptanceError(f"{label} observation is incomplete")
    if state == "visible":
        page_text = value.get("page_text")
        if not isinstance(page_text, str) or not page_text.strip():
            raise AcceptanceError(f"{label} visible page_text is missing")
        if value.get("value") is None:
            raise AcceptanceError(f"{label} visible value must not be null")
    elif value.get("page_text") is not None or value.get("value") is not None:
        raise AcceptanceError(f"{label} not-visible value must be null")
    try:
        json.dumps(value.get("value"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AcceptanceError(f"{label} value is not strict JSON") from exc
    return value


def _validate_typed_value(
    *, scope: str, platform: str, field: str, value: Any
) -> None:
    def nonnegative_integer(candidate: Any) -> bool:
        return (
            type(candidate) is int
            and candidate >= 0
        )

    string_fields = {
        "account_id",
        "account_name",
        "bio",
        "post_id",
        "post_url",
        "title",
        "text",
        "published_at",
        "content_type",
    }
    integer_fields = {
        "followers",
        "post_count",
        "platform_metrics.total_likes",
        "views",
        "likes",
        "comments",
        "favorites",
        "shares",
        "coins",
        "danmaku",
    }
    valid = False
    if field in string_fields:
        valid = isinstance(value, str)
    elif field in integer_fields:
        valid = nonnegative_integer(value)
    elif field == "verified":
        valid = type(value) is bool
    elif field == "duration_seconds":
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        )
    elif field == "hashtags":
        valid = isinstance(value, list) and all(
            isinstance(item, str) for item in value
        )
    if not valid:
        raise AcceptanceError(
            f"{scope}.{field} has an invalid visible value type for {platform}"
        )


def _value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(actual, float) and not math.isfinite(actual):
        return False
    return type(actual) is type(expected) and actual == expected


def _score_observation(
    *,
    actual: Any,
    visibility: Any,
    observation: dict[str, Any],
) -> bool:
    if observation["state"] == "visible":
        return visibility == "visible" and _value_matches(
            actual, observation["value"]
        )
    return actual is None and visibility == "hidden"


def _markdown_link_targets(markdown: str) -> set[str]:
    without_comments = _MARKDOWN_HTML_COMMENT.sub("", markdown)
    without_fences = _MARKDOWN_FENCED_CODE.sub("\n", without_comments)
    without_inline_code = re.sub(r"`[^`\r\n]*`", "", without_fences)
    return set(_MARKDOWN_INLINE_LINK.findall(without_inline_code))


class _AnchorTargetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and isinstance(value, str):
                self.targets.add(value)


def _html_link_targets(html: str) -> set[str]:
    parser = _AnchorTargetParser()
    parser.feed(html)
    parser.close()
    return parser.targets


def _pipeline_integrity(snapshot: BoundSnapshot) -> dict[str, Any]:
    source_payload = b"".join(
        (
            json.dumps(
                row, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode("utf-8")
        for row in snapshot.source_posts
    )
    try:
        expected_rows = normalize_in_memory(
            snapshot.profile, source_payload
        ).rows
    except (TypeError, ValueError) as exc:
        raise AcceptanceError("source posts cannot be normalized") from exc
    mismatches: list[dict[str, Any]] = []
    expected_by_id: dict[str, dict[str, Any]] = {}
    for row in expected_rows:
        post_id = row.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            mismatches.append(
                {"post_id": post_id, "field": "invalid_source_post_id"}
            )
        elif post_id in expected_by_id:
            mismatches.append(
                {"post_id": post_id, "field": "duplicate_source_post_id"}
            )
        else:
            expected_by_id[post_id] = row
    normalized_by_id: dict[str, dict[str, Any]] = {}
    for row in snapshot.normalized_posts:
        post_id = row.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            mismatches.append(
                {"post_id": post_id, "field": "invalid_normalized_post_id"}
            )
        elif post_id in normalized_by_id:
            mismatches.append(
                {
                    "post_id": post_id,
                    "field": "duplicate_normalized_post_id",
                }
            )
        else:
            normalized_by_id[post_id] = row
    for post_id in sorted(set(expected_by_id) | set(normalized_by_id)):
        expected = expected_by_id.get(post_id)
        normalized = normalized_by_id.get(post_id)
        if expected is None or normalized is None:
            mismatches.append({"post_id": post_id, "field": "row_presence"})
            continue
        extra_fields = set(normalized) - set(CSV_COLUMNS) - {"_visibility"}
        for field in sorted(extra_fields):
            mismatches.append(
                {"post_id": post_id, "field": f"unexpected:{field}"}
            )
        for field in CSV_COLUMNS:
            if field not in normalized or not _value_matches(
                normalized.get(field), expected.get(field)
            ):
                mismatches.append({"post_id": post_id, "field": field})
    return {
        "verdict": "PASS" if not mismatches else "FAIL",
        "source_count": len(expected_rows),
        "normalized_count": len(snapshot.normalized_posts),
        "mismatches": mismatches,
    }


def _expected_selection(snapshot: BoundSnapshot, sample_size: int) -> list[str]:
    eligible = sorted(
        _eligible_posts(snapshot),
        key=lambda row: _selection_key(snapshot, row["post_id"]),
    )
    if len(eligible) < sample_size:
        raise AcceptanceError("workspace no longer has the required sample")
    return [row["post_id"] for row in eligible[:sample_size]]


def _validate_truth_header(snapshot: BoundSnapshot, truth: Any) -> int:
    root_fields = {
        "schema",
        "platform",
        "collection_commit_sha256",
        "analysis_commit_sha256",
        "reviewer",
        "selection",
        "profile",
        "posts",
        "insights",
    }
    if not isinstance(truth, dict) or set(truth) != root_fields:
        raise AcceptanceError("truth root inventory is invalid")
    if not (
        truth.get("schema") == TRUTH_SCHEMA
        and truth.get("platform") == snapshot.platform
        and truth.get("collection_commit_sha256")
        == snapshot.collection_digest
        and truth.get("analysis_commit_sha256") == snapshot.analysis_digest
    ):
        raise AcceptanceError("truth is not bound to these workspaces")
    reviewer = truth.get("reviewer")
    if not (
        isinstance(reviewer, dict)
        and set(reviewer) == {"id", "reviewed_at"}
        and _safe_reviewer(reviewer.get("id"))
        and _timezone_timestamp(reviewer.get("reviewed_at"))
    ):
        raise AcceptanceError("truth reviewer metadata is incomplete")
    selection = truth.get("selection")
    if not isinstance(selection, dict) or set(selection) != {
        "method",
        "sample_size",
        "post_ids",
    }:
        raise AcceptanceError("truth selection inventory is invalid")
    sample_size = selection.get("sample_size")
    if (
        isinstance(sample_size, bool)
        or not isinstance(sample_size, int)
        or sample_size < MIN_POST_SAMPLE
        or selection.get("method") != SELECTION_METHOD
        or selection.get("post_ids")
        != _expected_selection(snapshot, sample_size)
    ):
        raise AcceptanceError("truth selection was not deterministically prepared")
    return sample_size


def _score_ac03(
    snapshot: BoundSnapshot, truth: dict[str, Any], sample_size: int
) -> dict[str, Any]:
    profile_truth = truth.get("profile")
    expected_profile_fields = set(_profile_fields(snapshot.platform))
    if not (
        isinstance(profile_truth, dict)
        and set(profile_truth) == {"page_url", "observed_at", "fields"}
        and profile_truth.get("page_url") == snapshot.profile.get("profile_url")
        and _timezone_timestamp(profile_truth.get("observed_at"))
        and isinstance(profile_truth.get("fields"), dict)
        and set(profile_truth["fields"]) == expected_profile_fields
    ):
        raise AcceptanceError("truth profile observation is invalid")

    checks: list[dict[str, Any]] = []
    for field in _profile_fields(snapshot.platform):
        observation = _validate_observation(
            profile_truth["fields"][field], f"profile.{field}"
        )
        if observation["state"] == "visible":
            _validate_typed_value(
                scope="profile",
                platform=snapshot.platform,
                field=field,
                value=observation["value"],
            )
        actual = _nested_value(snapshot.profile, field)
        correct = _score_observation(
            actual=actual,
            visibility=_visibility(snapshot.profile, field),
            observation=observation,
        )
        checks.append(
            {
                "scope": "profile",
                "post_id": None,
                "field": field,
                "actual": actual,
                "expected": observation["value"],
                "correct": correct,
            }
        )

    truth_posts = truth.get("posts")
    if not isinstance(truth_posts, list) or len(truth_posts) != sample_size:
        raise AcceptanceError("truth post observation count is invalid")
    normalized_by_id = {
        row.get("post_id"): row for row in snapshot.normalized_posts
    }
    expected_ids = truth["selection"]["post_ids"]
    if [row.get("post_id") for row in truth_posts if isinstance(row, dict)] != expected_ids:
        raise AcceptanceError("truth post observations do not match selection order")
    for index, truth_post in enumerate(truth_posts, start=1):
        post_id = truth_post.get("post_id")
        actual_post = normalized_by_id.get(post_id)
        canonical_url = (
            canonical_item_url(
                snapshot.platform, actual_post.get("post_url"), post_id
            )
            if isinstance(actual_post, dict)
            else None
        )
        if not (
            set(truth_post)
            == {"post_id", "page_url", "observed_at", "fields"}
            and canonical_url is not None
            and truth_post.get("page_url") == canonical_url
            and _timezone_timestamp(truth_post.get("observed_at"))
            and isinstance(truth_post.get("fields"), dict)
            and set(truth_post["fields"]) == set(_post_fields(snapshot.platform))
        ):
            raise AcceptanceError(f"truth post {index} observation is invalid")
        for field in _post_fields(snapshot.platform):
            observation = _validate_observation(
                truth_post["fields"][field], f"post {post_id}.{field}"
            )
            if observation["state"] == "visible":
                _validate_typed_value(
                    scope="post",
                    platform=snapshot.platform,
                    field=field,
                    value=observation["value"],
                )
            actual = actual_post.get(field)
            correct = _score_observation(
                actual=actual,
                visibility=_visibility(actual_post, field),
                observation=observation,
            )
            checks.append(
                {
                    "scope": "post",
                    "post_id": post_id,
                    "field": field,
                    "actual": actual,
                    "expected": observation["value"],
                    "correct": correct,
                }
            )

    correct_count = sum(item["correct"] for item in checks)
    denominator = len(checks)
    accuracy = round(correct_count / denominator, 6) if denominator else 0.0
    mismatches = [item for item in checks if not item["correct"]]
    field_accuracy = {}
    for field in sorted({item["field"] for item in checks}):
        field_checks = [item for item in checks if item["field"] == field]
        field_correct = sum(item["correct"] for item in field_checks)
        field_accuracy[field] = {
            "required": len(field_checks),
            "correct": field_correct,
            "accuracy": round(field_correct / len(field_checks), 6),
        }
    scope_accuracy = {}
    for scope, output_name in (("profile", "profile"), ("post", "posts")):
        scope_checks = [item for item in checks if item["scope"] == scope]
        scope_correct = sum(item["correct"] for item in scope_checks)
        scope_accuracy[output_name] = {
            "required": len(scope_checks),
            "correct": scope_correct,
            "accuracy": (
                round(scope_correct / len(scope_checks), 6)
                if scope_checks
                else 0.0
            ),
        }
    return {
        "verdict": "PASS" if accuracy >= AC03_TARGET else "FAIL",
        "target": AC03_TARGET,
        "sample_size": sample_size,
        "required_observations": denominator,
        "correct_observations": correct_count,
        "accuracy": accuracy,
        "scope_accuracy": scope_accuracy,
        "field_accuracy": field_accuracy,
        "mismatches": mismatches,
    }


def _score_ac06(snapshot: BoundSnapshot, truth: dict[str, Any]) -> dict[str, Any]:
    emitted = _core_insights(snapshot)
    truth_insights = truth.get("insights")
    if not isinstance(truth_insights, list):
        raise AcceptanceError("truth insights must be a list")
    emitted_ids = [
        item.get("id") if isinstance(item, dict) else None for item in emitted
    ]
    truth_ids = [
        item.get("insight_id") if isinstance(item, dict) else None
        for item in truth_insights
    ]
    if truth_ids != emitted_ids:
        raise AcceptanceError("truth insights do not match emitted insights")

    normalized_urls = {}
    for row in snapshot.normalized_posts:
        post_id = row.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            continue
        if post_id in normalized_urls:
            raise AcceptanceError("normalized post IDs must be unique")
        normalized_urls[post_id] = canonical_item_url(
            snapshot.platform, row.get("post_url"), post_id
        )
    markdown_links = _markdown_link_targets(snapshot.markdown)
    html_links = _html_link_targets(snapshot.html)
    covered_insights = 0
    valid_evidence = 0
    total_evidence = 0
    failures: list[dict[str, Any]] = []
    for emitted_insight, truth_insight in zip(emitted, truth_insights):
        if not (
            isinstance(emitted_insight, dict)
            and isinstance(truth_insight, dict)
            and set(truth_insight)
            == {
                "insight_id",
                "statement",
                "statement_verdict",
                "evidence",
                "note",
            }
            and truth_insight.get("statement")
            == emitted_insight.get("statement")
            and truth_insight.get("statement_verdict")
            in {"supported", "unsupported"}
            and isinstance(truth_insight.get("note"), str)
            and isinstance(truth_insight.get("evidence"), list)
        ):
            raise AcceptanceError("truth insight observation is invalid")
        emitted_evidence = emitted_insight.get("evidence")
        if not isinstance(emitted_evidence, list):
            emitted_evidence = []
        truth_evidence = truth_insight["evidence"]
        if len(truth_evidence) != len(emitted_evidence):
            raise AcceptanceError("truth evidence count does not match insight")

        insight_valid = bool(emitted_evidence)
        for emitted_row, truth_row in zip(emitted_evidence, truth_evidence):
            if not isinstance(emitted_row, dict) or not isinstance(truth_row, dict):
                raise AcceptanceError("truth evidence row is invalid")
            if set(truth_row) != {
                "post_id",
                "url",
                "opened",
                "owner_matches_profile",
                "content_matches_post",
            }:
                raise AcceptanceError("truth evidence inventory is invalid")
            post_id = emitted_row.get("post_id")
            emitted_url = emitted_row.get("url")
            canonical_url = canonical_item_url(
                snapshot.platform, emitted_url, post_id
            )
            row_valid = bool(
                isinstance(post_id, str)
                and bool(post_id)
                and canonical_url is not None
                and emitted_url == canonical_url
                and truth_row.get("post_id") == post_id
                and truth_row.get("url") == canonical_url
                and normalized_urls.get(post_id) == canonical_url
                and truth_row.get("opened") is True
                and truth_row.get("owner_matches_profile") is True
                and truth_row.get("content_matches_post") is True
                and truth_insight.get("statement_verdict") == "supported"
                and canonical_url in markdown_links
                and canonical_url in html_links
            )
            total_evidence += 1
            if row_valid:
                valid_evidence += 1
            else:
                insight_valid = False
                failures.append(
                    {
                        "insight_id": truth_insight.get("insight_id"),
                        "post_id": post_id,
                        "url": truth_row.get("url"),
                    }
                )
        if insight_valid:
            covered_insights += 1

    emitted_count = len(emitted)
    insight_coverage = (
        round(covered_insights / emitted_count, 6) if emitted_count else 0.0
    )
    evidence_validity = (
        round(valid_evidence / total_evidence, 6) if total_evidence else 0.0
    )
    enough_emitted_insights = emitted_count >= MIN_MANUAL_INSIGHTS
    complete = bool(
        enough_emitted_insights
        and covered_insights == emitted_count
        and valid_evidence == total_evidence
        and total_evidence > 0
    )
    verdict = (
        "INCONCLUSIVE"
        if not enough_emitted_insights
        else ("PASS" if complete else "FAIL")
    )
    return {
        "verdict": verdict,
        "emitted_insight_count": emitted_count,
        "minimum_manual_insights": MIN_MANUAL_INSIGHTS,
        "covered_insight_count": covered_insights,
        "insight_coverage": insight_coverage,
        "evidence_row_count": total_evidence,
        "valid_evidence_row_count": valid_evidence,
        "evidence_validity": evidence_validity,
        "failures": failures,
    }


def _acceptance_scope(snapshot: BoundSnapshot) -> dict[str, Any]:
    """Disclose whether scores cover a complete or explicitly partial run."""
    collection_status = snapshot.collection_task.get("task_status")
    analysis_status = snapshot.analysis_task.get("task_status")
    coverage = snapshot.collection_task.get("collection_coverage")
    is_exhaustive = (
        coverage.get("is_exhaustive")
        if isinstance(coverage, dict)
        and type(coverage.get("is_exhaustive")) is bool
        else None
    )
    end_to_end_complete = bool(
        collection_status == "COMPLETED"
        and analysis_status == "COMPLETED"
    )
    if not end_to_end_complete:
        status = "PARTIAL_SOURCE_SAMPLE"
    elif is_exhaustive is False:
        status = "NON_EXHAUSTIVE_SOURCE_SAMPLE"
    else:
        status = "COMPLETE_PIPELINE_SAMPLE"
    return {
        "status": status,
        "collection_task_status": collection_status,
        "collection_stop_reason": snapshot.collection_task.get("stop_reason"),
        "collection_diagnostic_code": snapshot.collection_task.get(
            "diagnostic_code"
        ),
        "collection_is_exhaustive": is_exhaustive,
        "analysis_task_status": analysis_status,
        "analysis_partial_reasons": list(
            snapshot.analysis_task.get("partial_reasons") or []
        ),
        "end_to_end_complete": end_to_end_complete,
    }


def verify_truth(
    collection_dir: Path | str,
    analysis_dir: Path | str,
    truth: dict[str, Any],
) -> dict[str, Any]:
    """Verify one completed, externally observed truth artifact."""
    with _bound_snapshot(collection_dir, analysis_dir) as snapshot:
        sample_size = _validate_truth_header(snapshot, truth)
        integrity = _pipeline_integrity(snapshot)
        ac03 = _score_ac03(snapshot, truth, sample_size)
        ac06 = _score_ac06(snapshot, truth)
        acceptance_scope = _acceptance_scope(snapshot)
        verdicts = {
            integrity["verdict"],
            ac03["verdict"],
            ac06["verdict"],
        }
        if verdicts == {"PASS"} and acceptance_scope["end_to_end_complete"]:
            overall_verdict = "PASS"
        elif "FAIL" in verdicts:
            overall_verdict = "FAIL"
        else:
            overall_verdict = "INCONCLUSIVE"
        return {
            "schema": "public-social-account-analyzer/acceptance-result-v1",
            "platform": snapshot.platform,
            "collection_commit_sha256": snapshot.collection_digest,
            "analysis_commit_sha256": snapshot.analysis_digest,
            "pipeline_integrity": integrity,
            "ac03": ac03,
            "ac06": ac06,
            "acceptance_scope": acceptance_scope,
            "overall_verdict": overall_verdict,
        }


def load_truth(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise AcceptanceError("truth file cannot be read") from exc
    if len(payload) > MAX_TRUTH_BYTES:
        raise AcceptanceError("truth file is too large")
    return _json_object(payload, "truth file")


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=False, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _outside_workspaces(
    collection: Path, analysis: Path, output: Path
) -> None:
    try:
        reject_workspace_overlap(str(collection), str(output))
        reject_workspace_overlap(str(analysis), str(output))
    except WorkspaceError as exc:
        raise AcceptanceError(
            "truth output must be outside both sealed workspaces"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PRD AC-03 / AC-06 external human-truth acceptance"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="create an empty review form")
    prepare.add_argument("--collection", required=True, type=Path)
    prepare.add_argument("--analysis", required=True, type=Path)
    prepare.add_argument("--out", required=True, type=Path)
    prepare.add_argument("--sample", type=int, default=MIN_POST_SAMPLE)
    verify = commands.add_parser("verify", help="score a completed review form")
    verify.add_argument("--collection", required=True, type=Path)
    verify.add_argument("--analysis", required=True, type=Path)
    verify.add_argument("--truth", required=True, type=Path)
    verify.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            _outside_workspaces(args.collection, args.analysis, args.out)
            prepared = prepare_truth(
                args.collection, args.analysis, sample_size=args.sample
            )
            _write_new_json(args.out, prepared)
            print(f"external truth form created: {args.out}")
            print("AC-03/AC-06 remain NOT_ASSESSED until a human completes it")
            return 0

        truth = load_truth(args.truth)
        result = verify_truth(args.collection, args.analysis, truth)
    except (AcceptanceError, OSError, WorkspaceError) as exc:
        print(f"INVALID_INPUT: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(
            "pipeline_integrity / AC-03 / AC-06: "
            f"{result['pipeline_integrity']['verdict']} / "
            f"{result['ac03']['verdict']} / {result['ac06']['verdict']}"
        )
        print(
            f"AC-03 accuracy: {result['ac03']['accuracy']:.2%} "
            f"({result['ac03']['correct_observations']}/"
            f"{result['ac03']['required_observations']})"
        )
        print(
            f"AC-06 insight/evidence coverage: "
            f"{result['ac06']['insight_coverage']:.2%} / "
            f"{result['ac06']['evidence_validity']:.2%}"
        )
        print(
            "scope: "
            f"{result['acceptance_scope']['status']} "
            f"(collection={result['acceptance_scope']['collection_task_status']}, "
            f"analysis={result['acceptance_scope']['analysis_task_status']}, "
            "exhaustive="
            f"{result['acceptance_scope']['collection_is_exhaustive']})"
        )
        print(f"overall: {result['overall_verdict']}")
    return 0 if result["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
