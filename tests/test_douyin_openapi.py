"""Offline contract tests for the authorized Douyin OpenAPI collector."""

from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path

import pytest

import collect_douyin_authorized as authorized
import collectors.douyin_openapi as openapi
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
            TOKEN, transport=FakeTransport([raw_error])
        ).collect_profile()

    assert exc_info.value.error_code == "TRANSPORT_ERROR"
    assert exc_info.value.partial_posts == []
    assert exc_info.value.coverage == {}
    _assert_exception_tree_is_sanitized(exc_info.value)


def test_malformed_json_token_is_not_retained_in_json_error_or_context():
    malformed = f'{{"echo":"{TOKEN}"'.encode("utf-8")

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN, transport=FakeTransport([malformed])
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
        DouyinOpenAPIClient(TOKEN).collect_profile()

    assert observed["opener_used"] is True
    assert observed["forwarded_headers"] == []
    _assert_exception_tree_is_sanitized(exc_info.value)


def test_request_rejects_non_fixed_endpoint_before_transport():
    transport = FakeTransport([_profile_response()])
    client = DouyinOpenAPIClient(TOKEN, transport=transport)

    with pytest.raises(DouyinOpenAPIError) as exc_info:
        client._request("GET", "https://redirect.example/video/list/")

    assert exc_info.value.error_code == "INVALID_ENDPOINT"
    assert transport.requests == []


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


def test_float_zero_error_code_is_not_accepted_as_exact_success():
    with pytest.raises(DouyinOpenAPIError) as exc_info:
        DouyinOpenAPIClient(
            TOKEN,
            transport=FakeTransport([{
                "data": {**_profile_response()["data"], "error_code": 0.0}
            }]),
        ).collect_profile()

    assert exc_info.value.error_code == "OPENAPI_ERROR"


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


def test_artifact_failure_is_sanitized_cleans_staging_and_allows_recovery(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    original_write_csv = authorized._write_csv

    def fail_csv(posts, path):
        raise OSError("injected serialization failure")

    monkeypatch.setattr(authorized, "_write_csv", fail_csv)
    first_client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    assert run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=first_client,
    ) == 3

    assert not out_dir.exists()
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    captured = capsys.readouterr()
    assert "injected serialization failure" not in captured.out + captured.err

    monkeypatch.setattr(authorized, "_write_csv", original_write_csv)
    recovery_client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )
    assert run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=recovery_client,
    ) == 0
    assert (out_dir / "task.json").is_file()


@pytest.mark.skipif(not Path("/dev/fd").is_dir(), reason="requires /dev/fd")
def test_authorized_runtime_serialization_failure_is_sanitized_without_leaks(
    monkeypatch, tmp_path, capsys
):
    original_dump = authorized.json.dump

    def fail_profile_dump(value, handle, *args, **kwargs):
        if isinstance(value, dict) and value.get("platform") == "douyin":
            raise RuntimeError(f"SECRET_RUNTIME_FAILURE {TOKEN}")
        return original_dump(value, handle, *args, **kwargs)

    monkeypatch.setattr(authorized.json, "dump", fail_profile_dump)
    before = len(list(Path("/dev/fd").iterdir()))
    results = []
    for index in range(20):
        client = DouyinOpenAPIClient(
            TOKEN,
            transport=FakeTransport([
                _profile_response(),
                _page([], cursor=0, has_more=0),
            ]),
        )
        results.append(run(
            out_dir=str(tmp_path / f"authorized-{index}"),
            collect_all=True,
            environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
            client=client,
        ))

    after = len(list(Path("/dev/fd").iterdir()))
    captured = capsys.readouterr()
    assert results == [3] * 20
    assert after <= before + 2
    assert list(tmp_path.glob(".authorized-*.staging-*")) == []
    assert not any((tmp_path / f"authorized-{index}").exists() for index in range(20))
    assert "SECRET_RUNTIME_FAILURE" not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err


@pytest.mark.parametrize("control_flow", [KeyboardInterrupt, SystemExit])
def test_authorized_serialization_preserves_base_exception_control_flow(
    monkeypatch, tmp_path, control_flow
):
    def interrupt_serialization(workspace, **kwargs):
        raise control_flow("CONTROL_FLOW_SENTINEL")

    monkeypatch.setattr(
        authorized, "_serialize_artifacts", interrupt_serialization
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    with pytest.raises(control_flow, match="CONTROL_FLOW_SENTINEL"):
        run(
            out_dir=str(tmp_path / "authorized"),
            collect_all=True,
            environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
            client=client,
        )

    assert list(tmp_path.glob(".authorized.staging-*")) == []


@pytest.mark.parametrize("node_kind", ["symlink", "fifo", "hardlink"])
def test_authorized_rejects_unsafe_staging_artifact_nodes(
    monkeypatch, tmp_path, capsys, node_kind
):
    if node_kind == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("FIFO requires POSIX")
    out_dir = tmp_path / "authorized"
    victim = tmp_path / "victim.bin"
    victim_bytes = b"victim\x00must-survive"
    victim.write_bytes(victim_bytes)
    original_serialize = authorized._serialize_artifacts

    def serialize_then_replace_task(workspace, **kwargs):
        original_serialize(workspace, **kwargs)
        task = Path(workspace) / "task.json"
        task.unlink()
        if node_kind == "symlink":
            task.symlink_to(victim)
        elif node_kind == "fifo":
            os.mkfifo(task)
        else:
            os.link(victim, task)

    monkeypatch.setattr(
        authorized, "_serialize_artifacts", serialize_then_replace_task
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert not out_dir.exists()
    assert victim.read_bytes() == victim_bytes
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_authorized_atomic_publish_unavailable_fails_closed(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"

    def unavailable(staging, target):
        raise OSError("atomic no-replace unavailable")

    monkeypatch.setattr(
        authorized, "_atomic_publish_noreplace", unavailable, raising=False
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert not out_dir.exists()
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_authorized_atomic_publish_preserves_concurrent_final_marker(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    marker_bytes = b"concurrent final\x00must-survive"

    def competing_publish(staging, target):
        Path(target).mkdir()
        (Path(target) / "marker.bin").write_bytes(marker_bytes)
        raise FileExistsError("concurrent target")

    monkeypatch.setattr(
        authorized, "_atomic_publish_noreplace", competing_publish, raising=False
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert (out_dir / "marker.bin").read_bytes() == marker_bytes
    assert sorted(path.name for path in out_dir.iterdir()) == ["marker.bin"]
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_concurrent_target_creation_preserves_marker_and_aborts_promotion(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    marker_bytes = b"concurrent owner data\x00must survive"
    original_serialize = authorized._serialize_artifacts

    def serialize_then_create_competing_target(workspace, **kwargs):
        original_serialize(workspace, **kwargs)
        out_dir.mkdir()
        (out_dir / "marker.bin").write_bytes(marker_bytes)

    monkeypatch.setattr(
        authorized,
        "_serialize_artifacts",
        serialize_then_create_competing_target,
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert (out_dir / "marker.bin").read_bytes() == marker_bytes
    assert [path.name for path in out_dir.iterdir()] == ["marker.bin"]
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_atomic_directory_publish_failure_cleans_only_owned_staging(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"

    def fail_atomic_publish(source, target):
        raise OSError(f"raw promotion failure {TOKEN}")

    monkeypatch.setattr(
        authorized, "_atomic_publish_noreplace", fail_atomic_publish
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert not out_dir.exists()
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_authorized_staging_identity_capture_failure_cleans_owned_staging(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"

    def fail_staging_capture(path, *args, **kwargs):
        raise OSError(f"injected identity failure {TOKEN}")

    monkeypatch.setattr(
        authorized, "_open_staging_directory", fail_staging_capture
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert not out_dir.exists()
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_staging_swap_before_identity_capture_never_adopts_replacement(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    displaced = tmp_path / "displaced-original-staging"
    replacement_task = b"concurrent task\x00must-survive"
    replacement_marker = b"concurrent marker\x00must-survive"

    def swap_then_fail_capture(staging, *args, **kwargs):
        Path(staging).rename(displaced)
        Path(staging).mkdir()
        (Path(staging) / "task.json").write_bytes(replacement_task)
        (Path(staging) / "marker.bin").write_bytes(replacement_marker)
        raise OSError(f"SECRET_CAPTURE_FAILURE {TOKEN}")

    monkeypatch.setattr(
        authorized, "_open_staging_directory", swap_then_fail_capture
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    assert run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    ) == 3

    captured = capsys.readouterr()
    replacements = list(tmp_path.glob(".authorized.staging-*"))
    assert len(replacements) == 1
    assert (replacements[0] / "task.json").read_bytes() == replacement_task
    assert (replacements[0] / "marker.bin").read_bytes() == replacement_marker
    assert displaced.is_dir()
    assert list(displaced.iterdir()) == []
    assert "SECRET_CAPTURE_FAILURE" not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err


def _test_windows_tree_evidence(staging: str) -> dict[str, tuple[int, ...]]:
    expected_root = {
        "source",
        "normalized-posts.csv",
        "task.json",
        "collection-report.md",
    }
    assert {path.name for path in Path(staging).iterdir()} == expected_root
    assert {
        path.name for path in (Path(staging) / "source").iterdir()
    } == {"profile.json", "posts.jsonl"}
    evidence: dict[str, tuple[int, ...]] = {}
    for relative in (
        "source/profile.json",
        "source/posts.jsonl",
        "normalized-posts.csv",
        "task.json",
        "collection-report.md",
    ):
        metadata = os.lstat(Path(staging) / relative)
        assert metadata.st_nlink == 1
        evidence[relative] = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
        )
    return evidence


@pytest.mark.parametrize("concurrent_target", [False, True])
def test_authorized_windows_backend_is_reachable_and_create_only(
    monkeypatch, tmp_path, concurrent_target
):
    out_dir = tmp_path / "authorized"
    calls = {"open": 0, "validate": 0, "close": 0, "publish": 0}
    marker_bytes = b"windows concurrent target\x00must-survive"

    def open_windows_staging(staging, expected_identity):
        calls["open"] += 1
        metadata = os.lstat(staging)
        assert (metadata.st_dev, metadata.st_ino) == expected_identity
        return object(), expected_identity

    def validate_windows_staging(
        staging, handle, identity, *, expected=None
    ):
        calls["validate"] += 1
        evidence = _test_windows_tree_evidence(staging)
        if expected is not None:
            assert evidence == expected
        return evidence

    def close_windows_staging(handle):
        calls["close"] += 1

    def publish_windows_staging(staging, target):
        calls["publish"] += 1
        if concurrent_target:
            Path(target).mkdir()
            (Path(target) / "marker.bin").write_bytes(marker_bytes)
            raise FileExistsError("concurrent Windows target")
        assert not os.path.lexists(target)
        os.rename(staging, target)

    monkeypatch.setattr(
        authorized, "_artifact_platform", lambda: "windows", raising=False
    )
    monkeypatch.setattr(
        authorized,
        "_open_windows_staging_directory",
        open_windows_staging,
        raising=False,
    )
    monkeypatch.setattr(
        authorized,
        "_validate_windows_staging_tree",
        validate_windows_staging,
        raising=False,
    )
    monkeypatch.setattr(
        authorized,
        "_close_windows_staging_directory",
        close_windows_staging,
        raising=False,
    )
    monkeypatch.setattr(
        authorized,
        "_windows_publish_noreplace",
        publish_windows_staging,
        raising=False,
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    assert rc == (2 if concurrent_target else 0)
    assert calls["open"] == 1
    assert calls["validate"] == (2 if concurrent_target else 3)
    assert calls["close"] == 1
    assert calls["publish"] == 1
    if concurrent_target:
        assert (out_dir / "marker.bin").read_bytes() == marker_bytes
        assert sorted(path.name for path in out_dir.iterdir()) == ["marker.bin"]
    else:
        assert (out_dir / "task.json").is_file()
        assert (out_dir / "source" / "profile.json").is_file()
    assert list(tmp_path.glob(".authorized.staging-*")) == []


def test_windows_publish_noreplace_preserves_existing_target(tmp_path):
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()
    marker_bytes = b"existing Windows target\x00must-survive"
    (target / "marker.bin").write_bytes(marker_bytes)

    with pytest.raises(FileExistsError):
        authorized._windows_publish_noreplace(str(staging), str(target))

    assert staging.is_dir()
    assert (target / "marker.bin").read_bytes() == marker_bytes

    publishable = tmp_path / "publishable"
    published = tmp_path / "published"
    publishable.mkdir()
    (publishable / "artifact.bin").write_bytes(b"complete")
    authorized._windows_publish_noreplace(str(publishable), str(published))
    assert not publishable.exists()
    assert (published / "artifact.bin").read_bytes() == b"complete"


def test_authorized_unknown_platform_fails_closed(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    monkeypatch.setattr(
        authorized, "_artifact_platform", lambda: "unsupported", raising=False
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    assert run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    ) == 3
    captured = capsys.readouterr()
    assert not out_dir.exists()
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_atomic_publish_failure_preserves_concurrent_final_marker(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    marker_bytes = b"concurrent marker\x00must survive"

    def competing_publish_then_fail(source, target):
        Path(target).mkdir()
        (Path(target) / "marker.bin").write_bytes(marker_bytes)
        raise OSError(f"raw promotion failure {TOKEN}")

    monkeypatch.setattr(
        authorized, "_atomic_publish_noreplace", competing_publish_then_fail
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert (out_dir / "marker.bin").read_bytes() == marker_bytes
    assert sorted(path.name for path in out_dir.iterdir()) == ["marker.bin"]
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


def test_post_publish_target_swap_leaves_replacement_and_published_tree_untouched(
    monkeypatch, tmp_path, capsys
):
    out_dir = tmp_path / "authorized"
    displaced_publish = tmp_path / "displaced-published-tree"
    marker_bytes = b"replacement target\x00must survive"
    original_publish = authorized._atomic_publish_noreplace

    def publish_then_replace_target(source, target):
        original_publish(source, target)
        Path(target).rename(displaced_publish)
        Path(target).mkdir()
        (Path(target) / "marker.bin").write_bytes(marker_bytes)

    monkeypatch.setattr(
        authorized, "_atomic_publish_noreplace", publish_then_replace_target
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([], cursor=0, has_more=0),
        ]),
    )

    rc = run(
        out_dir=str(out_dir),
        collect_all=True,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    )

    captured = capsys.readouterr()
    assert rc == 3
    assert (out_dir / "marker.bin").read_bytes() == marker_bytes
    assert (displaced_publish / "source" / "profile.json").is_file()
    assert (displaced_publish / "task.json").is_file()
    assert list(tmp_path.glob(".authorized.staging-*")) == []
    assert TOKEN not in captured.out + captured.err


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


def test_limited_loop_below_requested_count_is_partial(tmp_path):
    out_dir = tmp_path / "limited-loop"
    video = _video(
        7001, title="不足一页", create_time=1700000000, is_top=0, play_count=10
    )
    client = DouyinOpenAPIClient(
        TOKEN,
        transport=FakeTransport([
            _profile_response(),
            _page([video], cursor=0, has_more=1),
        ]),
    )

    assert run(
        out_dir=str(out_dir),
        limit=30,
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": TOKEN},
        client=client,
    ) == 0
    task = json.loads((out_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "PARSER_FAILED"
    assert task["collected_count"] == 1
