"""Offline contract tests for the authorized Douyin OpenAPI collector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collect_douyin_authorized import run
from collectors.douyin_openapi import DouyinOpenAPIClient, DouyinOpenAPIError


TOKEN = "secret-openapi-token-123"


def _profile_response():
    return {
        "data": {
            "error_code": 0,
            "open_id": "owner-open-id",
            "union_id": "owner-union-id",
            "nickname": "授权账号",
            "description": "公开简介",
            "avatar": "https://example.test/avatar.png",
        },
        "extra": {"error_code": 0},
    }


def _video(video_id, *, title, create_time, is_top, play_count):
    return {
        "video_id": str(video_id),
        "title": title,
        "create_time": create_time,
        "is_top": is_top,
        "media_type": "video",
        "share_url": (
            f"https://www.douyin.com/video/{video_id}?share_token=discard#fragment"
        ),
        "statistics": {
            "play_count": play_count,
            "digg_count": 12,
            "comment_count": 3,
            "share_count": 4,
            "download_count": 5,
            "forward_count": 6,
        },
    }


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, *, method, url, headers, data=None):
        self.requests.append(
            {"method": method, "url": url, "headers": dict(headers), "data": data}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_profile_uses_fixed_official_endpoint_and_header_token():
    transport = FakeTransport([_profile_response()])

    profile = DouyinOpenAPIClient(TOKEN, transport=transport).collect_profile()

    assert transport.requests == [{
        "method": "POST",
        "url": "https://open.douyin.com/oauth/userinfo/",
        "headers": {
            "Accept": "application/json",
            "access-token": TOKEN,
        },
        "data": b"",
    }]
    assert profile["account_id"] == "owner-open-id"
    assert profile["account_name"] == "授权账号"
    assert profile["bio"] == "公开简介"
    assert profile["platform_metrics"]["union_id"] == "owner-union-id"
    assert TOKEN not in transport.requests[0]["url"]
    assert TOKEN not in json.dumps(profile, ensure_ascii=False)


def test_two_video_pages_map_deduplicate_and_prove_exhaustive():
    first = _video(
        7001, title="第一条 #公开", create_time=1700000000,
        is_top=1, play_count=101,
    )
    duplicate = dict(first, title="重复项不覆盖首见顺序")
    second = _video(
        7002, title="第二条", create_time=1700000100,
        is_top=0, play_count=202,
    )
    transport = FakeTransport([
        {
            "data": {
                "error_code": 0,
                "list": [first],
                "cursor": 20,
                "has_more": 1,
            },
            "extra": {"error_code": 0},
        },
        {
            "data": {
                "error_code": 0,
                "list": [duplicate, second],
                "cursor": 40,
                "has_more": False,
            },
            "extra": {"error_code": 0},
        },
    ])

    posts, coverage = DouyinOpenAPIClient(
        TOKEN, transport=transport
    ).collect_video_pages(limit=None, page_size=20)

    assert [post["post_id"] for post in posts] == ["7001", "7002"]
    assert posts[0] == {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "published_at": "2023-11-15T06:13:20+08:00",
        "content_type": "video",
        "title": "第一条 #公开",
        "text": "第一条 #公开",
        "duration_seconds": None,
        "hashtags": ["公开"],
        "is_pinned": True,
        "is_repost": None,
        "is_promoted": None,
        "collection_status": "SUCCESS",
        "collected_at": posts[0]["collected_at"],
        "source_url": "https://www.douyin.com/video/7001",
        "views": 101,
        "likes": 12,
        "comments": 3,
        "favorites": None,
        "shares": 4,
        "coins": None,
        "danmaku": None,
        "platform_metrics": {
            "download_count": 5,
            "forward_count": 6,
            "media_type": "video",
        },
    }
    assert coverage == {
        "requested_all": True,
        "is_exhaustive": True,
        "terminal_page_observed": True,
        "observed_page_count": 2,
        "observed_post_count": 2,
        "repeated_cursor_count": 0,
        "zero_new_page_count": 0,
        "stop_condition": "terminal_page",
    }
    assert [request["url"] for request in transport.requests] == [
        "https://open.douyin.com/video/list/?cursor=0&count=20",
        "https://open.douyin.com/video/list/?cursor=20&count=20",
    ]
    assert all(TOKEN not in request["url"] for request in transport.requests)


@pytest.mark.parametrize(
    "share_url",
    [
        "http://www.douyin.com/video/7001",
        "https://douyin.example/video/7001",
        "https://www.douyin.com.evil.example/video/7001",
        "https://user:password@www.douyin.com/video/7001",
        "https://www.douyin.com:not-a-port/video/7001",
    ],
)
def test_rejects_non_douyin_https_share_urls_without_leaking_token(share_url):
    item = _video(7001, title="作品", create_time=1700000000, is_top=0, play_count=1)
    item["share_url"] = share_url
    transport = FakeTransport([{
        "data": {"error_code": 0, "list": [item], "cursor": 20, "has_more": 0},
        "extra": {"error_code": 0},
    }])

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(TOKEN, transport=transport).collect_video_pages()

    assert TOKEN not in str(exc_info.value)


@pytest.mark.parametrize(
    "response",
    [
        {"data": {"error_code": 0, "list": {}, "cursor": 20, "has_more": 0}},
        {"data": {"error_code": 0, "list": [], "cursor": 20, "has_more": 2}},
        {"data": {"error_code": 0, "list": [], "cursor": "opaque", "has_more": 0}},
        {
            "data": {
                "error_code": 0,
                "list": [{
                    **_video(
                        7001, title="作品", create_time=1700000000,
                        is_top=0, play_count=1,
                    ),
                    "video_id": "not-numeric",
                }],
                "cursor": 20,
                "has_more": 0,
            }
        },
        {
            "data": {
                "error_code": 0,
                "list": [{
                    **_video(
                        7001, title="作品", create_time=1700000000,
                        is_top=0, play_count=1,
                    ),
                    "create_time": 10**30,
                }],
                "cursor": 20,
                "has_more": 0,
            }
        },
    ],
)
def test_rejects_invalid_list_has_more_cursor_and_video_id(response):
    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, transport=FakeTransport([response])
        ).collect_video_pages()

    assert exc_info.value.error_code == "INVALID_RESPONSE"
    assert exc_info.value.partial_posts == []


def test_api_errors_never_include_token_even_when_transport_echoes_it():
    transport = FakeTransport([RuntimeError(f"failed header access-token={TOKEN}")])

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(TOKEN, transport=transport).collect_profile()

    assert TOKEN not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_rejects_token_echoed_in_mapped_response_fields():
    response = _profile_response()
    response["data"]["description"] = f"unexpected echo {TOKEN}"

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, transport=FakeTransport([response])
        ).collect_profile()

    assert TOKEN not in str(exc_info.value)


def _page(items, *, cursor, has_more, error_code=0):
    return {
        "data": {
            "error_code": error_code,
            "list": items,
            "cursor": cursor,
            "has_more": has_more,
        },
        "extra": {"error_code": 0},
    }


def test_top_level_and_data_level_api_errors_are_sanitized():
    for response in (
        {"error_code": 2190008, "data": {}},
        {"data": {"error_code": TOKEN}},
    ):
        with pytest.raises(DouyinOpenAPIError) as exc_info:
            DouyinOpenAPIClient(
                TOKEN, transport=FakeTransport([response])
            ).collect_profile()
        assert exc_info.value.error_code == "OPENAPI_ERROR"
        assert TOKEN not in str(exc_info.value)


def test_api_error_before_first_page_has_no_partial_items():
    transport = FakeTransport([_page([], cursor=0, has_more=0, error_code=2190008)])

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(TOKEN, transport=transport).collect_video_pages()

    assert exc_info.value.partial_posts == []
    assert exc_info.value.coverage["observed_page_count"] == 0
    assert exc_info.value.coverage["stop_condition"] == "api_error"


def test_api_error_after_first_page_preserves_first_page_items():
    first = _video(7001, title="第一条", create_time=1700000000, is_top=0, play_count=1)
    transport = FakeTransport([
        _page([first], cursor=20, has_more=1),
        _page([], cursor=40, has_more=0, error_code=2190008),
    ])

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(TOKEN, transport=transport).collect_video_pages()

    assert [post["post_id"] for post in exc_info.value.partial_posts] == ["7001"]
    assert exc_info.value.coverage["observed_page_count"] == 1
    assert exc_info.value.coverage["observed_post_count"] == 1
    assert exc_info.value.coverage["is_exhaustive"] is False


def test_repeated_cursor_is_a_non_exhaustive_partial_stop():
    first = _video(7001, title="第一条", create_time=1700000000, is_top=0, play_count=1)
    posts, coverage = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([_page([first], cursor=0, has_more=1)]),
    ).collect_video_pages()

    assert [post["post_id"] for post in posts] == ["7001"]
    assert coverage["is_exhaustive"] is False
    assert coverage["repeated_cursor_count"] == 1
    assert coverage["stop_condition"] == "repeated_cursor"


def test_two_zero_new_pages_stop_even_when_cursor_advances():
    first = _video(7001, title="第一条", create_time=1700000000, is_top=0, play_count=1)
    transport = FakeTransport([
        _page([first], cursor=20, has_more=1),
        _page([first], cursor=40, has_more=1),
        _page([first], cursor=60, has_more=1),
    ])

    posts, coverage = DouyinOpenAPIClient(
        TOKEN, transport=transport
    ).collect_video_pages()

    assert [post["post_id"] for post in posts] == ["7001"]
    assert coverage["zero_new_page_count"] == 2
    assert coverage["stop_condition"] == "repeated_zero_new_page"
    assert coverage["is_exhaustive"] is False


def test_requested_limit_stops_without_claiming_exhaustive():
    first = _video(7001, title="第一条", create_time=1700000000, is_top=0, play_count=1)
    transport = FakeTransport([_page([first], cursor=20, has_more=1)])

    posts, coverage = DouyinOpenAPIClient(
        TOKEN, transport=transport
    ).collect_video_pages(limit=1, page_size=20)

    assert [post["post_id"] for post in posts] == ["7001"]
    assert transport.requests[0]["url"].endswith("?cursor=0&count=1")
    assert coverage["requested_all"] is False
    assert coverage["stop_condition"] == "limit"
    assert coverage["is_exhaustive"] is False


def _artifact_text(out_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            out_dir / "source" / "profile.json",
            out_dir / "source" / "posts.jsonl",
            out_dir / "normalized-posts.csv",
            out_dir / "task.json",
            out_dir / "collection-report.md",
        )
    )


def test_missing_token_fails_before_creating_workspace(tmp_path, capsys):
    out_dir = tmp_path / "authorized"

    rc = run(out_dir=str(out_dir), environ={})

    captured = capsys.readouterr()
    assert rc == 2
    assert not out_dir.exists()
    assert "DOUYIN_OPENAPI_ACCESS_TOKEN" in captured.err


def test_refuses_to_overwrite_existing_workspace_before_api_calls(tmp_path):
    out_dir = tmp_path / "authorized"
    out_dir.mkdir()
    marker = out_dir / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    transport = FakeTransport([RuntimeError("API must not be called")])

    rc = run(
        out_dir=str(out_dir),
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=DouyinOpenAPIClient(TOKEN, transport=transport),
    )

    assert rc == 2
    assert marker.read_text(encoding="utf-8") == "keep"
    assert transport.requests == []


def test_all_writes_standard_completed_artifacts_without_token(tmp_path, capsys):
    out_dir = tmp_path / "authorized"
    video = _video(7001, title="授权作品", create_time=1700000000, is_top=0, play_count=10)
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([video], cursor=20, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert (out_dir / "source" / "profile.json").is_file()
    assert (out_dir / "source" / "posts.jsonl").is_file()
    assert (out_dir / "normalized-posts.csv").is_file()
    assert (out_dir / "task.json").is_file()
    assert (out_dir / "collection-report.md").is_file()
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "COMPLETED"
    assert task["collection_coverage"]["is_exhaustive"] is True
    assert task["collection_source"] == "douyin_openapi_token_owner"
    assert TOKEN not in _artifact_text(out_dir)
    assert TOKEN not in captured.out + captured.err


def test_api_error_after_page_writes_partial_artifacts(tmp_path):
    out_dir = tmp_path / "authorized"
    video = _video(7001, title="已保留", create_time=1700000000, is_top=0, play_count=10)
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([video], cursor=20, has_more=1),
            _page([], cursor=40, has_more=0, error_code=2190008),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    assert rc == 0
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "OPENAPI_ERROR"
    rows = (out_dir / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(row)["post_id"] for row in rows] == ["7001"]


def test_api_error_before_page_writes_failed_standard_artifacts(tmp_path):
    out_dir = tmp_path / "authorized"
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0, error_code=2190008),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    assert rc == 3
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["collected_count"] == 0
    assert _artifact_text(out_dir)


def test_all_repeated_cursor_is_partial_but_limited_request_is_complete(tmp_path):
    video = _video(7001, title="作品", create_time=1700000000, is_top=0, play_count=10)

    all_out = tmp_path / "all"
    all_client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([video], cursor=0, has_more=1),
        ]),
    )
    assert run(
        out_dir=str(all_out), collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN}, client=all_client,
    ) == 0
    all_task = json.loads((all_out / "task.json").read_text(encoding="utf-8"))
    assert all_task["task_status"] == "PARTIAL"

    limited_out = tmp_path / "limited"
    limited_client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([video], cursor=20, has_more=1),
        ]),
    )
    assert run(
        out_dir=str(limited_out), limit=1,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN}, client=limited_client,
    ) == 0
    limited_task = json.loads(
        (limited_out / "task.json").read_text(encoding="utf-8")
    )
    assert limited_task["task_status"] == "COMPLETED"
    assert limited_task["collection_coverage"]["is_exhaustive"] is False
