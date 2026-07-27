"""Truth-bound PRD AC-03 / AC-06 acceptance checks."""

from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path

import pytest

import immutable_workspace as workspace
import manual_accuracy_check as acceptance
import normalize


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


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")


def _posts() -> list[dict]:
    result = []
    for index in range(10):
        post_id = str(7000 + index)
        result.append(
            {
                "platform": "douyin",
                "post_id": post_id,
                "post_url": f"https://www.douyin.com/video/{post_id}",
                "source_url": f"https://www.douyin.com/video/{post_id}",
                "published_at": f"2026-07-{index + 1:02d}T12:00:00+08:00",
                "content_type": "video",
                "title": f"公开标题 {index}",
                "text": f"公开正文 {index}",
                "duration_seconds": 10 + index,
                "hashtags": ["公开", f"主题{index}"],
                "views": 1000 + index,
                "likes": 100 + index,
                "comments": 10 + index,
                "favorites": 20 + index,
                "shares": 5 + index,
                "coins": None,
                "danmaku": None,
                "collection_status": "SUCCESS",
                "field_visibility": {
                    "post_id": "visible",
                    "post_url": "visible",
                    "title": "visible",
                    "text": "visible",
                    "published_at": "visible",
                    "content_type": "visible",
                    "duration_seconds": "visible",
                    "hashtags": "visible",
                    "views": "visible",
                    "likes": "visible",
                    "comments": "visible",
                    "favorites": "visible",
                    "shares": "visible",
                    "coins": "hidden",
                    "danmaku": "hidden",
                },
            }
        )
    return result


def _profile() -> dict:
    return {
        "platform": "douyin",
        "account_id": "public-account",
        "account_name": "公开账号",
        "profile_url": "https://www.douyin.com/user/public-account",
        "bio": "公开简介",
        "verified": True,
        "followers": 12345,
        "post_count": 10,
        "platform_metrics": {"total_likes": 54321},
        "field_visibility": {
            "account_id": "visible",
            "account_name": "visible",
            "bio": "visible",
            "verified": "visible",
            "followers": "visible",
            "post_count": "visible",
            "total_likes": "visible",
        },
    }


def _commit(
    target: Path, artifacts: dict[str, bytes], allowed: frozenset[str]
) -> str:
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts=allowed
    )
    try:
        for relative, payload in artifacts.items():
            with reservation.open_binary(relative) as handle:
                handle.write(payload)
        return reservation.commit()
    finally:
        reservation.close()


def _workspace_pair(
    tmp_path: Path,
    *,
    insight_count: int = 3,
    duplicate_insight_ids: bool = False,
    report_links_are_not_real: bool = False,
    bad_provenance_inventory: bool = False,
    analysis_task_status: str = "COMPLETED",
    bad_evidence_coverage: bool = False,
) -> tuple[Path, Path, list[dict], dict]:
    posts = _posts()
    profile = _profile()
    task = {
        "task_id": "douyin-source-task",
        "platform": "douyin",
        "profile_url": profile["profile_url"],
        "requested_limit": 10,
        "collected_count": 10,
        "task_status": "COMPLETED",
    }
    profile_payload = _json_bytes(profile)
    posts_payload = b"".join(_json_bytes(post) for post in posts)
    task_payload = _json_bytes(task)
    normalized = normalize.normalize_in_memory(profile, posts_payload)

    collection = tmp_path / "collection"
    collection_digest = _commit(
        collection,
        {
            "source/profile.json": profile_payload,
            "source/posts.jsonl": posts_payload,
            "normalized-posts.csv": normalized.csv_text.encode("utf-8"),
            "task.json": task_payload,
            "collection-report.md": b"# collection\n",
        },
        COLLECTION_ARTIFACTS,
    )
    collection_manifest = workspace.verify_committed_workspace(
        str(collection), allowed_artifacts=COLLECTION_ARTIFACTS
    )

    core_insights = []
    report_urls = []
    for index in range(insight_count):
        post = posts[index]
        report_urls.append(post["post_url"])
        core_insights.append(
            {
                "id": (
                    "duplicate-insight"
                    if duplicate_insight_ids
                    else f"insight-{index + 1}"
                ),
                "statement": f"可人工核验的洞察 {index + 1}",
                "evidence": [
                    {
                        "post_id": post["post_id"],
                        "url": post["post_url"],
                    }
                ],
            }
        )
    evidence_coverage = {
        "selected_count": insight_count,
        "complete_count": insight_count,
        "missing_count": 0,
        "missing_post_ids": [],
        "rate": 1.0 if insight_count else None,
        "status": "COMPLETE",
    }
    if bad_evidence_coverage:
        evidence_coverage["missing_count"] = 1
    analysis_payload = _json_bytes(
        {
            "core_insights": core_insights,
            "evidence_coverage": evidence_coverage,
        }
    )
    provenance = {
        "source_format": workspace.FORMAT,
        "source_task_id": task["task_id"],
        "collection_commit_sha256": collection_digest,
        "source_manifest_artifacts": (
            []
            if bad_provenance_inventory
            else [
                {
                    "path": item["path"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                }
                for item in collection_manifest["artifacts"]
            ]
        ),
    }
    analysis_task = {
        "task_id": "douyin-analysis-task",
        "platform": "douyin",
        "analysis_goal": None,
        "source_task_id": task["task_id"],
        "collection_commit_sha256": collection_digest,
        "task_status": analysis_task_status,
        "partial_reasons": (
            [] if analysis_task_status == "COMPLETED" else ["TEST_PARTIAL"]
        ),
        "phase_results": {
            "collection_input": "VERIFIED",
            "normalization": "COMPLETED",
            "analysis": analysis_task_status,
            "render": "COMPLETED",
            "validation": "COMPLETED",
        },
    }
    if report_links_are_not_real:
        markdown = "\n".join(report_urls) + "\n"
        html = "".join(
            f'<!-- <a href="{url}">not rendered</a> -->'
            for url in report_urls
        )
    else:
        markdown = "\n".join(
            f"[evidence]({url})" for url in report_urls
        ) + "\n"
        html = "".join(
            f'<a href="{url}">evidence</a>' for url in report_urls
        )
    analysis = tmp_path / "analysis"
    _commit(
        analysis,
        {
            "source/profile.json": profile_payload,
            "source/posts.jsonl": posts_payload,
            "source/collection-task.json": task_payload,
            "source/collection-provenance.json": _json_bytes(provenance),
            "normalized-posts.csv": normalized.csv_text.encode("utf-8"),
            "normalized-coverage.json": _json_bytes({"valid_count": 10}),
            "analysis.json": analysis_payload,
            "account-analysis-report.md": markdown.encode("utf-8"),
            "dashboard.html": html.encode("utf-8"),
            "task.json": _json_bytes(analysis_task),
            "pipeline-report.md": b"# pipeline\n",
        },
        workspace.ANALYSIS_ARTIFACTS,
    )
    return collection, analysis, posts, profile


def _nested(value: dict, dotted_key: str):
    current = value
    for part in dotted_key.split("."):
        current = current[part]
    return current


def _completed_truth(template: dict, posts: list[dict], profile: dict) -> dict:
    truth = copy.deepcopy(template)
    truth["reviewer"] = {
        "id": "ops-001",
        "reviewed_at": "2026-07-27T15:00:00+08:00",
    }
    truth["profile"]["observed_at"] = "2026-07-27T15:00:00+08:00"
    for field, observation in truth["profile"]["fields"].items():
        value = _nested(profile, field)
        observation.update(
            {
                "state": "visible" if value is not None else "not_visible",
                "page_text": str(value) if value is not None else None,
                "value": value,
            }
        )
    by_id = {post["post_id"]: post for post in posts}
    for truth_post in truth["posts"]:
        post = by_id[truth_post["post_id"]]
        truth_post["observed_at"] = "2026-07-27T15:00:00+08:00"
        for field, observation in truth_post["fields"].items():
            value = post.get(field)
            observation.update(
                {
                    "state": "visible" if value is not None else "not_visible",
                    "page_text": str(value) if value is not None else None,
                    "value": value,
                }
            )
    for insight in truth["insights"]:
        insight["statement_verdict"] = "supported"
        for evidence in insight["evidence"]:
            evidence.update(
                {
                    "opened": True,
                    "owner_matches_profile": True,
                    "content_matches_post": True,
                }
            )
    return truth


def test_prepare_and_verify_require_external_truth_for_ac03_and_ac06(tmp_path):
    collection, analysis, posts, profile = _workspace_pair(tmp_path)

    template = acceptance.prepare_truth(collection, analysis, sample_size=10)
    assert template["selection"]["method"] == "commit-sha256-v1"
    assert len(template["selection"]["post_ids"]) == 10
    assert all(
        observation["state"] is None
        for observation in template["profile"]["fields"].values()
    )

    result = acceptance.verify_truth(
        collection,
        analysis,
        _completed_truth(template, posts, profile),
    )

    assert result["ac03"]["verdict"] == "PASS"
    assert result["ac03"]["accuracy"] == 1.0
    assert result["ac06"]["verdict"] == "PASS"
    assert result["ac06"]["insight_coverage"] == 1.0
    assert result["pipeline_integrity"]["verdict"] == "PASS"


def test_self_consistent_pipeline_cannot_hide_external_truth_errors(tmp_path):
    collection, analysis, posts, profile = _workspace_pair(tmp_path)
    template = acceptance.prepare_truth(collection, analysis, sample_size=10)
    truth = _completed_truth(template, posts, profile)
    for truth_post in truth["posts"]:
        truth_post["fields"]["title"]["value"] = "页面上的不同标题"

    result = acceptance.verify_truth(collection, analysis, truth)

    assert result["pipeline_integrity"]["verdict"] == "PASS"
    assert result["ac03"]["accuracy"] < 0.95
    assert result["ac03"]["verdict"] == "FAIL"


def test_visible_zero_is_not_equal_to_an_unknown_null():
    assert acceptance._score_observation(
        actual=None,
        visibility="hidden",
        observation={"state": "visible", "page_text": "0", "value": 0},
    ) is False


def test_ac06_rejects_a_profile_url_even_when_human_flags_are_true(tmp_path):
    collection, analysis, posts, profile = _workspace_pair(tmp_path)
    template = acceptance.prepare_truth(collection, analysis, sample_size=10)
    truth = _completed_truth(template, posts, profile)
    truth["insights"][0]["evidence"][0]["url"] = profile["profile_url"]

    result = acceptance.verify_truth(collection, analysis, truth)

    assert result["ac03"]["verdict"] == "PASS"
    assert result["ac06"]["verdict"] == "FAIL"


def test_prepare_rejects_fewer_eligible_posts_than_requested(tmp_path):
    collection, analysis, _, _ = _workspace_pair(tmp_path)

    with pytest.raises(acceptance.AcceptanceError, match="11"):
        acceptance.prepare_truth(collection, analysis, sample_size=11)


def test_zero_emitted_insights_is_inconclusive_not_vacuous_pass(tmp_path):
    collection, analysis, posts, profile = _workspace_pair(
        tmp_path, insight_count=0
    )
    template = acceptance.prepare_truth(collection, analysis, sample_size=10)
    truth = _completed_truth(template, posts, profile)

    result = acceptance.verify_truth(collection, analysis, truth)

    assert result["ac03"]["verdict"] == "PASS"
    assert result["ac06"]["verdict"] == "INCONCLUSIVE"
    assert result["overall_verdict"] == "INCONCLUSIVE"


def test_pipeline_integrity_compares_against_normalization_semantics():
    profile = _profile()
    source_post = _posts()[0]
    source_post["published_at"] = "2026-07-01T04:00:00Z"
    payload = _json_bytes(source_post)
    normalized = normalize.normalize_in_memory(profile, payload).rows
    snapshot = acceptance.BoundSnapshot(
        collection_digest="a" * 64,
        analysis_digest="b" * 64,
        platform="douyin",
        profile=profile,
        source_posts=[source_post],
        normalized_posts=normalized,
        analysis={},
        collection_task={},
        analysis_task={},
        markdown="",
        html="",
    )

    assert normalized[0]["published_at"] != source_post["published_at"]
    assert acceptance._pipeline_integrity(snapshot)["verdict"] == "PASS"


def test_visible_observation_cannot_claim_a_null_value():
    with pytest.raises(acceptance.AcceptanceError, match="visible value"):
        acceptance._validate_observation(
            {
                "state": "visible",
                "page_text": "页面明确显示了正文",
                "value": None,
            },
            "post 1.text",
        )


def test_ac06_requires_rendered_links_not_plain_text_or_html_comments(tmp_path):
    collection, analysis, posts, profile = _workspace_pair(
        tmp_path, report_links_are_not_real=True
    )
    template = acceptance.prepare_truth(collection, analysis, sample_size=10)
    truth = _completed_truth(template, posts, profile)

    result = acceptance.verify_truth(collection, analysis, truth)

    assert result["ac06"]["verdict"] == "FAIL"
    assert result["ac06"]["valid_evidence_row_count"] == 0


def test_duplicate_core_insight_ids_are_rejected(tmp_path):
    collection, analysis, _, _ = _workspace_pair(
        tmp_path, duplicate_insight_ids=True
    )

    with pytest.raises(acceptance.AcceptanceError, match="unique"):
        acceptance.prepare_truth(collection, analysis, sample_size=10)


def test_ac06_rejects_null_post_id_even_if_a_normalized_null_id_exists():
    url = "https://www.douyin.com/video/7000"
    snapshot = acceptance.BoundSnapshot(
        collection_digest="a" * 64,
        analysis_digest="b" * 64,
        platform="douyin",
        profile=_profile(),
        source_posts=[],
        normalized_posts=[{"post_id": None, "post_url": url}],
        analysis={
            "core_insights": [
                {
                    "id": "insight-1",
                    "statement": "公开内容洞察",
                    "evidence": [{"post_id": None, "url": url}],
                },
                {
                    "id": "insight-2",
                    "statement": "公开内容洞察 2",
                    "evidence": [{"post_id": None, "url": url}],
                },
                {
                    "id": "insight-3",
                    "statement": "公开内容洞察 3",
                    "evidence": [{"post_id": None, "url": url}],
                },
            ]
        },
        collection_task={},
        analysis_task={},
        markdown=f"[evidence]({url})",
        html=f'<a href="{url}">evidence</a>',
    )
    truth = {
        "insights": [
            {
                "insight_id": f"insight-{index}",
                "statement": (
                    "公开内容洞察" if index == 1 else f"公开内容洞察 {index}"
                ),
                "statement_verdict": "supported",
                "evidence": [
                    {
                        "post_id": None,
                        "url": url,
                        "opened": True,
                        "owner_matches_profile": True,
                        "content_matches_post": True,
                    }
                ],
                "note": "",
            }
            for index in range(1, 4)
        ]
    }

    result = acceptance._score_ac06(snapshot, truth)

    assert result["verdict"] == "FAIL"
    assert result["valid_evidence_row_count"] == 0


def test_douyin_ac03_excludes_inapplicable_metrics_and_reports_field_accuracy(
    tmp_path,
):
    collection, analysis, posts, profile = _workspace_pair(tmp_path)
    template = acceptance.prepare_truth(collection, analysis, sample_size=10)
    for truth_post in template["posts"]:
        assert "coins" not in truth_post["fields"]
        assert "danmaku" not in truth_post["fields"]
    truth = _completed_truth(template, posts, profile)
    for truth_post in truth["posts"][:7]:
        truth_post["fields"]["title"]["value"] = "页面上的不同标题"

    result = acceptance.verify_truth(collection, analysis, truth)

    assert result["ac03"]["verdict"] == "FAIL"
    assert result["ac03"]["field_accuracy"]["title"]["accuracy"] == 0.3
    assert result["ac03"]["scope_accuracy"]["posts"]["correct"] < (
        result["ac03"]["scope_accuracy"]["posts"]["required"]
    )


def test_ac03_rejects_a_schema_invalid_visible_value_type():
    with pytest.raises(acceptance.AcceptanceError, match="followers.*type"):
        acceptance._validate_typed_value(
            scope="profile",
            platform="douyin",
            field="followers",
            value="12345",
        )


def test_acceptance_rejects_fake_collection_manifest_provenance(tmp_path):
    collection, analysis, _, _ = _workspace_pair(
        tmp_path, bad_provenance_inventory=True
    )

    with pytest.raises(acceptance.AcceptanceError, match="manifest inventory"):
        acceptance.prepare_truth(collection, analysis, sample_size=10)


def test_acceptance_rejects_a_noncompleted_analysis_task(tmp_path):
    collection, analysis, _, _ = _workspace_pair(
        tmp_path, analysis_task_status="PARTIAL"
    )

    with pytest.raises(acceptance.AcceptanceError, match="task is not completed"):
        acceptance.prepare_truth(collection, analysis, sample_size=10)


def test_acceptance_rejects_incoherent_analysis_evidence_coverage(tmp_path):
    collection, analysis, _, _ = _workspace_pair(
        tmp_path, bad_evidence_coverage=True
    )

    with pytest.raises(acceptance.AcceptanceError, match="evidence coverage"):
        acceptance.prepare_truth(collection, analysis, sample_size=10)


def test_pipeline_integrity_detects_a_missing_normalized_field():
    profile = _profile()
    source_post = _posts()[0]
    normalized = normalize.normalize_in_memory(
        profile, _json_bytes(source_post)
    ).rows
    del normalized[0]["title"]
    snapshot = acceptance.BoundSnapshot(
        collection_digest="a" * 64,
        analysis_digest="b" * 64,
        platform="douyin",
        profile=profile,
        source_posts=[source_post],
        normalized_posts=normalized,
        analysis={},
        collection_task={},
        analysis_task={},
        markdown="",
        html="",
    )

    result = acceptance._pipeline_integrity(snapshot)

    assert result["verdict"] == "FAIL"
    assert {"post_id": source_post["post_id"], "field": "title"} in result[
        "mismatches"
    ]


def test_pipeline_integrity_detects_duplicate_normalized_post_ids():
    profile = _profile()
    source_post = _posts()[0]
    normalized = normalize.normalize_in_memory(
        profile, _json_bytes(source_post)
    ).rows
    snapshot = acceptance.BoundSnapshot(
        collection_digest="a" * 64,
        analysis_digest="b" * 64,
        platform="douyin",
        profile=profile,
        source_posts=[source_post],
        normalized_posts=[normalized[0], copy.deepcopy(normalized[0])],
        analysis={},
        collection_task={},
        analysis_task={},
        markdown="",
        html="",
    )

    result = acceptance._pipeline_integrity(snapshot)

    assert result["verdict"] == "FAIL"
    assert result["normalized_count"] == 2
    assert any(
        item["field"] == "duplicate_normalized_post_id"
        for item in result["mismatches"]
    )
