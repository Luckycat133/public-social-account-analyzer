"""Deterministic comment-evidence analysis contracts (Task C2)."""

from __future__ import annotations

import copy
import json

import pytest

import analyze
import normalize


COMMENT_FIELDS = {
    "comment_id",
    "parent_post_id",
    "parent_post_url",
    "author",
    "text",
    "likes",
    "published_at",
    "collected_at",
}


def _post(post_id: str, **overrides) -> dict:
    post = {
        "platform": "douyin",
        "post_id": post_id,
        "post_url": f"https://www.douyin.com/video/{post_id}",
        "published_at": "2026-07-01T08:00:00+08:00",
        "content_type": "video",
        "collection_status": "SUCCESS",
        "likes": 10,
        "views": 100,
    }
    post.update(overrides)
    return normalize.normalize_post(post)[0]


def _comment(
    comment_id: str,
    parent_post_id: str = "1001",
    **overrides,
) -> dict:
    value = {
        "comment_id": comment_id,
        "parent_post_id": parent_post_id,
        "parent_post_url": (
            f"https://www.douyin.com/video/{parent_post_id}"
        ),
        "author": "公开作者",
        "text": f"评论 {comment_id}",
        "likes": 1,
        "published_at": "2026-07-02T09:00:00+08:00",
        "collected_at": "2026-07-03T10:00:00+08:00",
    }
    value.update(overrides)
    return value


def _jsonl(*comments: dict) -> bytes:
    return "".join(
        json.dumps(comment, ensure_ascii=False, allow_nan=True) + "\n"
        for comment in comments
    ).encode("utf-8")


def _ledger(
    *,
    attempted_posts: int,
    comments_collected: int,
    empty_results: int,
    failures: int,
    stop_reason=None,
) -> dict:
    value = {
        "attempted_posts": attempted_posts,
        "comments_collected": comments_collected,
        "empty_results": empty_results,
        "failures": failures,
        "per_post_limit": 20,
    }
    if stop_reason is not None:
        value["stop_reason"] = stop_reason
    return value


def _analyze(
    rows: list[dict],
    *,
    include_comments=False,
    comments_payload=None,
    ledger=None,
) -> dict:
    params = {
        "task_id": "comment-contract",
        "platform": "douyin",
        "include_comments": include_comments,
    }
    if ledger is not None:
        params["comment_collection"] = ledger
    return analyze.analyze_in_memory(
        {
            "platform": "douyin",
            "account_name": "公开账号",
            "profile_url": "https://www.douyin.com/user/example",
        },
        rows,
        params,
        comments_payload=comments_payload,
    ).analysis["comment_analysis"]


def test_comment_analysis_not_requested_has_stable_complete_contract():
    result = _analyze([_post("1001")])

    assert set(result) == {
        "schema_version",
        "status",
        "requested",
        "sampled_comment_count",
        "eligible_parent_posts",
        "covered_parent_posts",
        "parent_coverage_rate",
        "collection_ledger",
        "field_coverage",
        "representative_selection",
        "representative_comments",
        "semantic",
        "limitations",
    }
    assert result == {
        **result,
        "schema_version": 1,
        "status": "not_requested",
        "requested": False,
        "sampled_comment_count": 0,
        "eligible_parent_posts": 1,
        "covered_parent_posts": 0,
        "parent_coverage_rate": 0.0,
        "collection_ledger": {
            "attempted_posts": 0,
            "comments_collected": 0,
            "empty_results": 0,
            "failures": 0,
            "per_post_limit": 20,
            "stop_reason": None,
        },
        "field_coverage": {
            field: {"present": 0, "total": 0, "rate": None}
            for field in ("author", "text", "likes", "published_at", "collected_at")
        },
        "representative_selection": {
            "max_parent_posts": 3,
            "max_per_parent": 1,
            "order": "visible_likes_desc_then_source_line",
        },
        "representative_comments": [],
        "semantic": {
            "status": "not-applicable",
            "model_version": None,
            "insights": None,
        },
    }
    assert isinstance(result["limitations"], list)
    assert result["limitations"]


def test_comment_analysis_distinguishes_empty_from_unavailable():
    rows = [_post("1001"), _post("1002")]
    empty = _analyze(
        rows,
        include_comments=True,
        comments_payload=b"",
        ledger=_ledger(
            attempted_posts=2,
            comments_collected=0,
            empty_results=2,
            failures=0,
        ),
    )
    unavailable = _analyze(
        rows,
        include_comments=True,
        comments_payload=None,
        ledger=_ledger(
            attempted_posts=1,
            comments_collected=0,
            empty_results=0,
            failures=1,
            stop_reason="VERIFICATION_REQUIRED",
        ),
    )

    assert empty["status"] == "empty"
    assert empty["requested"] is True
    assert empty["parent_coverage_rate"] == 0.0
    assert unavailable["status"] == "unavailable"
    assert unavailable["collection_ledger"]["stop_reason"] == (
        "VERIFICATION_REQUIRED"
    )
    assert unavailable["semantic"] == empty["semantic"] == {
        "status": "not-applicable",
        "model_version": None,
        "insights": None,
    }


def test_incomplete_zero_evidence_without_stop_is_unavailable_not_invalid():
    result = _analyze(
        [_post("1001"), _post("1002")],
        include_comments=True,
        comments_payload=b"",
        ledger=_ledger(
            attempted_posts=1,
            comments_collected=0,
            empty_results=1,
            failures=0,
        ),
    )

    assert result["status"] == "unavailable"


def test_valid_comment_evidence_wins_even_when_parent_attempts_are_incomplete():
    result = _analyze(
        [_post("1001"), _post("1002")],
        include_comments=True,
        comments_payload=_jsonl(_comment("c1")),
        ledger=_ledger(
            attempted_posts=1,
            comments_collected=1,
            empty_results=0,
            failures=0,
        ),
    )

    assert result["status"] == "collected_pending_model"


def test_valid_comments_win_over_failures_and_select_representatives_stably():
    rows = [_post(str(post_id)) for post_id in range(1001, 1006)]
    comments = (
        _comment("c1-null", "1001", likes=None, text="未知点赞"),
        _comment("c1-zero", "1001", likes=0, text="零点赞也可见"),
        _comment(
            "c2-seven",
            "1002",
            likes=7,
            author=None,
            published_at=None,
        ),
        _comment("c3-seven", "1003", likes=7, collected_at=None),
        _comment("c4-high", "1004", likes=100, text="最高"),
    )
    result = _analyze(
        rows,
        include_comments=True,
        comments_payload=_jsonl(*comments),
        ledger=_ledger(
            attempted_posts=5,
            comments_collected=5,
            empty_results=0,
            failures=1,
        ),
    )

    assert result["status"] == "collected_pending_model"
    assert result["sampled_comment_count"] == 5
    assert result["eligible_parent_posts"] == 5
    assert result["covered_parent_posts"] == 4
    assert result["parent_coverage_rate"] == 0.8
    assert result["field_coverage"] == {
        "author": {"present": 4, "total": 5, "rate": 0.8},
        "text": {"present": 5, "total": 5, "rate": 1.0},
        "likes": {"present": 4, "total": 5, "rate": 0.8},
        "published_at": {"present": 4, "total": 5, "rate": 0.8},
        "collected_at": {"present": 4, "total": 5, "rate": 0.8},
    }
    assert [
        (item["comment_id"], item["source_line"])
        for item in result["representative_comments"]
    ] == [("c4-high", 5), ("c2-seven", 3), ("c3-seven", 4)]
    assert all(
        set(item) == COMMENT_FIELDS | {"source_artifact", "source_line"}
        for item in result["representative_comments"]
    )
    assert all(
        item["source_artifact"] == "source/comments.jsonl"
        for item in result["representative_comments"]
    )


def test_representative_selection_treats_zero_likes_as_known():
    result = _analyze(
        [_post("1001")],
        include_comments=True,
        comments_payload=_jsonl(
            _comment("unknown", likes=None, text="未知"),
            _comment("zero", likes=0, text="零"),
        ),
        ledger=_ledger(
            attempted_posts=1,
            comments_collected=2,
            empty_results=0,
            failures=0,
        ),
    )

    assert [
        item["comment_id"] for item in result["representative_comments"]
    ] == ["zero"]


def test_comments_only_bind_to_distinct_valid_unflagged_canonical_parents():
    rows = [
        _post("1001"),
        _post("1001"),
        _post("1002", collection_status="PARTIAL"),
        _post("1003", collection_status="FAILED"),
        _post("1006", collection_status="DELETED"),
        _post("1007", collection_status="RESTRICTED"),
        _post("1004", is_pinned=True),
        _post("1008", is_repost=True),
        _post("1009", is_promoted=True),
        _post("1005", post_url="https://www.douyin.com/user/not-an-item"),
    ]
    result = _analyze(rows)

    assert result["eligible_parent_posts"] == 2


@pytest.mark.parametrize(
    "excluded_parent",
    [
        {"collection_status": "FAILED"},
        {"collection_status": "DELETED"},
        {"collection_status": "RESTRICTED"},
        {"is_pinned": True},
        {"is_repost": True},
        {"is_promoted": True},
    ],
    ids=("failed", "deleted", "restricted", "pinned", "repost", "promoted"),
)
def test_comments_reject_six_classes_of_ineligible_parent(excluded_parent):
    with pytest.raises(ValueError, match="invalid parent anchor"):
        _analyze(
            [_post("1001", **excluded_parent), _post("1002")],
            include_comments=True,
            comments_payload=_jsonl(_comment("excluded", "1001")),
            ledger=_ledger(
                attempted_posts=1,
                comments_collected=1,
                empty_results=0,
                failures=0,
            ),
        )


def test_comments_jsonl_accepts_crlf_and_preserves_unicode_line_separators():
    text = "第一段\u2028第二段\u2029第三段"
    payload = _jsonl(_comment("c1", text=text)).replace(b"\n", b"\r\n")

    result = _analyze(
        [_post("1001")],
        include_comments=True,
        comments_payload=payload,
        ledger=_ledger(
            attempted_posts=1,
            comments_collected=1,
            empty_results=0,
            failures=0,
        ),
    )

    assert result["sampled_comment_count"] == 1
    assert result["representative_comments"][0]["text"] == text


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_comments_jsonl_rejects_unicode_separator_as_record_delimiter(separator):
    first = json.dumps(_comment("c1"), ensure_ascii=False)
    second = json.dumps(_comment("c2"), ensure_ascii=False)
    payload = (first + separator + second).encode("utf-8")

    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        _analyze(
            [_post("1001")],
            include_comments=True,
            comments_payload=payload,
            ledger=_ledger(
                attempted_posts=1,
                comments_collected=2,
                empty_results=0,
                failures=0,
            ),
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"\xff", "UTF-8"),
        (b"\n", "line 1"),
        (b"[]\n", "object"),
        (_jsonl(_comment("c1", extra="forbidden")), "fields"),
        (
            b'{"comment_id":"c1","comment_id":"c2",'
            b'"parent_post_id":"1001",'
            b'"parent_post_url":"https://www.douyin.com/video/1001",'
            b'"author":null,"text":"x","likes":1,'
            b'"published_at":null,"collected_at":null}\n',
            "duplicate",
        ),
        (_jsonl(_comment("bad id")), "comment_id"),
        (_jsonl(_comment("c1", likes=True)), "likes"),
        (_jsonl(_comment("c1", likes=-1)), "likes"),
        (
            _jsonl(_comment("c1", published_at="2026-07-01T08:00:00")),
            "published_at",
        ),
        (
            _jsonl(_comment("c1", collected_at="2026-07-01T08:00:00")),
            "collected_at",
        ),
        (
            _jsonl(
                _comment(
                    "c1",
                    parent_post_url="https://www.douyin.com/video/1001?token=x",
                )
            ),
            "parent",
        ),
        (_jsonl(_comment("c1", parent_post_id="9999")), "parent"),
        (_jsonl(_comment("c1", likes=float("nan"))), "JSON"),
        (_jsonl(_comment("c1", likes=float("inf"))), "JSON"),
    ],
)
def test_comments_jsonl_is_strict_and_fail_closed(payload, message):
    with pytest.raises(ValueError, match=message):
        _analyze(
            [_post("1001")],
            include_comments=True,
            comments_payload=payload,
            ledger=_ledger(
                attempted_posts=1,
                comments_collected=1,
                empty_results=0,
                failures=0,
            ),
        )


def test_comments_reject_missing_field_even_when_nullable():
    value = _comment("c1")
    del value["author"]

    with pytest.raises(ValueError, match="fields"):
        _analyze(
            [_post("1001")],
            include_comments=True,
            comments_payload=_jsonl(value),
            ledger=_ledger(
                attempted_posts=1,
                comments_collected=1,
                empty_results=0,
                failures=0,
            ),
        )


def test_comments_reject_duplicate_id_within_parent():
    with pytest.raises(ValueError, match="duplicate"):
        _analyze(
            [_post("1001")],
            include_comments=True,
            comments_payload=_jsonl(_comment("same"), _comment("same")),
            ledger=_ledger(
                attempted_posts=1,
                comments_collected=2,
                empty_results=0,
                failures=0,
            ),
        )


def test_comments_allow_same_comment_id_on_different_parents():
    result = _analyze(
        [_post("1001"), _post("1002")],
        include_comments=True,
        comments_payload=_jsonl(
            _comment("same", "1001"),
            _comment("same", "1002"),
        ),
        ledger=_ledger(
            attempted_posts=2,
            comments_collected=2,
            empty_results=0,
            failures=0,
        ),
    )

    assert result["covered_parent_posts"] == 2


def test_comments_reject_more_than_twenty_records_per_parent():
    comments = [_comment(f"c{index}") for index in range(21)]

    with pytest.raises(ValueError, match="20"):
        _analyze(
            [_post("1001")],
            include_comments=True,
            comments_payload=_jsonl(*comments),
            ledger=_ledger(
                attempted_posts=1,
                comments_collected=21,
                empty_results=0,
                failures=0,
            ),
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ledger: ledger.update(attempted_posts=True),
        lambda ledger: ledger.update(comments_collected=-1),
        lambda ledger: ledger.update(per_post_limit=19),
        lambda ledger: ledger.update(comments_collected=0),
        lambda ledger: ledger.update(attempted_posts=0),
        lambda ledger: ledger.update(empty_results=1),
        lambda ledger: ledger.update(attempted_posts=2),
        lambda ledger: ledger.update(unexpected=1),
        lambda ledger: ledger.update(stop_reason="PARSER_FAILED"),
    ],
)
def test_comment_collection_ledger_rejects_invalid_or_contradictory_values(
    mutate,
):
    ledger = _ledger(
        attempted_posts=1,
        comments_collected=1,
        empty_results=0,
        failures=0,
    )
    mutate(ledger)

    with pytest.raises(ValueError, match="comment collection ledger"):
        _analyze(
            [_post("1001")],
            include_comments=True,
            comments_payload=_jsonl(_comment("c1")),
            ledger=ledger,
        )


def test_comments_file_is_forbidden_when_sampling_was_not_requested():
    with pytest.raises(ValueError, match="not requested"):
        _analyze(
            [_post("1001")],
            include_comments=False,
            comments_payload=_jsonl(_comment("c1")),
            ledger=None,
        )


def test_comment_analysis_is_pure_and_does_not_mutate_inputs():
    rows = [_post("1001")]
    ledger = _ledger(
        attempted_posts=1,
        comments_collected=1,
        empty_results=0,
        failures=0,
    )
    before_rows = copy.deepcopy(rows)
    before_ledger = copy.deepcopy(ledger)
    payload = _jsonl(_comment("c1"))

    first = _analyze(
        rows,
        include_comments=True,
        comments_payload=payload,
        ledger=ledger,
    )
    second = _analyze(
        rows,
        include_comments=True,
        comments_payload=payload,
        ledger=ledger,
    )

    assert first == second
    assert rows == before_rows
    assert ledger == before_ledger


def test_comment_semantics_never_generate_deterministic_insights():
    result = _analyze(
        [_post("1001")],
        include_comments=True,
        comments_payload=_jsonl(
            _comment("c1", text="重复问题 重复问题 强烈争议 用户需求")
        ),
        ledger=_ledger(
            attempted_posts=1,
            comments_collected=1,
            empty_results=0,
            failures=0,
        ),
    )

    assert result["semantic"] == {
        "status": "not-requested",
        "model_version": None,
        "insights": None,
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert "高频问题" not in serialized
    assert "争议点" not in serialized
    assert "需求洞察" not in serialized
