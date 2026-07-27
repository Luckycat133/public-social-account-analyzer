"""抖音无登录 Web 索引证据导入器。

测试全部离线，只验证证据结构、官方 URL、字段一致性、空值诚实性和任务产物；Agent
负责在 Web 连接器结果中核验真实来源与作品区，导入器本身不联网。
"""

import copy
import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

import analyze
import import_index_snapshot as importer
import immutable_workspace as immutable
import normalize
import render_report
import run_pipeline


PROFILE_ID = "MS4wLjABAAAAexample-sec-uid"
PROFILE_URL = f"https://www.douyin.com/user/{PROFILE_ID}"
OBSERVED_AT = "2026-07-24T18:07:51+08:00"


def _account(name="大漠叔叔"):
    return {
        "account_id": PROFILE_ID,
        "account_name": name,
        "bio": None,
        "verified": None,
        "followers": None,
        "post_count": None,
        "platform_metrics": {"douyin_id": "damashushu"},
    }


def _jingxuan_evidence():
    return {
        "schema_version": 1,
        "platform": "douyin",
        "profile_url": PROFILE_URL,
        "account": _account(),
        "source_kind": "douyin_jingxuan",
        "source_url": "https://jingxuan.douyin.com/m/video/7646317821839805739",
        "observed_at": OBSERVED_AT,
        "snapshot_crawled_at": "2026-07-18",
        "upstream_stop_reason": "LOGIN_REQUIRED",
        "posts": [
            {
                "post_id": "7646317821839805739",
                "post_url": "https://jingxuan.douyin.com/m/video/7646317821839805739",
                "author_name": "大漠叔叔",
                "title": "去海边看看",
                "published_at": "2026-07-18",
                "duration_seconds": 61,
                "likes": None,
                "comments": None,
                "favorites": None,
                "shares": None,
            },
            {
                "post_id": "7642203176673873203",
                "post_url": "https://jingxuan.douyin.com/m/video/7642203176673873203",
                "author_name": "大漠叔叔",
                "title": "第二条公开作品",
                "published_at": "2026-07-07T12:00:00+08:00",
                "duration_seconds": 42,
                "likes": 123,
                "comments": None,
                "favorites": None,
                "shares": None,
            },
        ],
    }


def _search_evidence():
    account = _account("中国政府网")
    account["platform_metrics"] = {
        "douyin_id": "zgzfw",
        "total_likes": 73_000_000,
    }
    return {
        "schema_version": 1,
        "platform": "douyin",
        "profile_url": PROFILE_URL,
        "account": account,
        "source_kind": "douyin_search_index",
        "source_url": PROFILE_URL,
        "observed_at": OBSERVED_AT,
        "snapshot_crawled_at": None,
        "snapshot_age_label": "约 6 个月前",
        "upstream_stop_reason": "LOGIN_REQUIRED",
        "posts": [
            {
                "post_id": None,
                "post_url": None,
                "author_name": "中国政府网",
                "title": "2026年高考全国统考于6月7日开始举行",
                "published_at": None,
                "duration_seconds": None,
                "likes": 523,
                "comments": None,
                "favorites": None,
                "shares": None,
            },
            {
                "post_id": None,
                "post_url": None,
                "author_name": "中国政府网",
                "title": "今年首批超长期特别国债支持设备更新资金下达",
                "published_at": None,
                "duration_seconds": None,
                "likes": 311,
                "comments": None,
                "favorites": None,
                "shares": None,
            },
        ],
    }


def _sealed_profile_collection(tmp_path, *, profile=None, task=None):
    target = tmp_path / "direct-profile"
    direct_profile = {
        "platform": "douyin",
        "account_id": "zgzfw-current",
        "account_name": "中国政府网（当前）",
        "profile_url": PROFILE_URL,
        "bio": "当前公开简介",
        "verified": True,
        "followers": 12_345_678,
        "post_count": 8_765,
        "level": None,
        "platform_metrics": {
            "sec_uid": PROFILE_ID,
            "unique_id": "zgzfw-current",
            "total_likes": 88_000_000,
        },
        "collected_at": "2026-07-25T09:00:00+08:00",
        "field_visibility": {
            "account_id": "visible",
            "account_name": "visible",
            "bio": "visible",
            "verified": "visible",
            "followers": "visible",
            "post_count": "visible",
        },
    }
    direct_profile.update(profile or {})
    direct_task = {
        "task_id": "douyin-direct-profile-task",
        "platform": "douyin",
        "profile_url": PROFILE_URL,
        "task_status": "FAILED",
        "stop_reason": "LOGIN_REQUIRED",
        "collected_count": 0,
    }
    direct_task.update(task or {})
    artifacts = {
        "source/profile.json": json.dumps(direct_profile, ensure_ascii=False),
        "source/posts.jsonl": "",
        "task.json": json.dumps(direct_task, ensure_ascii=False),
        "collection-report.md": "# direct profile\n",
    }
    reservation = immutable.ImmutableWorkspace.reserve(
        str(target),
        allowed_artifacts=frozenset(
            {
                "source/profile.json",
                "source/posts.jsonl",
                "source/comments.jsonl",
                "normalized-posts.csv",
                "task.json",
                "collection-report.md",
            }
        ),
    )
    try:
        for relative, payload in artifacts.items():
            with reservation.open_text(relative) as handle:
                handle.write(payload)
        digest = reservation.commit()
    finally:
        reservation.close()
    return target, digest


def test_jingxuan_evidence_keeps_real_ids_urls_and_partial_status():
    result = importer.validate_evidence(_jingxuan_evidence(), limit=1)

    assert result["profile"]["account_name"] == "大漠叔叔"
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert post["post_id"] == "7646317821839805739"
    assert post["post_url"].endswith("/7646317821839805739")
    assert post["published_at"] == "2026-07-18T00:00:00+08:00"
    assert post["collection_status"] == "PARTIAL"
    assert post["collection_status_source"] == "declared"
    assert post["is_pinned"] is None
    assert post["is_repost"] is None
    assert post["is_promoted"] is None
    assert post["platform_metrics"] == {
        "collection_source": "douyin_jingxuan",
        "platform_post_id_known": True,
        "local_record_key": False,
        "item_url_known": True,
        "source_rank": 1,
        "published_at_precision": "date",
    }


def test_search_index_uses_deterministic_disclosed_local_keys():
    first = importer.validate_evidence(_search_evidence(), limit=30)
    second = importer.validate_evidence(copy.deepcopy(_search_evidence()), limit=30)

    assert [p["post_id"] for p in first["posts"]] == [
        p["post_id"] for p in second["posts"]
    ]
    assert all(p["post_id"].startswith("idx-") for p in first["posts"])
    assert len(set(p["post_id"] for p in first["posts"])) == 2
    for post in first["posts"]:
        assert post["post_url"] == PROFILE_URL
        assert post["source_url"] == PROFILE_URL
        assert post["published_at"] is None
        assert post["content_type"] == "other"
        assert post["collection_status"] == "PARTIAL"
        assert post["collection_status_source"] == "declared"
        assert post["is_pinned"] is None
        assert post["is_repost"] is None
        assert post["is_promoted"] is None
        assert post["platform_metrics"]["platform_post_id_known"] is False
        assert post["platform_metrics"]["local_record_key"] is True
        assert post["platform_metrics"]["item_url_known"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["posts"][0].update(author_name="同名但不是目标账号"), "author_name"),
        (lambda data: data.update(source_url="https://example.com/result"), "source_url"),
        (lambda data: data.update(profile_url="http://www.douyin.com/user/insecure"), "profile_url"),
        (lambda data: data["account"].update(account_id="wrong-id"), "account_id"),
        (lambda data: data["posts"][0].update(post_url="https://jingxuan.douyin.com/m/video/999"), "post_id"),
        (lambda data: data["posts"][0].update(likes=-1), "likes"),
        (lambda data: data.update(observed_at="2026-07-24T18:07:51"), "observed_at"),
    ],
)
def test_invalid_identity_provenance_and_values_are_rejected(mutate, message):
    evidence = _jingxuan_evidence()
    mutate(evidence)
    with pytest.raises(importer.EvidenceError, match=message):
        importer.validate_evidence(evidence, limit=30)


def test_source_kind_contracts_cannot_be_blended():
    search = _search_evidence()
    search["posts"][0]["post_id"] = "123"
    with pytest.raises(importer.EvidenceError, match="post_id"):
        importer.validate_evidence(search, limit=30)

    selected = _jingxuan_evidence()
    selected["posts"][0]["post_id"] = None
    with pytest.raises(importer.EvidenceError, match="post_id"):
        importer.validate_evidence(selected, limit=30)


def test_limit_does_not_skip_invalid_evidence_later_in_the_batch():
    evidence = _search_evidence()
    evidence["posts"][1]["author_name"] = "错误作者"
    with pytest.raises(importer.EvidenceError, match="author_name"):
        importer.validate_evidence(evidence, limit=1)


@pytest.mark.parametrize(
    ("profile_url", "account_id"),
    [
        ("https://jingxuan.douyin.com/user/example", "example"),
        ("https://www.douyin.com/user/..", ".."),
        ("https://www.douyin.com/user/%2e%2e", "%2e%2e"),
    ],
)
def test_profile_requires_main_host_and_safe_account_id(profile_url, account_id):
    evidence = _search_evidence()
    evidence["profile_url"] = profile_url
    evidence["source_url"] = profile_url
    evidence["account"]["account_id"] = account_id
    with pytest.raises(importer.EvidenceError, match="profile_url"):
        importer.validate_evidence(evidence, limit=30)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.update(snapshot_crawled_at="2027-01-01"), "snapshot_crawled_at"),
        (lambda data: data["posts"][0].update(published_at="2028-01-01"), "published_at"),
        (
            lambda data: data["account"]["platform_metrics"].update(
                latest_post_at="2028-01-01T00:00:00+08:00"
            ),
            "latest_post_at",
        ),
    ],
)
def test_evidence_timestamps_cannot_be_after_observation(mutate, message):
    evidence = _jingxuan_evidence()
    mutate(evidence)
    with pytest.raises(importer.EvidenceError, match=message):
        importer.validate_evidence(evidence, limit=30)


@pytest.mark.parametrize(
    "url",
    [
        "https://notdouyin.com/user/example",
        "https://douyin.com.evil.example/user/example",
        "https://user@www.douyin.com/user/example",
        "https://www.douyin.com:8443/user/example",
        "https://www.douyin.com/user/example?token=secret",
    ],
)
def test_profile_url_rejects_lookalikes_credentials_ports_and_queries(url):
    evidence = _search_evidence()
    evidence["profile_url"] = url
    evidence["source_url"] = url
    evidence["account"]["account_id"] = "example"
    with pytest.raises(importer.EvidenceError, match="profile_url"):
        importer.validate_evidence(evidence, limit=30)


def test_boolean_metric_is_not_accepted_as_an_integer():
    evidence = _search_evidence()
    evidence["posts"][0]["likes"] = True
    with pytest.raises(importer.EvidenceError, match="likes"):
        importer.validate_evidence(evidence, limit=30)


@pytest.mark.parametrize("field", ["coins", "danmaku"])
def test_douyin_only_metrics_cannot_be_fabricated(field):
    evidence = _jingxuan_evidence()
    evidence["posts"][0][field] = 1
    with pytest.raises(importer.EvidenceError, match=field):
        importer.validate_evidence(evidence, limit=30)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("published_at", "2026-01-01"),
        ("duration_seconds", 12),
        ("views", 100),
        ("comments", 2),
        ("favorites", 3),
        ("shares", 4),
    ],
)
def test_search_index_only_accepts_card_visible_likes(field, value):
    evidence = _search_evidence()
    evidence["posts"][0][field] = value

    with pytest.raises(importer.EvidenceError, match=field):
        importer.validate_evidence(evidence, limit=30)


def test_persisted_evidence_is_whitelisted_not_a_connector_dump(tmp_path):
    evidence = _search_evidence()
    evidence["internal_connector_ref"] = "turn-secret-ref"
    evidence["account"]["private_cookie"] = "session-secret"
    evidence["posts"][0]["raw_html"] = "<secret>"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    out = tmp_path / "task"

    importer.run(str(evidence_path), str(out), limit=1)

    persisted = (out / "source" / "index-evidence.json").read_text(encoding="utf-8")
    assert "turn-secret-ref" not in persisted
    assert "session-secret" not in persisted
    assert "<secret>" not in persisted


def test_collection_report_escapes_untrusted_snapshot_label(tmp_path):
    evidence = _search_evidence()
    evidence["snapshot_age_label"] = "![pixel](https://tracker.invalid/p.png) | injected"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    out = tmp_path / "task"

    importer.run(str(evidence_path), str(out), limit=1)

    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "![pixel](" not in report
    assert "\\!\\[pixel\\](https://tracker.invalid/p.png) \\| injected" in report


def test_cli_returns_three_for_empty_evidence(tmp_path, capsys):
    evidence = _search_evidence()
    evidence["posts"] = []
    evidence_path = tmp_path / "empty.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    rc = importer.main([
        "--evidence", str(evidence_path),
        "--out", str(tmp_path / "task"),
    ])

    assert rc == 3
    assert "没有可导入作品" in capsys.readouterr().err
    assert not (tmp_path / "task").exists()


def test_run_writes_compatible_partial_workspace(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "task"

    summary = importer.run(str(evidence_path), str(out), limit=1)

    assert summary == {
        "task_status": "PARTIAL",
        "stop_reason": "LOGIN_REQUIRED",
        "collected_count": 1,
        "collection_source": "douyin_search_index",
        "output_dir": str(out.resolve()),
    }
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "LOGIN_REQUIRED"
    assert task["diagnostic_code"] == "SANDBOX_INDEX_FALLBACK"
    assert task["requested_limit"] == 1
    assert task["collected_count"] == 1

    profile = json.loads((out / "source" / "profile.json").read_text(encoding="utf-8"))
    assert profile["platform_metrics"]["collection_source"] == "douyin_search_index"
    rows = (out / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["likes"] == 523
    assert (out / "source" / "index-evidence.json").is_file()
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "索引快照" in report
    assert "不是抖音实时完整作品列表" in report


def test_index_task_persists_task_id_goal_and_committed_manifest(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "task"

    importer.run(
        str(evidence_path),
        str(out),
        limit=1,
        analysis_goal="分析公开索引选题",
    )

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["analysis_goal"] == "分析公开索引选题"
    assert isinstance(task["task_id"], str) and task["task_id"]
    assert (out / "manifest.json").is_file()
    assert (out / ".complete").is_file()
    immutable.verify_committed_workspace(
        str(out), allowed_artifacts=importer._INDEX_ARTIFACTS
    )


def test_index_run_normalizes_date_window_and_keeps_only_known_in_range_posts(
    tmp_path,
):
    evidence = _jingxuan_evidence()
    evidence["posts"].reverse()
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "task"

    summary = importer.run(
        str(evidence_path),
        str(out),
        limit=1,
        date_from="2026-07-10",
        date_to="2026-07-20",
    )

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    posts = [
        json.loads(line)
        for line in (out / "source" / "posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert task["date_from"] == "2026-07-10T00:00:00+08:00"
    assert task["date_to"] == "2026-07-20T23:59:59+08:00"
    assert task["collected_count"] == summary["collected_count"] == 1
    assert [post["post_id"] for post in posts] == ["7646317821839805739"]


def test_bounded_search_index_with_unknown_dates_is_empty_without_workspace(
    tmp_path,
):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EmptyEvidenceError, match="日期范围"):
        importer.run(
            str(evidence_path),
            str(out),
            date_from="2026-04-25",
            date_to="2026-07-24",
        )

    assert not out.exists()


def test_index_import_overlays_newer_verified_direct_profile(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, source_digest = _sealed_profile_collection(tmp_path)
    out = tmp_path / "task"

    importer.run(
        str(evidence_path),
        str(out),
        profile_collection_dir=str(profile_collection),
    )

    profile = json.loads((out / "source" / "profile.json").read_text())
    task = json.loads((out / "task.json").read_text())
    index_evidence = json.loads(
        (out / "source" / "index-evidence.json").read_text()
    )
    assert profile["account_id"] == "zgzfw-current"
    assert profile["account_name"] == "中国政府网（当前）"
    assert profile["followers"] == 12_345_678
    assert profile["post_count"] == 8_765
    assert profile["platform_metrics"]["total_likes"] == 88_000_000
    assert profile["platform_metrics"]["collection_source"] == (
        "douyin_search_index"
    )
    assert task["profile_overlay"] == {
        "source_format": immutable.FORMAT,
        "source_commit_sha256": source_digest,
        "source_task_id": "douyin-direct-profile-task",
        "collected_at": "2026-07-25T09:00:00+08:00",
        "field_sources": {
            "account_id": "direct_public_collection",
            "account_name": "direct_public_collection",
            "bio": "direct_public_collection",
            "verified": "direct_public_collection",
            "followers": "direct_public_collection",
            "post_count": "direct_public_collection",
            "level": "index_evidence",
            "platform_metrics.douyin_id": "index_evidence",
            "platform_metrics.latest_post_at": "index_evidence",
            "platform_metrics.sec_uid": "direct_public_collection",
            "platform_metrics.total_likes": "direct_public_collection",
            "platform_metrics.uid": "index_evidence",
            "platform_metrics.unique_id": "direct_public_collection",
        },
    }
    assert index_evidence["account"]["account_name"] == "中国政府网"
    assert all(
        post["author_name"] == "中国政府网"
        for post in index_evidence["posts"]
    )


def test_index_import_rejects_profile_overlay_older_than_known_index_snapshot(tmp_path):
    evidence = _search_evidence()
    evidence["snapshot_crawled_at"] = "2026-07-24"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        profile={"collected_at": "2026-07-23T09:00:00+08:00"},
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="较新|时间"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_import_rejects_profile_overlay_not_newer_than_observation(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        profile={"collected_at": "2026-07-24T17:00:00+08:00"},
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="较新|时间"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_import_rejects_same_day_overlay_for_date_precision_snapshot(tmp_path):
    evidence = _search_evidence()
    evidence["snapshot_crawled_at"] = "2026-07-24"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        profile={"collected_at": "2026-07-24T23:00:00+08:00"},
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="较新|时间"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_import_rejects_profile_overlay_without_source_task_id(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        task={"task_id": None},
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="task_id"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_profile_overlay_nulls_do_not_erase_index_profile_values(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        profile={
            "bio": None,
            "followers": None,
            "platform_metrics": {
                "sec_uid": PROFILE_ID,
                "unique_id": "zgzfw-current",
                "total_likes": None,
            },
        },
    )
    out = tmp_path / "task"

    importer.run(
        str(evidence_path),
        str(out),
        profile_collection_dir=str(profile_collection),
    )

    profile = json.loads((out / "source" / "profile.json").read_text())
    task = json.loads((out / "task.json").read_text())
    assert profile["platform_metrics"]["total_likes"] == 73_000_000
    assert task["profile_overlay"]["field_sources"][
        "platform_metrics.total_likes"
    ] == "index_evidence"


def test_index_profile_overlay_provenance_reaches_analysis_and_report(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(tmp_path)
    collection = tmp_path / "collection"
    output = tmp_path / "analysis"
    importer.run(
        str(evidence_path),
        str(collection),
        profile_collection_dir=str(profile_collection),
    )

    run_pipeline.run_pipeline(str(collection), str(output))

    collection_task = json.loads((collection / "task.json").read_text())
    analysis = json.loads((output / "analysis.json").read_text())
    report = (output / "account-analysis-report.md").read_text()
    assert analysis["meta"]["profile_overlay"] == collection_task[
        "profile_overlay"
    ]
    assert "当前直连公开资料" in report
    assert "较旧索引作品" in report


def test_index_profile_overlay_rejects_cross_account_task_before_output(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        task={"profile_url": "https://www.douyin.com/user/another-account"},
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="账号.*不一致"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_profile_overlay_rejects_authorized_owner_collection(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        task={"collection_source": "douyin_openapi_token_owner"},
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="匿名公开采集"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_profile_overlay_rejects_conflicting_sec_uid_before_output(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(
        tmp_path,
        profile={
            "platform_metrics": {
                "sec_uid": "another-account",
                "unique_id": "zgzfw-current",
            }
        },
    )
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="绑定证据"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


def test_index_profile_overlay_rejects_uncommitted_directory_before_output(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    uncommitted = tmp_path / "uncommitted"
    (uncommitted / "source").mkdir(parents=True)
    (uncommitted / "source" / "profile.json").write_text("{}")
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="已提交采集工作区"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(uncommitted),
        )

    assert not out.exists()


def test_index_profile_overlay_rejects_tampered_commit_before_output(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    profile_collection, _ = _sealed_profile_collection(tmp_path)
    profile_path = profile_collection / "source" / "profile.json"
    profile_path.chmod(0o600)
    profile_path.write_text("{}", encoding="utf-8")
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="已提交采集工作区"):
        importer.run(
            str(evidence_path),
            str(out),
            profile_collection_dir=str(profile_collection),
        )

    assert not out.exists()


@pytest.mark.parametrize("goal", [123, "", " ", "x" * 501, "a\nb", "a\x00b"])
def test_index_rejects_invalid_goal_before_evidence_read_or_output(
    tmp_path, goal
):
    out = tmp_path / "task"

    with pytest.raises(importer.EvidenceError, match="analysis_goal"):
        importer.run(
            str(tmp_path / "missing-evidence.json"),
            str(out),
            analysis_goal=goal,
        )

    assert not out.exists()


def test_index_cli_forwards_analysis_goal_and_date_window(monkeypatch, capsys):
    captured = {}

    def fake_run(
        evidence,
        out,
        *,
        limit,
        analysis_goal,
        date_from,
        date_to,
        profile_collection_dir,
    ):
        captured.update(
            evidence=evidence,
            out=out,
            limit=limit,
            analysis_goal=analysis_goal,
            date_from=date_from,
            date_to=date_to,
            profile_collection_dir=profile_collection_dir,
        )
        return {
            "task_status": "PARTIAL",
            "stop_reason": "LOGIN_REQUIRED",
            "collected_count": 1,
            "collection_source": "douyin_search_index",
            "output_dir": out,
        }

    monkeypatch.setattr(importer, "run", fake_run)

    assert importer.main([
        "--evidence", "evidence.json",
        "--out", "task",
        "--analysis-goal", "分析公开索引",
        "--date-from", "2026-04-25",
        "--date-to", "2026-07-24",
        "--profile-from-collection", "profile-task",
    ]) == 0
    assert captured["analysis_goal"] == "分析公开索引"
    assert captured["date_from"] == "2026-04-25"
    assert captured["date_to"] == "2026-07-24"
    assert captured["profile_collection_dir"] == "profile-task"
    assert capsys.readouterr().err == ""


def test_index_refuses_existing_empty_workspace(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_search_evidence()), encoding="utf-8")
    out = tmp_path / "task"
    out.mkdir()

    with pytest.raises(importer.EvidenceError, match="已存在|占用"):
        importer.run(str(evidence_path), str(out), limit=1)

    assert list(out.iterdir()) == []


def test_index_rejects_symlink_ancestor_without_writing_outside(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_search_evidence()), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(importer.EvidenceError, match="不安全|符号链接"):
        importer.run(str(evidence_path), str(linked_parent / "task"), limit=1)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in outside.iterdir()) == ["keep.txt"]


def test_run_refuses_to_overwrite_nonempty_workspace(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_search_evidence()), encoding="utf-8")
    out = tmp_path / "task"
    out.mkdir()
    (out / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(importer.EvidenceError, match="非空"):
        importer.run(str(evidence_path), str(out), limit=30)

    assert (out / "keep.txt").read_text(encoding="utf-8") == "user data"


@pytest.mark.parametrize("limit", [0, 101, True])
def test_limit_must_be_an_integer_between_one_and_one_hundred(limit):
    with pytest.raises(importer.EvidenceError, match="limit"):
        importer.validate_evidence(_search_evidence(), limit=limit)


def test_normalize_preserves_index_provenance_columns():
    raw = importer.validate_evidence(_search_evidence(), limit=1)["posts"][0]

    row, errors = normalize.normalize_post(raw)

    assert errors == []
    assert row["collection_source"] == "douyin_search_index"
    assert row["platform_post_id_known"] is False
    assert row["local_record_key"] is True
    assert row["item_url_known"] is False
    assert row["source_rank"] == 1
    assert row["published_at_precision"] == "unknown"
    for field in (
        "collection_source",
        "platform_post_id_known",
        "local_record_key",
        "item_url_known",
        "source_rank",
        "published_at_precision",
    ):
        assert field in normalize.CSV_COLUMNS


def test_date_only_precision_does_not_fabricate_midnight_distribution():
    cadence = analyze.compute_cadence([
        {
            "published_at": datetime.fromisoformat("2026-07-18T00:00:00+08:00"),
            "published_at_precision": "date",
        }
    ])

    assert sum(cadence["hour_distribution"].values()) == 0
    assert cadence["time_precision"]["date_only"] == 1
    assert cadence["time_precision"]["datetime"] == 0
    assert "具体时段" in cadence["note"]
    assert analyze.format_published_at_for_boundary({
        "published_at": datetime.fromisoformat("2026-07-18T00:00:00+08:00"),
        "published_at_precision": "date",
    }) == "2026-07-18"


def test_missing_dates_do_not_fabricate_weekly_average():
    cadence = analyze.compute_cadence([
        {"published_at": None, "published_at_precision": "unknown"},
        {"published_at": None, "published_at_precision": "unknown"},
    ])

    assert cadence["weekly_avg"] is None
    assert cadence["coverage_weeks"] == 0


def test_nonexhaustive_index_keeps_date_counts_but_suppresses_cadence_claims():
    cadence = analyze.compute_cadence([
        {
            "published_at": datetime.fromisoformat("2026-07-01T09:00:00+08:00"),
            "published_at_precision": "datetime",
        },
        {
            "published_at": datetime.fromisoformat("2026-07-08T10:00:00+08:00"),
            "published_at_precision": "datetime",
        },
    ])

    restricted = analyze.restrict_nonexhaustive_index_cadence(cadence)

    assert sum(restricted["weekday_distribution"].values()) == 2
    assert restricted["weekly_avg"] is None
    assert restricted["median_interval_hours"] is None
    assert restricted["longest_gap_hours"] is None
    assert restricted["seasonal_intensity"] is None
    assert restricted["break_month_share"] is None
    assert restricted["cadence_inference_allowed"] is False
    assert "非穷尽索引样本" in restricted["note"]


def test_search_index_uses_visible_likes_not_inferred_total_engagement():
    raw = importer.validate_evidence(_search_evidence(), limit=2)["posts"]
    rows = [normalize.normalize_post(post)[0] for post in raw]
    posts = analyze.build_posts(rows)

    metric, note = analyze.choose_main_metric(None, posts)

    assert metric == "likes"
    assert "搜索索引" in note
    assert analyze.follower_based_ratio(posts[0], followers=22_000_000) is None


def test_analysis_record_keeps_title_and_does_not_claim_profile_as_item_url():
    raw = importer.validate_evidence(_search_evidence(), limit=1)["posts"][0]
    normalized = normalize.normalize_post(raw)[0]
    post = analyze.build_posts([normalized])[0]
    medians = analyze.compute_medians([post])

    record = analyze.build_post_records([post], medians, followers=None)[0]

    assert record["title"] == raw["title"]
    assert record["collection_source"] == "douyin_search_index"
    assert record["item_url_known"] is False
    assert record["post_url"] is None
    assert record["evidence_url"] == PROFILE_URL


def test_render_discloses_partial_index_source_and_suppresses_fake_item_links():
    analysis = {
        "meta": {
            "account_name": "中国政府网",
            "platform": "douyin",
            "profile_url": PROFILE_URL,
            "task_status": "PARTIAL",
            "stop_reason": "LOGIN_REQUIRED",
            "collection_source": "douyin_search_index",
            "snapshot_age_label": "约 6 个月前",
            "evidence_is_exhaustive": False,
        },
        "sample_boundary": {"valid": 1},
        "posts": [
            {
                "post_id": "idx-example",
                "post_url": None,
                "evidence_url": PROFILE_URL,
                "item_url_known": False,
            }
        ],
    }
    profile = {"profile_url": PROFILE_URL, "field_visibility": {}}

    task_md, _ = render_report.build_task_info(analysis, profile, [])
    limits_md, _ = render_report.build_sample_limits(analysis, profile)
    sources_md, _ = render_report.build_sources(analysis, profile)

    assert "PARTIAL" in task_md
    assert "LOGIN_REQUIRED" in task_md
    assert "douyin_search_index" in task_md
    assert "约 6 个月前" in task_md
    assert "索引快照" in limits_md and "非实时" in limits_md
    assert "idx-example" not in sources_md
    assert sources_md.count(PROFILE_URL) == 1


def test_search_index_runs_through_immutable_analysis_pipeline(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_search_evidence(), ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "task"
    importer.run(str(evidence_path), str(out), limit=2)
    collection_digest = immutable.verify_committed_workspace(
        str(out), allowed_artifacts=importer._INDEX_ARTIFACTS
    )["commit_sha256"]
    derived = tmp_path / "analysis"

    result = run_pipeline.run_pipeline(str(out), str(derived))
    rows = list(
        csv.DictReader(
            (derived / "normalized-posts.csv").read_text(encoding="utf-8").splitlines()
        )
    )
    assert rows[0]["collection_source"] == "douyin_search_index"
    assert rows[0]["item_url_known"] == "false"
    assert result.task_status == "PARTIAL"
    assert immutable.verify_committed_workspace(
        str(out), allowed_artifacts=importer._INDEX_ARTIFACTS
    )["commit_sha256"] == collection_digest

    analysis = json.loads((derived / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["meta"]["task_status"] == "PARTIAL"
    assert analysis["meta"]["collection_source"] == "douyin_search_index"
    assert analysis["meta"]["main_sort_metric"] == "likes"
    assert analysis["publish_cadence"]["weekly_avg"] is None
    assert analysis["publish_cadence"]["cadence_inference_allowed"] is False
    assert all(post["post_url"] is None for post in analysis["posts"])
    assert all(post["title"] for post in analysis["posts"])

    report = (derived / "account-analysis-report.md").read_text(encoding="utf-8")
    dashboard = (derived / "dashboard.html").read_text(encoding="utf-8")
    for rendered in (report, dashboard):
        assert "douyin_search_index" in rendered
        assert "PARTIAL" in rendered
        assert "非实时" in rendered
        assert "非穷尽索引样本" in rendered
    assert report.count(PROFILE_URL) >= 1
    assert "idx-" not in report.split("## 12. 来源链接", 1)[-1]
