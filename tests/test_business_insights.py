"""Strict second-stage business-insight contracts."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

import analyze
import immutable_workspace as workspace
import manual_accuracy_check as acceptance
import normalize
import render_report


COLLECTION_ARTIFACTS = frozenset(
    {
        "source/profile.json",
        "source/posts.jsonl",
        "task.json",
        "collection-report.md",
    }
)


def _profile() -> dict:
    return {
        "platform": "douyin",
        "account_id": "account-1",
        "account_name": "示例账号",
        "profile_url": "https://www.douyin.com/user/example",
        "bio": "讲解公开内容分析方法",
        "followers": 1000,
    }


def _posts() -> list[dict]:
    posts = []
    for index in range(1, 16):
        post_id = f"{index:02d}"
        posts.append(
            {
                "platform": "douyin",
                "post_id": post_id,
                "post_url": f"https://www.douyin.com/video/{post_id}",
                "published_at": f"2026-01-{index:02d}T08:00:00+08:00",
                "content_type": "video",
                "title": f"作品 {post_id} 标题",
                "text": f"作品 {post_id} 文案开头，后续结构说明",
                "hashtags": ["内容分析"],
                "collection_status": "SUCCESS",
                "collected_at": "2026-07-27T08:00:00+08:00",
                "views": 100 + index,
                "likes": 10 + index,
                "comments": 2,
                "favorites": 1,
                "shares": 1,
            }
        )
    return posts


def _collection(tmp_path: Path) -> tuple[Path, str]:
    target = tmp_path / "collection"
    posts = _posts()
    artifacts = {
        "source/profile.json": json.dumps(
            _profile(), ensure_ascii=False
        ).encode("utf-8"),
        "source/posts.jsonl": "".join(
            json.dumps(post, ensure_ascii=False) + "\n" for post in posts
        ).encode("utf-8"),
        "task.json": json.dumps(
            {
                "task_id": "douyin-source-task",
                "platform": "douyin",
                "profile_url": _profile()["profile_url"],
                "task_status": "COMPLETED",
                "requested_limit": 15,
                "collected_count": 15,
                "analysis_goal": "分析播放表现与内容策略",
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
    return target, digest


def _classification(post_id: str) -> dict:
    return {
        "post_id": post_id,
        "topic": "内容分析",
        "format": "tutorial",
        "funnel_stage": "education",
        "hook_type": "result_first",
        "series_name": "分析课",
        "is_original": True,
        "has_product_placement": False,
        "analysis_labels": ["方法"],
        "classification_confidence": 0.9,
    }


def _classification_payload() -> bytes:
    return (
        json.dumps(
            [_classification(f"{index:02d}") for index in range(1, 16)],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _evidence(post_id: str, source_field: str, excerpt: str) -> dict:
    return {
        "post_id": post_id,
        "source_field": source_field,
        "excerpt": excerpt,
    }


def _replace_evidence_triples_with_ids(value):
    if isinstance(value, list):
        return [_replace_evidence_triples_with_ids(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"post_id", "source_field", "excerpt"}:
        return {"evidence_id": f"{value['post_id']}:{value['source_field']}"}
    return {
        key: _replace_evidence_triples_with_ids(item)
        for key, item in value.items()
    }


def _group_evidence(post_ids: tuple[str, ...], source_field: str) -> list[dict]:
    if source_field == "title":
        return [_evidence(post_id, "title", f"作品 {post_id} 标题") for post_id in post_ids]
    if source_field == "opening":
        return [_evidence(post_id, "text", f"作品 {post_id} 文案开头") for post_id in post_ids]
    return [_evidence(post_id, "text", "后续结构说明") for post_id in post_ids]


def _claim(statement: str, post_id: str) -> dict:
    return {
        "statement": statement,
        "evidence": [_evidence(post_id, "title", f"作品 {post_id} 标题")],
    }


def _business_result(collection_digest: str, classification_digest: str) -> dict:
    high_ids = ("15", "14", "13")
    low_ids = ("03", "02", "01")
    patterns = []
    for group, post_ids in (("high", high_ids), ("low", low_ids)):
        for dimension, basis in (
            ("title", "title"),
            ("opening", "caption_lead"),
            ("structure", "caption_text"),
        ):
            patterns.append(
                {
                    "id": f"{group}-{dimension}",
                    "observability": "supported",
                    "basis": basis,
                    "statement": f"{group} 组{dimension}公开文案特征",
                    "evidence": _group_evidence(post_ids, dimension),
                    "limitation": None,
                }
            )
    return {
        "schema_version": 1,
        "model_version": "llm-insight-1",
        "collection_commit_sha256": collection_digest,
        "classification_results_sha256": classification_digest,
        "account_positioning": {
            "target_audience": _claim("关注内容方法的运营人员", "15"),
            "content_domain": _claim("公开社媒内容分析与运营方法", "15"),
            "value_proposition": _claim("提供可复核的内容分析方法", "14"),
            "persona_expression": _claim("严谨、证据优先的方法型表达", "14"),
            "follow_reason": _claim("持续获得可执行的分析框架", "13"),
        },
        "performance_patterns": patterns,
        "topic_ideas": [
            {
                "id": f"topic-{index:02d}",
                "title": f"选题方向 {index:02d}",
                "rationale": "延展当前公开样本中的方法主题",
                "evidence": [
                    _evidence(f"{index:02d}", "title", f"作品 {index:02d} 标题")
                ],
            }
            for index in range(1, 9)
        ],
        "content_modes": [
            {
                "id": f"mode-{index:02d}",
                "name": f"内容模式 {index:02d}",
                "recipe": "问题切入，给出方法，再总结行动",
                "evidence": [
                    _evidence(f"{index + 10:02d}", "topic", "内容分析")
                ],
            }
            for index in range(1, 6)
        ],
        "experiments": [
            {
                "id": f"experiment-{index:02d}",
                "hypothesis": f"实验假设 {index:02d}",
                "variable": "公开文案开头表达",
                "control": "保持主题与形式一致",
                "success_metric": "views",
                "decision_rule": "比较实验组与对照组的中位数",
                "window": "连续发布周期",
                "evidence": [
                    _evidence(f"{16 - index:02d}", "format", "tutorial")
                ],
            }
            for index in range(1, 5)
        ],
        "limitations": [],
    }


def _minimal_template() -> str:
    return "<!doctype html><html><body>" + "".join(
        "{{" + name + "}}" for name in render_report.PLACEHOLDERS
    ) + "</body></html>"


def _pipeline_module():
    return importlib.import_module("run_pipeline")


def test_draft_commits_taxonomy_and_business_insight_prompts(tmp_path):
    pipeline = _pipeline_module()
    collection, digest = _collection(tmp_path)
    output = tmp_path / "draft"

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        with_business_insights=True,
    )

    analysis_payload = json.loads(
        (output / "analysis.json").read_text(encoding="utf-8")
    )
    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    assert result.task_status == "PARTIAL"
    assert task["partial_reasons"] == [
        "PENDING_CLASSIFICATION",
        "PENDING_BUSINESS_INSIGHTS",
    ]
    assert analysis_payload["business_insight_status"] == "pending-model"
    assert analysis_payload["business_insight_required"] is True
    assert (output / "taxonomy-prompt.md").is_file()
    prompt = (output / "business-insights-prompt.md").read_text(encoding="utf-8")
    context = json.loads((output / "business-context.json").read_text(encoding="utf-8"))
    assert context["collection_commit_sha256"] == digest
    assert "business-result-template.json" in prompt
    manifest = workspace.verify_committed_workspace(
        str(output), allowed_artifacts=pipeline.ANALYSIS_ARTIFACTS
    )
    assert "business-insights-prompt.md" in {
        item["path"] for item in manifest["artifacts"]
    }


def test_business_prompt_binds_classification_bytes_and_states_strict_schema(
    tmp_path,
):
    pipeline = _pipeline_module()
    collection, collection_digest = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(classification_payload)
    classification_digest = hashlib.sha256(classification_payload).hexdigest()
    output = tmp_path / "business-draft"

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_business_insights=True,
    )

    prompt = (output / "business-insights-prompt.md").read_text(
        encoding="utf-8"
    )
    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    assert result.task_status == "PARTIAL"
    assert task["partial_reasons"] == ["PENDING_BUSINESS_INSIGHTS"]
    context = json.loads((output / "business-context.json").read_text(encoding="utf-8"))
    template = json.loads((output / "business-result-template.json").read_text(encoding="utf-8"))
    assert context["collection_commit_sha256"] == collection_digest
    assert context["classification_results_sha256"] == classification_digest
    assert template["schema_version"] == 1
    assert template["performance_patterns"][1]["id"] == "high-opening"
    assert template["experiments"][0]["success_metric"] == "views"
    assert "business-evidence-catalog.jsonl" in prompt


def test_business_prompt_exposes_copy_safe_source_bound_evidence_catalog(tmp_path):
    pipeline = _pipeline_module()
    collection, _collection_digest = _collection(tmp_path)
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(_classification_payload())
    output = tmp_path / "business-draft"

    pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_business_insights=True,
    )

    catalog = (output / "business-evidence-catalog.jsonl").read_text(
        encoding="utf-8"
    )
    catalog_line = next(
        line
        for line in catalog.splitlines()
        if '"evidence_id":"15:title"' in line
    )
    assert json.loads(catalog_line) == {
        "evidence_id": "15:title",
        "post_id": "15",
        "performance_group": "high",
        "source_field": "title",
        "excerpt": "作品 15 标题",
    }


def test_validate_only_accepts_model_results_without_creating_workspace(
    tmp_path, capsys
):
    pipeline = _pipeline_module()
    collection, collection_digest = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(classification_payload)
    business_path = tmp_path / "business.json"
    business_path.write_text(
        json.dumps(
            _replace_evidence_triples_with_ids(
                _business_result(
                    collection_digest,
                    hashlib.sha256(classification_payload).hexdigest(),
                )
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = pipeline.main([
        "--validate-only",
        "--input", str(collection),
        "--with-llm-tax",
        "--classification-results", str(classification_path),
        "--business-insight-results", str(business_path),
    ])

    assert exit_code == 0
    assert "model results valid" in capsys.readouterr().out
    assert {path.name for path in tmp_path.iterdir()} == {
        "collection", "taxonomy.json", "business.json",
    }


def test_final_pipeline_writes_deterministic_delivery_handoff(tmp_path):
    pipeline = _pipeline_module()
    collection, collection_digest = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(classification_payload)
    classification_digest = hashlib.sha256(classification_payload).hexdigest()
    business_path = tmp_path / "business.json"
    business_path.write_text(
        json.dumps(
            _business_result(collection_digest, classification_digest),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "final"

    pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_business_insights=True,
        business_insight_results_path=str(business_path),
    )

    handoff = json.loads(
        (output / "delivery-summary.json").read_text(encoding="utf-8")
    )
    assert handoff == {
        "schema_version": 1,
        "delivery_ready": True,
        "delivery_kind": "strategy",
        "strategy_ready": True,
        "task_status": "COMPLETED",
        "stop_reason": "null",
        "restriction_scope": None,
        "sample": {
            "requested": 15,
            "collected": 15,
            "valid": 15,
            "excluded_flagged": 0,
            "status_counts": {
                "SUCCESS": 15,
                "PARTIAL": 0,
                "FAILED": 0,
                "DELETED": 0,
                "RESTRICTED": 0,
            },
        },
        "field_coverage": {
            "views": 1.0,
            "likes": 1.0,
            "comments": 1.0,
            "favorites": 1.0,
            "shares": 1.0,
            "coins": 0.0,
            "danmaku": 0.0,
        },
        "classification": {"status": "completed", "coverage_rate": 1.0},
        "business_insights": {"status": "completed"},
        "comments": {
            "collection_status": "not_requested",
            "sampled_count": 0,
            "insight_required": False,
                "insight_status": "not-applicable",
        },
            "performance": {
                "main_metric": "views",
                "label": "按 views 排序的样本内相对表现",
                "small_denominator_warning": None,
                "axes": {
                    "reach": {"status": "ok", "measured_count": 15},
                    "engagement_efficiency": {
                        "status": "INSUFFICIENT_SAMPLE",
                        "measured_count": 11,
                        "denominator_floor": 104.5,
                        "excluded_small_denominator_count": 4,
                    },
                },
            },
    }
    final_response = (output / "final-response.md").read_text(encoding="utf-8")
    assert final_response.startswith("## 数据质量摘要\n")
    assert "SUCCESS 15 / PARTIAL 0 / FAILED 0 / DELETED 0 / RESTRICTED 0" in final_response
    assert "## 分析结论交付规则" in final_response
    assert "不得重新计算或凭记忆改写上述数字" in final_response


def test_pipeline_rejects_an_empty_delivery_handoff(monkeypatch, tmp_path):
    pipeline = _pipeline_module()
    collection, _collection_digest = _collection(tmp_path)
    output = tmp_path / "invalid-delivery"
    monkeypatch.setattr(pipeline, "_final_response", lambda _summary: "")

    with pytest.raises(pipeline.PipelineError, match="final-response.md is empty"):
        pipeline.run_pipeline(
            str(collection),
            str(output),
            template_text=_minimal_template(),
        )

    assert not output.exists()


def test_final_seals_business_result_and_renders_dynamic_contract(tmp_path):
    pipeline = _pipeline_module()
    collection, collection_digest = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(classification_payload)
    classification_digest = hashlib.sha256(classification_payload).hexdigest()
    business_payload = (
        json.dumps(
            _business_result(collection_digest, classification_digest),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    business_path = tmp_path / "business.json"
    business_path.write_bytes(business_payload)
    output = tmp_path / "final"

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_business_insights=True,
        business_insight_results_path=str(business_path),
    )

    analysis_payload = json.loads(
        (output / "analysis.json").read_text(encoding="utf-8")
    )
    assert result.task_status == "COMPLETED"
    assert analysis_payload["business_insight_status"] == "completed"
    business = analysis_payload["business_insights"]
    assert len(business["performance_patterns"]) == 6
    assert len(business["topic_ideas"]) == 8
    assert len(business["content_modes"]) == 5
    assert len(business["experiments"]) == 4
    assert (
        output / "source" / "business-insight-results.json"
    ).read_bytes() == business_payload
    manifest = workspace.verify_committed_workspace(
        str(output), allowed_artifacts=pipeline.ANALYSIS_ARTIFACTS
    )
    assert "source/business-insight-results.json" in {
        item["path"] for item in manifest["artifacts"]
    }
    markdown = (output / "account-analysis-report.md").read_text(encoding="utf-8")
    html = (output / "dashboard.html").read_text(encoding="utf-8")
    for rendered in (markdown, html):
        assert "目标受众" in rendered
        assert "内容领域" in rendered
        assert "人设 / 品牌表达" in rendered
        assert "高表现公开文案特征" in rendered
        assert "选题方向 08" in rendered
        assert "内容模式 05" in rendered
        assert "实验假设 04" in rendered
        assert "https://www.douyin.com/video/15" in rendered
    truth_form = acceptance.prepare_truth(
        collection, output, sample_size=10
    )
    assert [item["insight_id"] for item in truth_form["insights"]] == [
        "performance-high",
        "performance-low",
        "positioning-target_audience",
        "positioning-content_domain",
        "positioning-value_proposition",
        "positioning-persona_expression",
        "positioning-follow_reason",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "schema_boolean",
        "collection_digest",
        "classification_digest",
        "parent",
        "group",
        "count",
        "url",
    ],
)
def test_invalid_business_result_fails_before_publishing(tmp_path, mutation):
    pipeline = _pipeline_module()
    collection, collection_digest = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(classification_payload)
    classification_digest = hashlib.sha256(classification_payload).hexdigest()
    business = _business_result(collection_digest, classification_digest)
    if mutation == "schema_boolean":
        business["schema_version"] = True
    elif mutation == "collection_digest":
        business["collection_commit_sha256"] = "0" * 64
    elif mutation == "classification_digest":
        business["classification_results_sha256"] = "0" * 64
    elif mutation == "parent":
        business["account_positioning"]["target_audience"]["evidence"][0][
            "post_id"
        ] = "99"
    elif mutation == "group":
        business["performance_patterns"][0]["evidence"][0]["post_id"] = "01"
    elif mutation == "count":
        business["topic_ideas"] = business["topic_ideas"][:2]
    else:
        business["account_positioning"]["target_audience"]["evidence"][0][
            "url"
        ] = "https://evil.example/video/15"
    business_path = tmp_path / "business.json"
    business_path.write_text(
        json.dumps(business, ensure_ascii=False), encoding="utf-8"
    )
    output = tmp_path / "invalid-final"

    with pytest.raises(pipeline.PipelineError, match="business insight"):
        pipeline.run_pipeline(
            str(collection),
            str(output),
            template_text=_minimal_template(),
            with_taxonomy_prompt=True,
            classification_results_path=str(classification_path),
            with_business_insights=True,
            business_insight_results_path=str(business_path),
        )

    assert not output.exists()


def test_unobservable_copy_pattern_keeps_final_partial_and_explicit(tmp_path):
    pipeline = _pipeline_module()
    collection, collection_digest = _collection(tmp_path)
    classification_payload = _classification_payload()
    classification_path = tmp_path / "taxonomy.json"
    classification_path.write_bytes(classification_payload)
    classification_digest = hashlib.sha256(classification_payload).hexdigest()
    business = _business_result(collection_digest, classification_digest)
    opening = next(
        pattern
        for pattern in business["performance_patterns"]
        if pattern["id"] == "high-opening"
    )
    opening.update(
        {
            "observability": "not_observable",
            "basis": "unobservable",
            "statement": None,
            "evidence": [],
            "limitation": "公开样本没有可核验的文案开头。",
        }
    )
    business_path = tmp_path / "business.json"
    business_path.write_text(
        json.dumps(business, ensure_ascii=False), encoding="utf-8"
    )
    output = tmp_path / "partial-final"

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        with_taxonomy_prompt=True,
        classification_results_path=str(classification_path),
        with_business_insights=True,
        business_insight_results_path=str(business_path),
    )

    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    report = (output / "account-analysis-report.md").read_text(encoding="utf-8")
    assert result.task_status == "PARTIAL"
    assert "PARTIAL_BUSINESS_INSIGHTS" in task["partial_reasons"]
    assert "公开样本没有可核验的文案开头" in report
    assert "视频开头" not in report


def test_business_results_do_not_change_deterministic_analysis_objects():
    profile = _profile()
    rows = [normalize.normalize_post(post)[0] for post in _posts()]
    classifications = [_classification(f"{index:02d}") for index in range(1, 16)]
    classification_payload = _classification_payload()
    classification_digest = hashlib.sha256(classification_payload).hexdigest()
    params = {"analysis_goal": "分析播放表现与内容策略"}
    baseline = analyze.analyze_in_memory(
        profile,
        rows,
        params,
        classification_results=classifications,
    ).analysis
    enriched = analyze.analyze_in_memory(
        profile,
        rows,
        params,
        classification_results=classifications,
        with_business_insights=True,
        business_insight_results=_business_result("a" * 64, classification_digest),
        collection_commit_sha256="a" * 64,
        classification_results_sha256=classification_digest,
    ).analysis

    frozen_keys = (
        "metric_summary",
        "engagement",
        "performance_meta",
        "high_performance",
        "low_performance",
        "core_insights",
        "classification_breakdown",
        "high_low_feature_comparison",
    )
    assert {key: baseline[key] for key in frozen_keys} == {
        key: enriched[key] for key in frozen_keys
    }
def test_business_claim_support_public_api():
    public_validator = getattr(analyze, "validate_business_claim_support", None)
    assert callable(public_validator)
    with pytest.raises(ValueError, match="semantic support"):
        public_validator(
            {
                "statement": "这一需求已验证",
                "evidence": [{"post_id": "1", "excerpt": "单条公开样本"}],
            },
            "claim",
        )
