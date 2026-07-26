"""Offline contract tests for the authorized Douyin OpenAPI collector."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import csv
from pathlib import Path

import pytest

import collect_douyin_authorized as authorized
import analyze
import immutable_workspace as immutable
import collectors.douyin_openapi as openapi
from collect_douyin_authorized import run
from collectors.douyin_openapi import DouyinOpenAPIClient, DouyinOpenAPIError


TOKEN = "secret-openapi-token-123"
OPEN_ID = "owner-open-id"
AUTHORIZED_ENV = {
    "DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN,
    "DOUYIN_OPENAPI_OPEN_ID": OPEN_ID,
}


class _CredentialSubclass(str):
    pass


def _profile_response():
    return {
        "err_no": 0,
        "data": {
            "open_id": OPEN_ID,
            "union_id": "owner-union-id",
            "nickname": "授权账号",
            "description": "公开简介",
            "avatar": "https://example.test/avatar.png",
        },
    }


def _video(video_id, *, title, create_time, is_top, play_count):
    return {
        "video_id": str(video_id),
        "title": title,
        "create_time": create_time,
        "is_top": is_top,
        "media_type": 2,
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
    def __init__(self, responses, hook=None):
        self.responses = list(responses)
        self.requests = []
        self.hook = hook or (lambda stage: None)

    def __call__(self, *, method, url, headers, data=None):
        self.hook("profile" if url.endswith("/oauth/userinfo/") else "pages")
        self.requests.append(
            {"method": method, "url": url, "headers": dict(headers), "data": data}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_profile_uses_fixed_official_endpoint_and_form_credentials():
    transport = FakeTransport([_profile_response()])

    profile = DouyinOpenAPIClient(
        TOKEN, OPEN_ID, transport=transport
    ).collect_profile()

    assert transport.requests == [{
        "method": "POST",
        "url": "https://open.douyin.com/oauth/userinfo/",
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        "data": b"access_token=secret-openapi-token-123&open_id=owner-open-id",
    }]
    assert profile["account_id"] == "owner-open-id"
    assert profile["account_name"] == "授权账号"
    assert profile["bio"] == "公开简介"
    assert profile["platform_metrics"]["union_id"] == "owner-union-id"
    assert TOKEN not in transport.requests[0]["url"]
    assert TOKEN not in json.dumps(profile, ensure_ascii=False)


@pytest.mark.parametrize(
    ("access_token", "open_id", "error_code"),
    [
        ("", OPEN_ID, "TOKEN_MISSING"),
        (" ", OPEN_ID, "TOKEN_MISSING"),
        (_CredentialSubclass(TOKEN), OPEN_ID, "TOKEN_MISSING"),
        (TOKEN, "", "OPEN_ID_MISSING"),
        (TOKEN, " ", "OPEN_ID_MISSING"),
        (TOKEN, "owner\nopen-id", "OPEN_ID_MISSING"),
        (TOKEN, _CredentialSubclass(OPEN_ID), "OPEN_ID_MISSING"),
        (TOKEN, None, "OPEN_ID_MISSING"),
    ],
)
def test_client_rejects_missing_or_blank_credentials(
    access_token, open_id, error_code
):
    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(access_token, open_id)

    assert exc_info.value.error_code == error_code
    assert TOKEN not in str(exc_info.value)


@pytest.mark.parametrize("err_no", [None, 1, "0", 0.0, False])
def test_profile_requires_exact_top_level_integer_zero_err_no(err_no):
    response = _profile_response()
    if err_no is None:
        response.pop("err_no")
    else:
        response["err_no"] = err_no
    response["err_tips"] = f"untrusted server detail {TOKEN}"

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=FakeTransport([response])
        ).collect_profile()

    assert exc_info.value.error_code == "OPENAPI_ERROR"
    _assert_exception_tree_is_sanitized(exc_info.value)


def test_profile_rejects_response_for_a_different_open_id():
    response = _profile_response()
    response["data"]["open_id"] = "different-owner"

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=FakeTransport([response])
        ).collect_profile()

    assert exc_info.value.error_code == "INVALID_RESPONSE"
    assert "different-owner" not in str(exc_info.value)


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
        TOKEN, OPEN_ID, transport=transport
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
        "collection_status_source": "declared",
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
            "media_type": 2,
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
    assert all(request["headers"] == {
        "Accept": "application/json",
        "access-token": TOKEN,
    } for request in transport.requests)
    assert all(request["data"] is None for request in transport.requests)
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
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=transport
        ).collect_video_pages()

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
            TOKEN, OPEN_ID, transport=FakeTransport([response])
        ).collect_video_pages()

    assert exc_info.value.error_code == "INVALID_RESPONSE"
    assert exc_info.value.partial_posts == []


def test_api_errors_never_include_token_even_when_transport_echoes_it():
    transport = FakeTransport([RuntimeError(f"failed header access-token={TOKEN}")])

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=transport
        ).collect_profile()

    assert TOKEN not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def _exception_nodes(error):
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)


def _assert_exception_tree_is_sanitized(error):
    nodes = list(_exception_nodes(error))
    sensitive_text = "\n".join(
        repr((node.args, getattr(node, "doc", None))) for node in nodes
    )
    assert TOKEN not in sensitive_text
    assert len(nodes) == 1
    assert error.__cause__ is None
    assert error.__context__ is None


def test_token_bearing_transport_openapi_error_is_replaced_without_context():
    raw_error = DouyinOpenAPIError(
        TOKEN,
        f"raw transport response {TOKEN}",
        partial_posts=[{"title": TOKEN}],
        coverage={"raw": TOKEN},
    )

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=FakeTransport([raw_error])
        ).collect_profile()

    assert exc_info.value.error_code == "TRANSPORT_ERROR"
    assert exc_info.value.partial_posts == []
    assert exc_info.value.coverage == {}
    _assert_exception_tree_is_sanitized(exc_info.value)


def test_malformed_json_token_is_not_retained_in_json_error_or_context():
    malformed = f'{{"echo":"{TOKEN}"'.encode("utf-8")

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=FakeTransport([malformed])
        ).collect_profile()

    assert exc_info.value.error_code == "INVALID_RESPONSE"
    _assert_exception_tree_is_sanitized(exc_info.value)


def test_default_transport_rejects_redirect_without_forwarding_token(monkeypatch):
    observed = {"opener_used": False, "forwarded_headers": []}

    def build_opener(*handlers):
        observed["opener_used"] = True
        redirect_handler = next(
            handler
            for handler in handlers
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        )

        class RedirectingOpener:
            def open(self, request, timeout):
                redirected = redirect_handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    "https://redirect.example/steal",
                )
                if redirected is not None:
                    observed["forwarded_headers"].append(dict(redirected.headers))
                raise urllib.error.HTTPError(
                    request.full_url, 302, "redirect rejected", {}, None
                )

        return RedirectingOpener()

    monkeypatch.setattr(openapi.urllib.request, "build_opener", build_opener)
    monkeypatch.setattr(
        openapi.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("global urlopen follows redirects"),
    )

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(TOKEN, OPEN_ID).collect_profile()

    assert observed["opener_used"] is True
    assert observed["forwarded_headers"] == []
    _assert_exception_tree_is_sanitized(exc_info.value)


def test_request_rejects_non_fixed_endpoint_before_transport():
    transport = FakeTransport([_profile_response()])
    client = DouyinOpenAPIClient(TOKEN, OPEN_ID, transport=transport)

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        client._request("GET", "https://redirect.example/video/list/")

    assert exc_info.value.error_code == "INVALID_ENDPOINT"
    assert transport.requests == []


def test_rejects_token_echoed_in_mapped_response_fields():
    response = _profile_response()
    response["data"]["description"] = f"unexpected echo {TOKEN}"

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=FakeTransport([response])
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
                TOKEN, OPEN_ID, transport=FakeTransport([response])
            ).collect_profile()
        assert exc_info.value.error_code == "OPENAPI_ERROR"
        assert TOKEN not in str(exc_info.value)


def test_float_zero_error_code_is_not_accepted_as_exact_success():
    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN,
            OPEN_ID,
            transport=FakeTransport([{
                "data": {**_profile_response()["data"], "error_code": 0.0}
            }]),
        ).collect_profile()

    assert exc_info.value.error_code == "OPENAPI_ERROR"


def test_api_error_before_first_page_has_no_partial_items():
    transport = FakeTransport([_page([], cursor=0, has_more=0, error_code=2190008)])

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=transport
        ).collect_video_pages()

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
        DouyinOpenAPIClient(
            TOKEN, OPEN_ID, transport=transport
        ).collect_video_pages()

    assert [post["post_id"] for post in exc_info.value.partial_posts] == ["7001"]
    assert exc_info.value.coverage["observed_page_count"] == 1
    assert exc_info.value.coverage["observed_post_count"] == 1
    assert exc_info.value.coverage["is_exhaustive"] is False


def test_repeated_cursor_is_a_non_exhaustive_partial_stop():
    first = _video(7001, title="第一条", create_time=1700000000, is_top=0, play_count=1)
    posts, coverage = DouyinOpenAPIClient(
        TOKEN,
        OPEN_ID,
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
        TOKEN, OPEN_ID, transport=transport
    ).collect_video_pages()

    assert [post["post_id"] for post in posts] == ["7001"]
    assert coverage["zero_new_page_count"] == 2
    assert coverage["stop_condition"] == "repeated_zero_new_page"
    assert coverage["is_exhaustive"] is False


def test_requested_limit_stops_without_claiming_exhaustive():
    first = _video(7001, title="第一条", create_time=1700000000, is_top=0, play_count=1)
    transport = FakeTransport([_page([first], cursor=20, has_more=1)])

    posts, coverage = DouyinOpenAPIClient(
        TOKEN, OPEN_ID, transport=transport
    ).collect_video_pages(limit=1, page_size=20)

    assert [post["post_id"] for post in posts] == ["7001"]
    assert transport.requests[0]["url"].endswith("?cursor=0&count=1")
    assert coverage["requested_all"] is False
    assert coverage["stop_condition"] == "limit"
    assert coverage["is_exhaustive"] is False


@pytest.mark.parametrize(
    ("media_type", "expected_type"),
    [
        (2, "video"),
        (4, "image_text"),
    ],
)
def test_media_type_maps_only_recognized_official_values(media_type, expected_type):
    video = _video(
        7001, title="作品", create_time=1700000000, is_top=0, play_count=1
    )
    video["media_type"] = media_type

    posts, _ = DouyinOpenAPIClient(
        TOKEN,
        OPEN_ID,
        transport=FakeTransport([_page([video], cursor=20, has_more=0)]),
    ).collect_video_pages()

    assert posts[0]["content_type"] == expected_type
    assert posts[0]["platform_metrics"]["media_type"] == media_type


@pytest.mark.parametrize("media_type", [None, "video", 99, []])
def test_unknown_media_type_is_rejected_instead_of_defaulting_to_video(media_type):
    video = _video(
        7001, title="作品", create_time=1700000000, is_top=0, play_count=1
    )
    video["media_type"] = media_type

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN,
            OPEN_ID,
            transport=FakeTransport([_page([video], cursor=20, has_more=0)]),
        ).collect_video_pages()

    assert exc_info.value.error_code == "INVALID_RESPONSE"
    assert exc_info.value.partial_posts == []


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


@pytest.mark.parametrize(
    "open_id",
    [None, "", " ", "owner\nopen-id", _CredentialSubclass(OPEN_ID)],
)
def test_missing_or_blank_open_id_fails_before_creating_workspace(
    tmp_path, capsys, open_id
):
    out_dir = tmp_path / "authorized"
    environ = {"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN}
    if open_id is not None:
        environ["DOUYIN_OPENAPI_OPEN_ID"] = open_id

    rc = run(out_dir=str(out_dir), environ=environ)

    captured = capsys.readouterr()
    assert rc == 2
    assert not out_dir.exists()
    assert "DOUYIN_OPENAPI_OPEN_ID" in captured.err
    assert TOKEN not in captured.out + captured.err


def test_refuses_to_overwrite_existing_workspace_before_api_calls(tmp_path):
    out_dir = tmp_path / "authorized"
    out_dir.mkdir()
    marker = out_dir / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    transport = FakeTransport([RuntimeError("API must not be called")])

    rc = run(
        out_dir=str(out_dir),
        environ=AUTHORIZED_ENV,
        transport=transport,
    )

    assert rc == 2
    assert marker.read_text(encoding="utf-8") == "keep"
    assert transport.requests == []


class _CompletedAuthorizedClient:
    def __init__(self, hook=None):
        self.hook = hook or (lambda stage: None)
        self.calls = []

    def collect_profile(self):
        self.calls.append("profile")
        self.hook("profile")
        return {
            "platform": "douyin",
            "account_id": OPEN_ID,
            "profile_url": "https://open.douyin.com/oauth/userinfo/",
            "field_visibility": {},
        }

    def collect_video_pages(self, *, limit, page_size):
        self.calls.append("pages")
        self.hook("pages")
        return [], {
            "requested_all": limit is None,
            "is_exhaustive": True,
            "terminal_page_observed": True,
            "observed_page_count": 1,
            "observed_post_count": 0,
            "repeated_cursor_count": 0,
            "zero_new_page_count": 0,
            "stop_condition": "terminal_page",
        }


def _completed_transport(hook=None):
    return FakeTransport(
        [_profile_response(), _page([], cursor=0, has_more=0)],
        hook=hook,
    )


class _ForeignAuthorizedClient(_CompletedAuthorizedClient):
    def collect_profile(self):
        self.calls.append("profile")
        return {
            "platform": "douyin",
            "account_id": "foreign-open-id",
            "profile_url": "https://open.douyin.com/oauth/userinfo/",
            "field_visibility": {},
        }


def test_public_entry_rejects_stateful_client_injection_before_output(tmp_path):
    out_dir = tmp_path / "authorized"
    foreign_client = _ForeignAuthorizedClient()

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        client=foreign_client,
    )

    assert rc == 3
    assert foreign_client.calls == []
    assert not out_dir.exists()


def test_orchestration_rejects_foreign_profile_before_video_pages(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    foreign_client = _ForeignAuthorizedClient()
    monkeypatch.setattr(
        authorized,
        "DouyinOpenAPIClient",
        lambda *args, **kwargs: foreign_client,
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert foreign_client.calls == ["profile"]
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["stop_reason"] == "OPENAPI_ERROR"
    assert task["diagnostic_code"] == "INVALID_RESPONSE"
    assert task["collection_coverage"]["is_exhaustive"] is False
    assert task["collection_coverage"]["terminal_page_observed"] is False
    profile = json.loads(
        (out_dir / "source" / "profile.json").read_text(encoding="utf-8")
    )
    assert profile == {}
    assert "foreign-open-id" not in _artifact_text(out_dir)
    assert "foreign-open-id" not in captured.out + captured.err
    report = (out_dir / "collection-report.md").read_text(encoding="utf-8")
    assert "stage=collect_profile" in report
    assert "stage=collect_video_pages" not in report


def test_authorized_entry_builds_client_from_both_environment_credentials(
    monkeypatch, tmp_path
):
    observed = {}

    def build_client(access_token, open_id, transport=None):
        observed.update({
            "access_token": access_token,
            "open_id": open_id,
            "transport": transport,
        })
        return _CompletedAuthorizedClient()

    monkeypatch.setattr(authorized, "DouyinOpenAPIClient", build_client)

    assert run(
        out_dir=str(tmp_path / "authorized"),
        environ=AUTHORIZED_ENV,
    ) == 0
    assert observed == {
        "access_token": TOKEN,
        "open_id": OPEN_ID,
        "transport": None,
    }


@pytest.mark.parametrize("stage", ["serialization", "commit"])
@pytest.mark.parametrize("exception_type", [RuntimeError, OSError])
def test_authorized_ordinary_output_failure_is_sanitized_and_never_cleans_up(
    monkeypatch, tmp_path, capsys, stage, exception_type
):
    out_dir = tmp_path / "authorized"
    secret = f"SECRET_OUTPUT_FAILURE {TOKEN}"
    for name in ("replace", "rename", "unlink", "rmdir"):
        monkeypatch.setattr(
            immutable.os,
            name,
            lambda *args, _name=name, **kwargs: pytest.fail(
                f"output failure called os.{_name}"
            ),
        )
    if stage == "serialization":
        monkeypatch.setattr(
            authorized,
            "_serialize_artifacts",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                exception_type(secret)
            ),
        )
    else:
        monkeypatch.setattr(
            immutable.ImmutableWorkspace,
            "commit",
            lambda self: (_ for _ in ()).throw(exception_type(secret)),
        )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=_completed_transport(),
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert out_dir.is_dir()
    assert not (out_dir / ".complete").exists()
    assert secret not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err


def test_authorized_indeterminate_commit_has_dedicated_sanitized_exit_and_closes_handles(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    secret = f"SECRET_AUTHORIZED_INDETERMINATE {TOKEN}"
    held_descriptors = []

    def fail_indeterminate(self):
        held_descriptors.extend(
            owned.descriptor for owned in self._leaves.values()
        )
        if self.posix_chain is not None:
            held_descriptors.extend(
                entry.descriptor for entry in self.posix_chain.entries
            )
        try:
            raise OSError(secret)
        except OSError as cause:
            raise immutable.WorkspaceCommitIndeterminate() from cause

    monkeypatch.setattr(immutable.ImmutableWorkspace, "commit", fail_indeterminate)

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=_completed_transport(),
    )

    assert rc == 4
    assert held_descriptors
    for descriptor in held_descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    captured = capsys.readouterr()
    assert captured.err == (
        "[INDETERMINATE] 输出目录可能已有可见提交，但持久化或最终验证未确认；"
        "请保留目录并重新核验\n"
    )
    assert secret not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err
    assert out_dir.is_dir()


@pytest.mark.parametrize("stage", ["serialization", "commit"])
@pytest.mark.parametrize("control_flow", [KeyboardInterrupt, SystemExit])
def test_authorized_control_flow_propagates_after_workspace_handles_close(
    monkeypatch, tmp_path, stage, control_flow
):
    out_dir = tmp_path / "authorized"
    original_close = immutable.ImmutableWorkspace.close
    closed = []

    def record_close(self):
        original_close(self)
        closed.append(self.closed)

    monkeypatch.setattr(immutable.ImmutableWorkspace, "close", record_close)
    if stage == "serialization":
        monkeypatch.setattr(
            authorized,
            "_serialize_artifacts",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                control_flow("CONTROL_FLOW_SENTINEL")
            ),
        )
    else:
        monkeypatch.setattr(
            immutable.ImmutableWorkspace,
            "commit",
            lambda self: (_ for _ in ()).throw(
                control_flow("CONTROL_FLOW_SENTINEL")
            ),
        )

    with pytest.raises(control_flow, match="CONTROL_FLOW_SENTINEL"):
        run(
            out_dir=str(out_dir),
            collect_all=True,
            environ=AUTHORIZED_ENV,
            transport=_completed_transport(),
        )

    assert closed == [True]
    assert out_dir.is_dir()
    assert not (out_dir / ".complete").exists()


def test_authorized_leaf_conflict_preserves_concurrent_bytes(tmp_path):
    out_dir = tmp_path / "authorized"
    concurrent_bytes = b"concurrent profile\x00must-survive"

    def conflict(stage):
        if stage == "profile":
            (out_dir / "source" / "profile.json").write_bytes(concurrent_bytes)

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=_completed_transport(conflict),
    )

    assert rc == 2
    assert (out_dir / "source" / "profile.json").read_bytes() == concurrent_bytes
    assert not (out_dir / ".complete").exists()


def test_authorized_workspace_swap_preserves_replacement_uncommitted(tmp_path):
    out_dir = tmp_path / "authorized"
    displaced = tmp_path / "displaced-authorized"
    replacement_bytes = b"replacement\x00must-survive"

    def swap(stage):
        if stage == "profile":
            out_dir.rename(displaced)
            out_dir.mkdir()
            (out_dir / "replacement.bin").write_bytes(replacement_bytes)

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=_completed_transport(swap),
    )

    assert rc == 2
    assert (out_dir / "replacement.bin").read_bytes() == replacement_bytes
    assert not (out_dir / ".complete").exists()
    assert not (displaced / ".complete").exists()


def test_authorized_preexisting_complete_marker_is_not_overwritten(tmp_path):
    out_dir = tmp_path / "authorized"
    marker_bytes = b"concurrent marker\x00must-survive"

    def add_marker(stage):
        if stage == "profile":
            (out_dir / ".complete").write_bytes(marker_bytes)

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=_completed_transport(add_marker),
    )

    assert rc == 2
    assert (out_dir / ".complete").read_bytes() == marker_bytes


def test_authorized_missing_backend_fails_before_workspace_and_api(
    monkeypatch, tmp_path
):
    out_dir = tmp_path / "authorized"
    transport = _completed_transport()
    monkeypatch.setattr(immutable, "_backend_kind", lambda: "unsupported")

    assert run(
        out_dir=str(out_dir),
        environ=AUTHORIZED_ENV,
        transport=transport,
    ) == 2
    assert not out_dir.exists()
    assert transport.requests == []


def test_all_writes_standard_completed_artifacts_without_token(tmp_path, capsys):
    out_dir = tmp_path / "authorized"
    video = _video(7001, title="#授权作品", create_time=1700000000, is_top=0, play_count=10)
    transport = FakeTransport([
        _profile_response(),
        _page([video], cursor=20, has_more=0),
    ])

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=transport,
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
    with (out_dir / "normalized-posts.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        row = next(csv.DictReader(handle))
    assert row["hashtags"] == '["授权作品"]'
    assert row["platform_metrics"] == (
        '{"download_count":5,"forward_count":6,"media_type":2}'
    )
    assert row["is_pinned"] == "false"
    assert row["is_repost"] == ""
    post = analyze.build_posts([row])[0]
    assert post["hashtags"] == ["授权作品"]
    assert post["platform_metrics"] == {
        "download_count": 5,
        "forward_count": 6,
        "media_type": 2,
    }
    assert post["is_pinned"] is False
    assert post["is_repost"] is None
    assert TOKEN not in _artifact_text(out_dir)
    assert TOKEN not in captured.out + captured.err


def test_authorized_task_persists_task_id_and_analysis_goal(tmp_path):
    out_dir = tmp_path / "authorized-goal"
    transport = FakeTransport([
        _profile_response(),
        _page([], cursor=0, has_more=0),
    ])

    assert run(
        out_dir=str(out_dir),
        analysis_goal="分析授权账号作品节奏",
        environ=AUTHORIZED_ENV,
        transport=transport,
    ) == 0

    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["analysis_goal"] == "分析授权账号作品节奏"
    assert isinstance(task["task_id"], str) and task["task_id"]


@pytest.mark.parametrize("goal", [123, "", " ", "x" * 501, "a\nb", "a\x00b"])
def test_authorized_rejects_invalid_analysis_goal_before_output_or_transport(
    tmp_path, goal
):
    def must_not_run(**kwargs):
        pytest.fail("transport must not run")

    out_dir = tmp_path / "invalid-goal"
    assert run(
        out_dir=str(out_dir),
        analysis_goal=goal,
        environ=AUTHORIZED_ENV,
        transport=must_not_run,
    ) == 2
    assert not out_dir.exists()


def test_authorized_cli_forwards_analysis_goal(monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(authorized, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect_douyin_authorized.py",
            "--analysis-goal",
            "分析授权内容",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        authorized.main()

    assert exc_info.value.code == 0
    assert captured["analysis_goal"] == "分析授权内容"


def test_api_error_after_page_writes_partial_artifacts(tmp_path):
    out_dir = tmp_path / "authorized"
    video = _video(7001, title="已保留", create_time=1700000000, is_top=0, play_count=10)
    transport = FakeTransport([
        _profile_response(),
        _page([video], cursor=20, has_more=1),
        _page([], cursor=40, has_more=0, error_code=2190008),
    ])

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=transport,
    )

    assert rc == 0
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "OPENAPI_ERROR"
    rows = (out_dir / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(row)["post_id"] for row in rows] == ["7001"]


def test_api_error_before_page_writes_failed_standard_artifacts(tmp_path):
    out_dir = tmp_path / "authorized"
    transport = FakeTransport([
        _profile_response(),
        _page([], cursor=0, has_more=0, error_code=2190008),
    ])

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ=AUTHORIZED_ENV,
        transport=transport,
    )

    assert rc == 3
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["collected_count"] == 0
    assert _artifact_text(out_dir)


def test_all_repeated_cursor_is_partial_but_limited_request_is_complete(tmp_path):
    video = _video(7001, title="作品", create_time=1700000000, is_top=0, play_count=10)

    all_out = tmp_path / "all"
    all_transport = FakeTransport([
        _profile_response(),
        _page([video], cursor=0, has_more=1),
    ])
    assert run(
        out_dir=str(all_out), collect_all=True,
        environ=AUTHORIZED_ENV, transport=all_transport,
    ) == 0
    all_task = json.loads((all_out / "task.json").read_text(encoding="utf-8"))
    assert all_task["task_status"] == "PARTIAL"

    limited_out = tmp_path / "limited"
    limited_transport = FakeTransport([
        _profile_response(),
        _page([video], cursor=20, has_more=1),
    ])
    assert run(
        out_dir=str(limited_out), limit=1,
        environ=AUTHORIZED_ENV, transport=limited_transport,
    ) == 0
    limited_task = json.loads(
        (limited_out / "task.json").read_text(encoding="utf-8")
    )
    assert limited_task["task_status"] == "COMPLETED"
    assert limited_task["collection_coverage"]["is_exhaustive"] is False


def test_limited_loop_below_requested_count_is_partial(tmp_path):
    out_dir = tmp_path / "limited-loop"
    video = _video(
        7001, title="不足一页", create_time=1700000000, is_top=0, play_count=10
    )
    transport = FakeTransport([
        _profile_response(),
        _page([video], cursor=0, has_more=1),
    ])

    assert run(
        out_dir=str(out_dir),
        limit=30,
        environ=AUTHORIZED_ENV,
        transport=transport,
    ) == 0
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "PARSER_FAILED"
    assert task["collected_count"] == 1
