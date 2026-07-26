"""Offline policy tests for Bilibili protection and transport handling."""

from __future__ import annotations

import json
import subprocess

import pytest

from collectors.bilibili import (
    BilibiliCollector,
    BilibiliError,
    STOP_ACCESS_RESTRICTED,
    STOP_LOGIN,
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
