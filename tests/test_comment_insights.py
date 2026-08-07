"""Strict external-model comment-semantic contracts."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

import immutable_workspace as workspace
from analysis import render_report


COLLECTION_ARTIFACTS = frozenset(
    {
        "source/profile.json",
        "source/posts.jsonl",
        "source/comments.jsonl",
        "task.json",
        "collection-report.md",
    }
)


def _profile() -> dict:
    return {
        "platform": "douyin",
        "account_id": "account-1",
        "account_name": "评论示例账号",
        "profile_url": "https://www.douyin.com/user/example",
        "followers": 1000,
    }


def _post() -> dict:
    return {
        "platform": "douyin",
        "post_id": "1001",
        "post_url": "https://www.douyin.com/video/1001",
        "published_at": "2026-07-01T08:00:00+08:00",
        "content_type": "video",
        "title": "如何选择公开内容分析指标",
        "text": "先明确目标，再选择公开可见指标。",
        "hashtags": ["内容分析"],
        "collection_status": "SUCCESS",
        "collected_at": "2026-07-03T08:00:00+08:00",
        "views": 100,
        "likes": 10,
        "comments": 5,
        "favorites": 1,
        "shares": 1,
    }


def _comment(comment_id: str, text: str) -> dict:
    return {
        "comment_id": comment_id,
        "parent_post_id": "1001",
        "parent_post_url": "https://www.douyin.com/video/1001",
        "author": "公开用户",
        "text": text,
        "likes": 1,
        "published_at": "2026-07-02T09:00:00+08:00",
        "collected_at": "2026-07-03T10:00:00+08:00",
    }


def _comments() -> list[dict]:
    return [
        _comment("c1", "请问怎么选择分析指标？"),
        _comment("c2", "指标应该怎么选？"),
        _comment("c3", "我不同意只看播放量。"),
        _comment("c4", "希望提供可以复用的分析模板。"),
        _comment("c5", "担心样本太少会造成误导。"),
    ]


def _comments_payload() -> bytes:
    return "".join(
        json.dumps(item, ensure_ascii=False) + "\n" for item in _comments()
    ).encode("utf-8")


def _collection(tmp_path: Path) -> tuple[Path, str, bytes]:
    target = tmp_path / "collection"
    comments_payload = _comments_payload()
    artifacts = {
        "source/profile.json": json.dumps(
            _profile(), ensure_ascii=False
        ).encode("utf-8"),
        "source/posts.jsonl": (
            json.dumps(_post(), ensure_ascii=False) + "\n"
        ).encode("utf-8"),
        "source/comments.jsonl": comments_payload,
        "task.json": json.dumps(
            {
                "task_id": "comment-source-task",
                "platform": "douyin",
                "task_status": "COMPLETED",
                "requested_limit": 1,
                "collected_count": 1,
                "analysis_goal": "分析公开评论反馈",
                "include_comments": True,
                "comment_collection": {
                    "attempted_posts": 1,
                    "comments_collected": 5,
                    "empty_results": 0,
                    "failures": 0,
                    "per_post_limit": 20,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        "collection-report.md": b"# collection\n",
    }
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts=COLLECTION_ARTIFACTS
    )
    try:
        for relative, payload in artifacts.items():
            with reservation.open_binary(relative) as handle:
                handle.write(payload)
        digest = reservation.commit()
    finally:
        reservation.close()
    return target, digest, comments_payload


def _classification_payload() -> bytes:
    return (
        json.dumps(
            [
                {
                    "post_id": "1001",
                    "topic": "内容分析",
                    "format": "tutorial",
                    "funnel_stage": "education",
                    "hook_type": "question",
                    "series_name": "分析课",
                    "is_original": True,
                    "has_product_placement": False,
                    "analysis_labels": ["方法"],
                    "classification_confidence": 0.9,
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _minimal_template() -> str:
    return "<!doctype html><html><body>" + "".join(
        "{{" + name + "}}" for name in render_report.PLACEHOLDERS
    ) + "</body></html>"


def test_comment_insight_draft_requires_usable_comment_text():
    analyze = importlib.import_module("analysis.analyze")

    with pytest.raises(
        ValueError, match="at least one usable comment text"
    ):
        analyze.analyze_comments_in_memory(
            [_post()],
            {
                "include_comments": True,
                "comment_collection": {
                    "attempted_posts": 1,
                    "comments_collected": 0,
                    "empty_results": 1,
                    "failures": 0,
                    "per_post_limit": 20,
                },
            },
            platform="douyin",
            comments_payload=b"",
            with_comment_insights=True,
        )


def _pipeline_module():
    return importlib.import_module("run_pipeline")


def _evidence(comment_id: str, source_line: int, excerpt: str) -> dict:
    return {
        "parent_post_id": "1001",
        "comment_id": comment_id,
        "source_line": source_line,
        "excerpt": excerpt,
    }


def _comment_result(draft_analysis: dict, comments_sha256: str) -> dict:
    semantic = draft_analysis["comment_analysis"]["semantic"]
    provenance = semantic["provenance"]
    return {
        "schema_version": 1,
        "model_version": "llm-comment-1",
        "comments_source_sha256": comments_sha256,
        "semantic_input_sha256": provenance["semantic_input_sha256"],
        "input_summary": copy.deepcopy(semantic["input_summary"]),
        "insights": {
            "frequent_questions": [
                {
                    "id": "frequent-question-01",
                    "statement": "用户反复询问如何选择分析指标。",
                    "evidence": [
                        _evidence("c1", 1, "怎么选择分析指标"),
                        _evidence("c2", 2, "指标应该怎么选"),
                    ],
                }
            ],
            "controversies": [
                {
                    "id": "controversy-01",
                    "statement": "是否只看播放量存在分歧。",
                    "evidence": [
                        _evidence("c3", 3, "不同意只看播放量")
                    ],
                }
            ],
            "needs": [
                {
                    "id": "need-01",
                    "statement": "用户需要可复用的分析模板。",
                    "evidence": [_evidence("c4", 4, "可以复用的分析模板")],
                }
            ],
            "concerns": [
                {
                    "id": "concern-01",
                    "statement": "用户顾虑小样本可能造成误导。",
                    "evidence": [_evidence("c5", 5, "样本太少会造成误导")],
                }
            ],
            "follow_up_topics": [
                {
                    "id": "follow-up-topic-01",
                    "statement": "后续可讲解小样本分析模板的使用边界。",
                    "evidence": [_evidence("c5", 5, "样本太少")],
                }
            ],
        },
        "limitations": ["仅代表本次公开评论样本。"],
    }


def _draft(tmp_path: Path):
    pipeline = _pipeline_module()
    collection, collection_digest, comments_payload = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "classification.json"
    classification_path.write_bytes(classification_payload)
    output = tmp_path / "comment-draft"
    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_comment_insights=True,
    )
    analysis = json.loads((output / "analysis.json").read_text(encoding="utf-8"))
    return (
        pipeline,
        collection,
        collection_digest,
        comments_payload,
        classification_path,
        output,
        result,
        analysis,
    )


def test_comment_insight_draft_is_pending_and_seals_bound_prompt(tmp_path):
    (
        pipeline,
        _collection_path,
        _collection_digest,
        comments_payload,
        _classification_path,
        output,
        result,
        analysis,
    ) = _draft(tmp_path)

    semantic = analysis["comment_analysis"]["semantic"]
    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    prompt = (output / "comment-insights-prompt.md").read_text(encoding="utf-8")
    markdown = (output / "account-analysis-report.md").read_text(encoding="utf-8")
    html = (output / "dashboard.html").read_text(encoding="utf-8")
    comments_digest = hashlib.sha256(comments_payload).hexdigest()
    assert result.task_status == "PARTIAL"
    assert task["partial_reasons"] == ["PENDING_COMMENT_INSIGHTS"]
    assert analysis["comment_insight_required"] is True
    assert analysis["comment_insight_status"] == "pending-model"
    assert semantic["status"] == "pending-model"
    assert semantic["insights"] is None
    assert semantic["input_summary"] == {
        "sampled_comment_count": 5,
        "usable_comment_count": 5,
        "parent_post_count": 1,
    }
    assert semantic["provenance"]["comments_source_sha256"] == comments_digest
    assert comments_digest in prompt
    assert semantic["provenance"]["semantic_input_sha256"] in prompt
    assert '"frequent_questions"' in prompt
    assert '"comment_id": "c1"' in prompt
    for rendered in (markdown, html):
        assert "评论语义状态 (comment_insight_status)" in rendered
        assert "pending-model（待生成）" in rendered
    manifest = workspace.verify_committed_workspace(
        str(output), allowed_artifacts=pipeline.ANALYSIS_ARTIFACTS
    )
    assert "comment-insights-prompt.md" in {
        item["path"] for item in manifest["artifacts"]
    }


def test_comment_insight_final_binds_raw_result_and_renders_all_categories(tmp_path):
    (
        pipeline,
        collection,
        _collection_digest,
        comments_payload,
        classification_path,
        _draft_output,
        _draft_result,
        draft_analysis,
    ) = _draft(tmp_path)
    comments_digest = hashlib.sha256(comments_payload).hexdigest()
    payload = (
        json.dumps(
            _comment_result(draft_analysis, comments_digest),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    result_path = tmp_path / "comment-result.json"
    result_path.write_bytes(payload)
    output = tmp_path / "comment-final"

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_comment_insights=True,
        comment_insight_results_path=str(result_path),
    )

    analysis = json.loads((output / "analysis.json").read_text(encoding="utf-8"))
    semantic = analysis["comment_analysis"]["semantic"]
    assert result.task_status == "COMPLETED"
    assert analysis["comment_analysis"]["status"] == "collected_analyzed"
    assert semantic["status"] == "completed"
    assert semantic["provenance"]["result_sha256"] == hashlib.sha256(payload).hexdigest()
    assert semantic["output_summary"] == {
        "total_insights": 5,
        "evidence_reference_count": 6,
        "category_counts": {
            "frequent_questions": 1,
            "controversies": 1,
            "needs": 1,
            "concerns": 1,
            "follow_up_topics": 1,
        },
    }
    for values in semantic["insights"].values():
        for insight in values:
            for evidence in insight["evidence"]:
                assert set(evidence) == {
                    "parent_post_id",
                    "parent_post_url",
                    "comment_id",
                    "source_line",
                    "excerpt",
                    "source_artifact",
                }
                assert evidence["parent_post_url"] == (
                    "https://www.douyin.com/video/1001"
                )
    assert (output / "source" / "comment-insight-results.json").read_bytes() == payload
    markdown = (output / "account-analysis-report.md").read_text(encoding="utf-8")
    html = (output / "dashboard.html").read_text(encoding="utf-8")
    for rendered in (markdown, html):
        for expected in (
            "评论语义洞察",
            "高频问题",
            "争议",
            "需求",
            "顾虑",
            "后续选题线索",
            "用户反复询问如何选择分析指标",
            "c1",
            "source/comments.jsonl:1",
            "怎么选择分析指标",
            "https://www.douyin.com/video/1001",
        ):
            assert expected in rendered
        assert "评论语义洞察待模型处理" not in rendered
        assert "collected_pending_model" not in rendered
    manifest = workspace.verify_committed_workspace(
        str(output), allowed_artifacts=pipeline.ANALYSIS_ARTIFACTS
    )
    assert "source/comment-insight-results.json" in {
        item["path"] for item in manifest["artifacts"]
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "schema_boolean",
        "comments_digest",
        "semantic_digest",
        "input_summary",
        "parent",
        "source_line",
        "excerpt",
        "frequent_count",
        "unexpected_url",
    ),
)
def test_invalid_comment_insight_result_fails_before_publish(tmp_path, mutation):
    (
        pipeline,
        collection,
        _collection_digest,
        comments_payload,
        classification_path,
        _draft_output,
        _draft_result,
        draft_analysis,
    ) = _draft(tmp_path)
    value = _comment_result(
        draft_analysis, hashlib.sha256(comments_payload).hexdigest()
    )
    if mutation == "schema_boolean":
        value["schema_version"] = True
    elif mutation == "comments_digest":
        value["comments_source_sha256"] = "0" * 64
    elif mutation == "semantic_digest":
        value["semantic_input_sha256"] = "0" * 64
    elif mutation == "input_summary":
        value["input_summary"]["usable_comment_count"] = 4
    elif mutation == "parent":
        value["insights"]["needs"][0]["evidence"][0]["parent_post_id"] = "9999"
    elif mutation == "source_line":
        value["insights"]["needs"][0]["evidence"][0]["source_line"] = 5
    elif mutation == "excerpt":
        value["insights"]["needs"][0]["evidence"][0]["excerpt"] = "不存在"
    elif mutation == "frequent_count":
        value["insights"]["frequent_questions"][0]["evidence"].pop()
    else:
        value["insights"]["needs"][0]["evidence"][0]["parent_post_url"] = (
            "https://evil.example/video/1001"
        )
    result_path = tmp_path / f"invalid-{mutation}.json"
    result_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / f"invalid-{mutation}"

    with pytest.raises(pipeline.PipelineError, match="comment insight"):
        pipeline.run_pipeline(
            str(collection),
            str(output),
            template_text=_minimal_template(),
            with_taxonomy_prompt=True,
            classification_results_path=str(classification_path),
            with_comment_insights=True,
            comment_insight_results_path=str(result_path),
        )

    assert not output.exists()
