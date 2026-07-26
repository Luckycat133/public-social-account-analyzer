"""Offline policy tests for Bilibili protection and transport handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from collectors.bilibili import (
    BilibiliCollector,
    BilibiliError,
    STOP_ACCESS_RESTRICTED,
    STOP_LOGIN,
    STOP_NO_PUBLIC_CONTENT,
    STOP_PARSER_FAILED,
    STOP_VERIFICATION,
    Session,
)


def test_platform_rate_limit_stops_without_retry_identity_rotation_or_browser(
    monkeypatch,
):
    session = Session(browser_fallback=True)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)
    calls: list[str] = []
    rotations: list[bool] = []
    browser_calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: (
            calls.append(url)
            or json.dumps({"code": -799, "message": "request too frequent"})
        ),
    )
    monkeypatch.setattr(
        session,
        "ensure_buvid",
        lambda force=False: rotations.append(force),
    )
    monkeypatch.setattr(
        session,
        "_fetch_via_browser",
        lambda url, referer: (
            browser_calls.append(url) or json.dumps({"code": 0, "data": {}})
        ),
    )

    with pytest.raises(BilibiliError) as exc_info:
        session.get_json("/x/space/wbi/arc/search", retry=20)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(calls) == 1
    assert rotations == []
    assert browser_calls == []


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("<html>login 请先登录</html>", STOP_LOGIN),
        ("<html>verify_captcha 请完成滑块验证</html>", STOP_VERIFICATION),
    ],
)
def test_protection_html_stops_after_one_response(
    monkeypatch, body, reason
):
    session = Session(browser_fallback=True)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)
    calls: list[str] = []
    rotations: list[bool] = []
    browser_calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or body,
    )
    monkeypatch.setattr(
        session,
        "ensure_buvid",
        lambda force=False: rotations.append(force),
    )
    monkeypatch.setattr(
        session,
        "_fetch_via_browser",
        lambda url, referer: browser_calls.append(url) or "{}",
    )

    with pytest.raises(BilibiliError) as exc_info:
        session.get_json("/x/web-interface/view", retry=20)

    assert exc_info.value.stop_reason == reason
    assert len(calls) == 1
    assert rotations == []
    assert browser_calls == []


@pytest.mark.parametrize(
    "body",
    [
        "not-json without platform-protection evidence",
        "<html>an article about captcha design and verification workflows</html>",
    ],
)
def test_plain_non_json_is_parser_failure_without_opening_circuit(
    monkeypatch, body
):
    session = Session(browser_fallback=False)
    calls: list[str] = []
    responses = iter([
        body,
        json.dumps({"code": 0, "data": {"ok": True}}),
    ])
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or next(responses),
    )

    with pytest.raises(BilibiliError) as first:
        session.get_json("/x/web-interface/view", retry=1)
    assert first.value.stop_reason == STOP_PARSER_FAILED

    result = session.get_json("/x/web-interface/card", retry=1)
    assert result["data"]["ok"] is True
    assert len(calls) == 2


@pytest.mark.parametrize(
    "body",
    [
        "<html>captcha required</html>",
        "<html>verification required</html>",
    ],
)
def test_explicit_english_verification_page_opens_circuit(monkeypatch, body):
    session = Session(browser_fallback=False)
    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or body,
    )

    with pytest.raises(BilibiliError) as first:
        session.get_json("/x/web-interface/view", retry=1)
    assert first.value.stop_reason == STOP_VERIFICATION

    with pytest.raises(BilibiliError) as second:
        session.get_json("/x/web-interface/card", retry=1)
    assert second.value.stop_reason == STOP_VERIFICATION
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        "<html>WAF request was banned</html>",
        "<html>rate limit: too many requests</html>",
        "<html>access denied</html>",
    ],
)
def test_explicit_non_json_access_protection_opens_circuit(monkeypatch, body):
    session = Session(browser_fallback=False)
    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or body,
    )

    with pytest.raises(BilibiliError) as first:
        session.get_json("/x/web-interface/view", retry=1)
    assert first.value.stop_reason == STOP_ACCESS_RESTRICTED

    with pytest.raises(BilibiliError) as second:
        session.get_json("/x/web-interface/card", retry=1)
    assert second.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(calls) == 1


def test_platform_block_opens_session_circuit_breaker(monkeypatch):
    session = Session(browser_fallback=False)
    calls: list[str] = []

    def blocked_response(url, referer):
        calls.append(url)
        return json.dumps({"code": -412, "message": "request was banned"})

    monkeypatch.setattr(session, "_curl", blocked_response)
    with pytest.raises(BilibiliError) as first:
        session.get_json("/x/web-interface/card", retry=1)
    assert first.value.stop_reason == STOP_ACCESS_RESTRICTED

    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or json.dumps({"code": 0}),
    )
    with pytest.raises(BilibiliError) as second:
        session.get_json("/x/relation/stat", retry=1)

    assert second.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(calls) == 1


def test_transport_failure_retries_once_with_same_identity(monkeypatch):
    session = Session(browser_fallback=True)
    session.cookies = {"buvid3": "stable-public-id"}
    attempts: list[list[str]] = []
    rotations: list[bool] = []

    def run_curl(cmd, **kwargs):
        attempts.append(list(cmd))
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(cmd, 10)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"code": 0, "data": {"ok": True}}),
            stderr="",
        )

    monkeypatch.setattr("collectors.bilibili.subprocess.run", run_curl)
    monkeypatch.setattr(session, "_throttle", lambda: None)
    monkeypatch.setattr(
        session,
        "ensure_buvid",
        lambda force=False: rotations.append(force),
    )
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    result = session.get_json("/x/web-interface/card", retry=99)

    assert result["data"]["ok"] is True
    assert len(attempts) == 2
    assert rotations == []
    assert session.cookies == {"buvid3": "stable-public-id"}


def test_fingerprint_initialization_is_once_and_non_recursive(monkeypatch):
    session = Session(browser_fallback=False)
    calls: list[str] = []
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: (
            calls.append(url)
            or json.dumps({"code": -412, "message": "request was banned"})
        ),
    )

    session.ensure_buvid()
    session.ensure_buvid(force=True)

    assert len(calls) == 1
    assert session.cookies == {}


def test_discover_arc_never_rotates_identity_between_pages(monkeypatch):
    session = Session(browser_fallback=False)
    page = {"value": 0}
    rotations: list[bool] = []

    def get_json(path, params=None, wbi=False, referer=None, retry=3):
        page["value"] += 1
        items = (
            [{"bvid": f"BV{index:010d}"} for index in range(50)]
            if page["value"] == 1
            else []
        )
        return {"code": 0, "data": {"list": {"vlist": items}}}

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr(
        session,
        "ensure_buvid",
        lambda force=False: rotations.append(force),
    )
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    assert len(session.discover_arc("123", 51)) == 50
    assert rotations == []


def test_post_list_does_not_change_endpoint_after_access_restriction(
    monkeypatch,
):
    class RestrictedSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return None

        def discover_medialist(self, mid, limit):
            raise BilibiliError(STOP_ACCESS_RESTRICTED, "restricted")

        def discover_arc(self, mid, limit):
            raise AssertionError("must not try another endpoint after restriction")

        def discover_search(self, mid, url, limit):
            raise AssertionError("must not try another endpoint after restriction")

    collector = BilibiliCollector(browser_fallback=True)
    monkeypatch.setattr(collector, "_new_session", RestrictedSession)

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_post_list("https://space.bilibili.com/123", limit=30)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED


@pytest.mark.parametrize(
    ("observation", "expected_flags"),
    [
        ((False, None), [None, None]),
        ((True, None), [False, False]),
        ((True, "BVone"), [True, False]),
        ("BVone", [True, False]),
    ],
)
def test_post_list_marks_pin_only_from_an_observed_top_response(
    monkeypatch, observation, expected_flags
):
    class PinnedSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return observation

        def discover_medialist(self, mid, limit):
            return [
                {
                    "bv_id": "BVone",
                    "copy_right": 1,
                    "cnt_info": {},
                },
                {
                    "bv_id": "BVtwo",
                    "copy_right": 1,
                    "cnt_info": {},
                },
            ]

        def collect_tags(self, bvid):
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", PinnedSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123", limit=2
    )

    assert [post["is_pinned"] for post in posts] == expected_flags


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"code": 0, "data": {"bvid": "BVtop"}}, (True, "BVtop")),
        ({"code": 0, "data": None}, (True, None)),
        ({"code": 0, "data": {}}, (False, None)),
        ({"code": 0, "data": {"bvid": ""}}, (False, None)),
        ({"code": 0, "data": {"bvid": 123}}, (False, None)),
        ({"code": -1, "data": None}, (False, None)),
    ],
)
def test_collect_pinned_distinguishes_observed_no_pin_from_failure(
    monkeypatch, response, expected
):
    session = Session(browser_fallback=False)
    monkeypatch.setattr(session, "get_json", lambda *args, **kwargs: response)

    assert session.collect_pinned("123") == expected


def test_collector_reuses_one_session_across_task_methods(monkeypatch):
    collector = BilibiliCollector(browser_fallback=False)
    session = collector._new_session()
    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: (
            calls.append(url)
            or json.dumps({"code": -412, "message": "request was banned"})
        ),
    )

    with pytest.raises(BilibiliError):
        session.get_json("/x/web-interface/card", retry=1)

    later = collector._new_session()
    monkeypatch.setattr(
        later,
        "_curl",
        lambda url, referer: calls.append(url) or json.dumps({"code": 0}),
    )
    with pytest.raises(BilibiliError) as exc_info:
        later.get_json("/x/relation/stat", retry=1)

    assert later is session
    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(calls) == 1


def test_collect_tags_propagates_platform_protection(monkeypatch):
    session = Session(browser_fallback=False)
    monkeypatch.setattr(
        session,
        "get_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            BilibiliError(STOP_ACCESS_RESTRICTED, "restricted")
        ),
    )

    with pytest.raises(BilibiliError) as exc_info:
        session.collect_tags("BV1restricted")

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED


def test_comments_use_the_shared_task_session_for_view_and_reply(monkeypatch):
    collector = BilibiliCollector(browser_fallback=False)
    session = collector._new_session()
    session.cookies = {"buvid3": "stable-public-id"}
    calls: list[tuple[str, dict | None]] = []

    def get_json(path, params=None, **kwargs):
        calls.append((path, params))
        if path == "/x/web-interface/view":
            return {"code": 0, "data": {"aid": 123}}
        if path == "/x/v2/reply":
            return {"code": 0, "data": {"replies": []}}
        raise AssertionError(path)

    monkeypatch.setattr(session, "get_json", get_json)
    assert collector.collect_comments(
        "https://www.bilibili.com/video/BV1abc"
    ) == []
    assert calls == [
        ("/x/web-interface/view", {"bvid": "BV1abc"}),
        (
            "/x/v2/reply",
            {"type": 1, "oid": 123, "mode": 3, "next": 0},
        ),
    ]


def test_comments_preserve_verification_and_open_task_circuit(monkeypatch):
    collector = BilibiliCollector(browser_fallback=False)
    session = collector._new_session()
    session.cookies = {"buvid3": "stable-public-id"}
    calls: list[str] = []
    bodies = iter([
        json.dumps({"code": 0, "data": {"aid": 123}}),
        json.dumps({"code": -401, "message": "verification required"}),
    ])
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or next(bodies),
    )

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_comments("https://www.bilibili.com/video/BV1abc")

    assert exc_info.value.stop_reason == STOP_VERIFICATION
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or json.dumps({"code": 0}),
    )
    with pytest.raises(BilibiliError) as later:
        collector.collect_profile("https://space.bilibili.com/123")
    assert later.value.stop_reason == STOP_VERIFICATION
    assert len(calls) == 2


def test_comments_check_existing_task_circuit_before_any_network(monkeypatch):
    collector = BilibiliCollector(browser_fallback=False)
    session = collector._new_session()
    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: (
            calls.append(url)
            or json.dumps({"code": -412, "message": "request was banned"})
        ),
    )
    with pytest.raises(BilibiliError):
        session.get_json("/x/web-interface/card", retry=1)

    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or json.dumps({"code": 0}),
    )
    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_comments("https://www.bilibili.com/video/BV1abc")

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(calls) == 1


def test_missing_wbi_keys_are_parser_failure_not_platform_protection(
    monkeypatch,
):
    session = Session(browser_fallback=False)
    calls: list[str] = []
    bodies = iter([
        json.dumps({"code": 0, "data": {}}),
        json.dumps({"code": 0, "data": {"ok": True}}),
    ])
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or next(bodies),
    )

    with pytest.raises(BilibiliError) as exc_info:
        session.get_json("/x/space/wbi/arc/search", wbi=True, retry=1)
    assert exc_info.value.stop_reason == STOP_PARSER_FAILED

    result = session.get_json("/x/web-interface/card", retry=1)
    assert result["data"]["ok"] is True
    assert len(calls) == 2


def test_search_response_protection_trips_circuit_even_outside_get_json(
    monkeypatch,
):
    session = Session(browser_fallback=False)
    responses = iter([
        {"code": 0, "data": {"card": {"name": "safe"}}},
        {"code": -401, "message": "verification required"},
    ])
    monkeypatch.setattr(session, "get_json", lambda *args, **kwargs: next(responses))

    with pytest.raises(BilibiliError) as exc_info:
        session.discover_search("123", "https://space.bilibili.com/123", 30)
    assert exc_info.value.stop_reason == STOP_VERIFICATION

    calls: list[str] = []
    monkeypatch.setattr(
        session,
        "_curl",
        lambda url, referer: calls.append(url) or json.dumps({"code": 0}),
    )
    with pytest.raises(BilibiliError) as later:
        Session.get_json(session, "/x/web-interface/card", retry=1)
    assert later.value.stop_reason == STOP_VERIFICATION
    assert calls == []


def test_local_empty_and_parser_states_do_not_claim_access_restriction(
    monkeypatch,
):
    session = Session(browser_fallback=False)
    monkeypatch.setattr(
        session,
        "get_json",
        lambda *args, **kwargs: {"code": 0, "data": {"card": {}}},
    )
    with pytest.raises(BilibiliError) as search_error:
        session.discover_search("123", "https://space.bilibili.com/123", 30)
    assert search_error.value.stop_reason == STOP_PARSER_FAILED

    class EmptySession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return None

        def discover_medialist(self, mid, limit):
            return []

        def discover_arc(self, mid, limit):
            return []

        def discover_search(self, mid, url, limit):
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", EmptySession)
    with pytest.raises(BilibiliError) as empty_error:
        collector.collect_post_list("https://space.bilibili.com/123")
    assert empty_error.value.stop_reason == STOP_NO_PUBLIC_CONTENT


def test_empty_view_payload_is_parser_failure(monkeypatch):
    class EmptyViewSession:
        def ensure_buvid(self):
            return None

        def get_json(self, path, params):
            return {"code": 0, "data": None}

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", EmptyViewSession)

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_post_detail("https://www.bilibili.com/video/BV1abc")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED


def test_usage_never_promises_bilibili_browser_retry_after_protection():
    usage = (
        Path(__file__).resolve().parents[1] / "USAGE.md"
    ).read_text(encoding="utf-8")

    assert "该参数同时显式启用 B站既有的浏览器传输层降级" not in usage
    assert "设置为 `1` 启用 B站 传输层浏览器降级重试机制" not in usage
    faq = usage.split("### Q3:", 1)[1].split("### Q4:", 1)[0]
    assert "立即停止" in faq
    assert "浏览器" not in faq


def test_authoritative_docs_keep_bilibili_protection_and_comment_contracts_exact():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    skill = (root / "skill/SKILL.md").read_text(encoding="utf-8")
    bilibili = (
        root / "skill/references/platform-bilibili.md"
    ).read_text(encoding="utf-8")
    douyin = (
        root / "skill/references/platform-douyin.md"
    ).read_text(encoding="utf-8")
    exceptions = (
        root / "skill/references/exceptions.md"
    ).read_text(encoding="utf-8")

    assert "`--no-browser-fallback` 会同时禁止 B站和抖音" not in readme
    assert "`--no-browser-fallback` 同时禁止 B站和抖音" not in skill
    assert "同时禁止 B站和抖音启动浏览器" not in douyin
    assert "第 3 层：浏览器降级路径" not in bilibili
    assert "BILIBILI_BROWSER_FALLBACK=1" not in bilibili

    assert "B站" in readme and "平台保护" in readme and "立即停止" in readme
    assert "仅控制抖音" in skill
    assert "仅控制抖音" in douyin
    assert "第 3 层：平台保护停止策略" in bilibili
    assert "同一任务" in bilibili and "浏览器" in bilibili
    assert "COMMENTS_UNAVAILABLE" in exceptions
    assert "LOGIN_REQUIRED" in exceptions
    assert "VERIFICATION_REQUIRED" in exceptions
    assert "ACCESS_RESTRICTED" in exceptions
    assert "优先于此前的非平台保护原因" in exceptions
