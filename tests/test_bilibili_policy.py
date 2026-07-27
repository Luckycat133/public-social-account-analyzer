"""Offline policy tests for Bilibili protection and transport handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from collectors.bilibili import (
    BilibiliCollector,
    BilibiliError,
    STOP_ACCOUNT_UNAVAILABLE,
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


def test_arc_page_protection_keeps_prior_page_entries(monkeypatch):
    session = Session(browser_fallback=False)
    calls = 0

    def get_json(path, params=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {"bvid": f"BVarc{index}", "created": 300 - index}
                            for index in range(50)
                        ]
                    }
                },
            }
        raise BilibiliError(STOP_ACCESS_RESTRICTED, "page blocked")

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    with pytest.raises(BilibiliError) as exc_info:
        session.discover_arc("123", 51)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(exc_info.value.partial_entries) == 50
    assert exc_info.value.partial_entries[0]["bvid"] == "BVarc0"


def test_medialist_date_window_pages_past_newer_items(monkeypatch):
    session = Session(browser_fallback=False)
    pages = [
        {
            "code": 0,
            "data": {
                "media_list": [
                    {
                        "id": index,
                        "bv_id": f"BVnew{index}",
                        "pubtime": 300 - index,
                    }
                    for index in range(20)
                ],
                "has_more": True,
            },
        },
        {
            "code": 0,
            "data": {
                "media_list": [
                    {
                        "id": 100 + index,
                        "bv_id": f"BVmatch{index}",
                        "pubtime": 200 - index,
                    }
                    for index in range(5)
                ],
                "has_more": False,
            },
        },
    ]
    calls = []

    def get_json(path, params=None, **kwargs):
        calls.append(params["oid"])
        return pages[len(calls) - 1]

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    entries = session.discover_medialist(
        "123",
        5,
        date_range=(
            "1970-01-01T08:03:10+08:00",
            "1970-01-01T08:03:30+08:00",
        ),
    )

    assert calls == ["0", "19"]
    assert [entry["bv_id"] for entry in entries] == [
        "BVmatch0",
        "BVmatch1",
        "BVmatch2",
        "BVmatch3",
        "BVmatch4",
    ]


def test_medialist_deduplicates_page_boundary_before_applying_limit(monkeypatch):
    session = Session(browser_fallback=False)
    pages = [
        {
            "code": 0,
            "data": {
                "media_list": [
                    {
                        "id": index + 1,
                        "bv_id": f"BVunique{index}",
                        "pubtime": 300 - index,
                    }
                    for index in range(20)
                ],
                "has_more": True,
            },
        },
        {
            "code": 0,
            "data": {
                "media_list": [
                    {
                        "id": 20,
                        "bv_id": "BVunique19",
                        "pubtime": 281,
                    },
                    *[
                        {
                            "id": index + 1,
                            "bv_id": f"BVunique{index}",
                            "pubtime": 300 - index,
                        }
                        for index in range(20, 31)
                    ],
                ],
                "has_more": False,
            },
        },
    ]
    calls = 0

    def get_json(path, params=None, **kwargs):
        nonlocal calls
        response = pages[calls]
        calls += 1
        return response

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    entries = session.discover_medialist("123", 30)

    ids = [entry["bv_id"] for entry in entries]
    assert len(ids) == len(set(ids)) == 30
    assert ids[-1] == "BVunique29"
    assert calls == 2


def test_medialist_page_protection_keeps_prior_page_entries(monkeypatch):
    session = Session(browser_fallback=False)
    calls = 0

    def get_json(path, params=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "code": 0,
                "data": {
                    "media_list": [
                        {
                            "id": index + 1,
                            "bv_id": f"BVpage{index}",
                            "pubtime": 300 - index,
                            "cnt_info": {"play": index},
                        }
                        for index in range(20)
                    ],
                    "has_more": True,
                },
            }
        raise BilibiliError(STOP_ACCESS_RESTRICTED, "page blocked")

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    with pytest.raises(BilibiliError) as exc_info:
        session.discover_medialist("123", 30)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(exc_info.value.partial_entries) == 20
    assert exc_info.value.partial_entries[0]["bv_id"] == "BVpage0"


def test_post_list_converts_prior_medialist_pages_to_partial_posts(monkeypatch):
    class ProtectedSecondPageSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, "BVpage0"

        def discover_medialist(self, mid, limit):
            raise BilibiliError(
                STOP_ACCESS_RESTRICTED,
                "page blocked",
                partial_entries=[
                    {
                        "bv_id": "BVpage0",
                        "title": "retained first-page record",
                        "pubtime": 300,
                        "cnt_info": {"play": 0, "reply": 0},
                    }
                ],
            )

        def discover_arc(self, mid, limit):
            raise AssertionError("must stop after platform protection")

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", ProtectedSecondPageSession)

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_post_list(
            "https://space.bilibili.com/123", limit=30
        )

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(exc_info.value.partial_posts) == 1
    retained = exc_info.value.partial_posts[0]
    assert retained["post_id"] == "BVpage0"
    assert retained["title"] == "retained first-page record"
    assert retained["views"] == 0
    assert retained["comments"] == 0
    assert retained["is_pinned"] is True


def test_dynamic_page_protection_keeps_prior_page_cards(monkeypatch):
    session = Session(browser_fallback=False)
    calls = 0

    dynamic_item = {
        "orig": None,
        "modules": {
            "module_author": {"pub_ts": 300},
            "module_dynamic": {
                "major": {
                    "archive": {
                        "bvid": "BVdynamic",
                        "title": "retained dynamic",
                        "stat": {"play": 0, "danmaku": 0},
                    }
                }
            },
            "module_stat": {
                "like": {"count": 0},
                "comment": {"count": 0},
                "forward": {"count": 0},
            },
        },
    }

    def get_json(path, params=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "code": 0,
                "data": {
                    "items": [dynamic_item],
                    "has_more": True,
                    "offset": "next",
                },
            }
        raise BilibiliError(STOP_ACCESS_RESTRICTED, "page blocked")

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    with pytest.raises(BilibiliError) as exc_info:
        session.discover_dynamics("123", 2)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert len(exc_info.value.partial_entries) == 1
    assert exc_info.value.partial_entries[0]["bvid"] == "BVdynamic"


def test_post_list_keeps_dynamic_page_records_on_protection(monkeypatch):
    class DynamicProtectionSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return [
                {
                    "bv_id": "BVregular",
                    "title": "regular",
                    "pubtime": 200,
                    "cnt_info": {"play": 1},
                }
            ]

        def collect_tags(self, bvid):
            return []

        def discover_dynamics(self, mid, limit):
            raise BilibiliError(
                STOP_ACCESS_RESTRICTED,
                "page blocked",
                partial_entries=[
                    {
                        "bvid": "BVdynamic",
                        "title": "retained dynamic",
                        "pub_ts": 300,
                        "is_forward": False,
                        "stat": {
                            "play": 0,
                            "like": 0,
                            "comment": 0,
                            "forward": 0,
                            "danmaku": 0,
                        },
                    }
                ],
            )

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", DynamicProtectionSession)

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_post_list(
            "https://space.bilibili.com/123", limit=2
        )

    assert [post["post_id"] for post in exc_info.value.partial_posts] == [
        "BVdynamic",
        "BVregular",
    ]
    assert exc_info.value.partial_posts[0]["views"] == 0
    assert exc_info.value.partial_posts[0]["collection_status"] == "PARTIAL"


def test_post_list_forwards_date_window_to_all_discovery_paths(monkeypatch):
    requested_range = (
        "1970-01-01T08:03:10+08:00",
        "1970-01-01T08:03:30+08:00",
    )
    calls = []

    class DateAwareSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit, date_range=None):
            calls.append(("medialist", date_range))
            return [{
                "bv_id": "BVrange",
                "title": "in range",
                "pubtime": 200,
                "cnt_info": {"play": 1},
            }]

        def collect_tags(self, bvid):
            return []

        def discover_dynamics(self, mid, limit, date_range=None):
            calls.append(("dynamics", date_range))
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", DateAwareSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123",
        limit=1,
        date_range=requested_range,
    )

    assert [post["post_id"] for post in posts] == ["BVrange"]
    assert calls == [
        ("medialist", requested_range),
        ("dynamics", requested_range),
    ]


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
    expected_visibility = (
        "visible"
        if isinstance(observation, str) or observation[0] is True
        else "hidden"
    )
    assert [
        post["field_visibility"]["is_pinned"] for post in posts
    ] == [expected_visibility, expected_visibility]


def test_post_list_never_emits_duplicate_regular_post_ids(monkeypatch):
    class DuplicateMedialistSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return [
                {
                    "bv_id": "BVduplicate",
                    "title": "first observation wins",
                    "pubtime": 200,
                    "cnt_info": {"play": 1},
                },
                {
                    "bv_id": "BVduplicate",
                    "title": "duplicate observation",
                    "pubtime": 200,
                    "cnt_info": {"play": 1},
                },
            ]

        def collect_tags(self, bvid):
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", DuplicateMedialistSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123", limit=2
    )

    assert [post["post_id"] for post in posts] == ["BVduplicate"]
    assert posts[0]["title"] == "first observation wins"


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


def test_profile_reuses_card_observed_during_access_check(monkeypatch):
    class CardThenBlockedSession:
        def __init__(self):
            self.calls = 0

        def ensure_buvid(self):
            return None

        def get_json(self, path, params=None, **kwargs):
            self.calls += 1
            if self.calls == 1 and path == "/x/web-interface/card":
                return {
                    "code": 0,
                    "data": {
                        "card": {
                            "mid": 123,
                            "name": "cached profile",
                            "sign": "public bio",
                            "fans": 5,
                            "archive_count": 7,
                            "level_info": {"current_level": 2},
                            "official": {"type": -1},
                        }
                    },
                }
            raise BilibiliError(STOP_ACCESS_RESTRICTED, "circuit open")

    session = CardThenBlockedSession()
    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", lambda: session)

    assert collector.check_access(
        "https://space.bilibili.com/123"
    )["accessible"] is True
    profile = collector.collect_profile("https://space.bilibili.com/123")

    assert session.calls == 1
    assert profile["account_name"] == "cached profile"
    assert profile["followers"] == 5
    assert profile["post_count"] == 7
    assert profile["level"] == 2


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


def test_arc_detail_failure_keeps_list_evidence_as_partial(monkeypatch):
    class ArcDetailFailureSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return []

        def discover_arc(self, mid, limit):
            return [{
                "bvid": "BVpartial",
                "title": "list title",
                "play": 12,
                "comment": 0,
                "video_review": 1,
            }]

        def get_json(self, path, params=None, **kwargs):
            raise BilibiliError(STOP_PARSER_FAILED, "malformed view")

        def collect_tags(self, bvid):
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", ArcDetailFailureSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123", limit=1
    )

    assert len(posts) == 1
    assert posts[0]["title"] == "list title"
    assert posts[0]["views"] == 12
    assert posts[0]["comments"] == 0
    assert posts[0]["collection_status"] == "PARTIAL"
    assert posts[0]["platform_metrics"]["detail_status"] == "UNAVAILABLE"


def test_unexpected_arc_detail_error_is_isolated_to_one_post(monkeypatch):
    class UnexpectedDetailFailureSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return []

        def discover_arc(self, mid, limit):
            return [
                {"bvid": "BVbroken", "title": "list survives", "play": 1},
                {"bvid": "BVhealthy", "title": "list title", "play": 2},
            ]

        def get_json(self, path, params=None, **kwargs):
            if params["bvid"] == "BVbroken":
                raise ValueError("unexpected decoder failure")
            return {
                "code": 0,
                "data": {
                    "bvid": "BVhealthy",
                    "title": "detail succeeds",
                    "pubdate": 200,
                    "stat": {
                        "view": 2,
                        "like": 1,
                        "reply": 0,
                        "favorite": 0,
                        "share": 0,
                        "coin": 0,
                        "danmaku": 0,
                    },
                },
            }

        def collect_tags(self, bvid):
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", UnexpectedDetailFailureSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123", limit=2
    )

    by_id = {post["post_id"]: post for post in posts}
    assert by_id["BVbroken"]["title"] == "list survives"
    assert by_id["BVbroken"]["collection_status"] == "PARTIAL"
    assert by_id["BVbroken"]["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert by_id["BVhealthy"]["title"] == "detail succeeds"
    assert by_id["BVhealthy"]["collection_status"] == "SUCCESS"


def test_deleted_arc_post_is_marked_deleted_without_stopping_batch(monkeypatch):
    class DeletedDetailSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return []

        def discover_arc(self, mid, limit):
            return [
                {"bvid": "BVdeleted", "title": "old list title", "play": 1},
                {"bvid": "BVhealthy", "title": "list title", "play": 2},
            ]

        def get_json(self, path, params=None, **kwargs):
            if params["bvid"] == "BVdeleted":
                raise BilibiliError(
                    STOP_ACCOUNT_UNAVAILABLE,
                    "video was deleted",
                )
            return {
                "code": 0,
                "data": {
                    "bvid": "BVhealthy",
                    "title": "detail succeeds",
                    "pubdate": 200,
                    "stat": {
                        "view": 2,
                        "like": 1,
                        "reply": 0,
                        "favorite": 0,
                        "share": 0,
                        "coin": 0,
                        "danmaku": 0,
                    },
                },
            }

        def collect_tags(self, bvid):
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", DeletedDetailSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123", limit=2
    )

    by_id = {post["post_id"]: post for post in posts}
    assert by_id["BVdeleted"]["collection_status"] == "DELETED"
    assert by_id["BVdeleted"]["platform_metrics"]["detail_status"] == "DELETED"
    assert by_id["BVhealthy"]["collection_status"] == "SUCCESS"


def test_platform_protection_carries_posts_collected_before_the_stop(monkeypatch):
    class TagProtectionSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return [
                {"bv_id": "BVone", "title": "one", "cnt_info": {"play": 1}},
                {"bv_id": "BVtwo", "title": "two", "cnt_info": {"play": 2}},
            ]

        def collect_tags(self, bvid):
            if bvid == "BVtwo":
                raise BilibiliError(STOP_ACCESS_RESTRICTED, "restricted")
            return []

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", TagProtectionSession)

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_post_list(
            "https://space.bilibili.com/123", limit=2
        )

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert [post["post_id"] for post in exc_info.value.partial_posts] == [
        "BVone",
        "BVtwo",
    ]
    assert [
        post["collection_status"] for post in exc_info.value.partial_posts
    ] == ["SUCCESS", "PARTIAL"]


def test_post_list_merges_dynamic_only_posts_and_deduplicates_bvid(monkeypatch):
    tag_calls: list[str] = []

    class RegularAndDynamicSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            return [
                {
                    "bv_id": "BVregular",
                    "title": "regular",
                    "pubtime": 100,
                    "cnt_info": {"play": 10},
                },
                {
                    "bv_id": "BVduplicate",
                    "title": "regular wins duplicate",
                    "pubtime": 200,
                    "cnt_info": {"play": 20},
                },
            ]

        def collect_tags(self, bvid):
            tag_calls.append(bvid)
            return []

        def discover_dynamics(self, mid, limit):
            return [
                {
                    "bvid": "BVduplicate",
                    "title": "dynamic duplicate",
                    "pub_ts": 200,
                    "is_forward": False,
                    "stat": {"play": 200},
                },
                {
                    "bvid": "BVdynamic",
                    "title": "dynamic only",
                    "pub_ts": 300,
                    "is_forward": False,
                    "stat": {"play": 30},
                },
            ]

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", RegularAndDynamicSession)

    posts = collector.collect_post_list(
        "https://space.bilibili.com/123", limit=3
    )

    assert [post["post_id"] for post in posts] == [
        "BVdynamic",
        "BVduplicate",
        "BVregular",
    ]
    assert posts[0]["content_type"] == "dynamic"
    assert posts[0]["collection_status"] == "PARTIAL"
    assert posts[1]["content_type"] == "video"
    assert posts[1]["title"] == "regular wins duplicate"
    assert tag_calls == ["BVdynamic", "BVduplicate", "BVregular"]
    assert collector.get_collection_coverage() == {
        "regular_source": "medialist",
        "regular_observed_count": 2,
        "dynamic_status": "OBSERVED",
        "dynamic_observed_count": 2,
    }


def test_dynamic_protection_stops_before_optional_tags_and_records_substage(
    monkeypatch,
):
    events: list[str] = []

    class DynamicProtectionSession:
        def ensure_buvid(self):
            return None

        def collect_pinned(self, mid):
            return True, None

        def discover_medialist(self, mid, limit):
            events.append("regular")
            return [{
                "bv_id": "BVregular",
                "title": "regular",
                "pubtime": 100,
                "cnt_info": {
                    "play": 1,
                    "thumb_up": 0,
                    "reply": 0,
                    "collect": 0,
                    "share": 0,
                    "coin": 0,
                    "danmaku": 0,
                },
            }]

        def discover_dynamics(self, mid, limit):
            events.append("dynamic")
            raise BilibiliError(
                STOP_ACCESS_RESTRICTED,
                "SECRET_DYNAMIC_RESPONSE",
            )

        def collect_tags(self, bvid):
            events.append("tag")
            pytest.fail("tag enrichment must not run after dynamic protection")

    collector = BilibiliCollector(browser_fallback=False)
    monkeypatch.setattr(collector, "_new_session", DynamicProtectionSession)

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_post_list(
            "https://space.bilibili.com/123",
            limit=1,
        )

    error = exc_info.value
    assert error.stop_reason == STOP_ACCESS_RESTRICTED
    assert error.diagnostic_code == "BILIBILI_DYNAMIC_DISCOVERY"
    assert events == ["regular", "dynamic"]
    assert [post["post_id"] for post in error.partial_posts] == ["BVregular"]
    assert error.partial_posts[0]["collection_status"] == "SUCCESS"
    assert collector.get_collection_coverage() == {
        "regular_source": "medialist",
        "regular_observed_count": 1,
        "dynamic_status": "ACCESS_RESTRICTED",
        "dynamic_observed_count": 0,
    }


def test_dynamic_page_protection_keeps_partial_cards_and_safe_diagnostic(
    monkeypatch,
):
    session = Session(browser_fallback=False)
    calls = 0

    def get_json(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "code": 0,
                "data": {
                    "items": [{
                        "orig": None,
                        "modules": {
                            "module_author": {"pub_ts": 100},
                            "module_dynamic": {
                                "major": {
                                    "archive": {
                                        "bvid": "BVpartial",
                                        "title": "partial",
                                        "stat": {},
                                    }
                                }
                            },
                            "module_stat": {},
                        },
                    }],
                    "has_more": True,
                    "offset": "safe-in-memory-offset",
                },
            }
        raise BilibiliError(
            STOP_ACCESS_RESTRICTED,
            "SECRET_PLATFORM_BODY",
        )

    monkeypatch.setattr(session, "get_json", get_json)
    monkeypatch.setattr("collectors.bilibili.time.sleep", lambda _: None)

    with pytest.raises(BilibiliError) as exc_info:
        session.discover_dynamics("123", 2)

    assert exc_info.value.diagnostic_code == "BILIBILI_DYNAMIC_DISCOVERY"
    assert [card["bvid"] for card in exc_info.value.partial_entries] == [
        "BVpartial"
    ]


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
