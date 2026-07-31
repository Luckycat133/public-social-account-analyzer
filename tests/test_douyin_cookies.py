"""User-authorized Douyin cookie input contracts."""

from __future__ import annotations

import json

import pytest


ACCOUNT_URL = "https://www.douyin.com/user/example"
COOKIE_SECRET = "session-secret-value"


def test_load_douyin_cookie_file_accepts_exported_json_array(tmp_path):
    from collectors.douyin_cookies import load_douyin_cookie_file

    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "sessionid",
                    "value": COOKIE_SECRET,
                    "domain": ".douyin.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    assert load_douyin_cookie_file(path) == (
        {
            "name": "sessionid",
            "value": COOKIE_SECRET,
            "domain": ".douyin.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        },
    )


def test_load_douyin_cookie_file_accepts_cookie_header_text(tmp_path):
    from collectors.douyin_cookies import load_douyin_cookie_file

    path = tmp_path / "cookies.txt"
    path.write_text("sessionid=abc; sid_guard=def\n", encoding="utf-8")

    records = load_douyin_cookie_file(path)

    assert [(item["name"], item["value"]) for item in records] == [
        ("sessionid", "abc"),
        ("sid_guard", "def"),
    ]
    assert all(item["domain"] == ".douyin.com" for item in records)


def test_load_douyin_cookie_file_rejects_foreign_domain_without_leaking_secret(
    tmp_path,
):
    from collectors.douyin_cookies import DouyinCookieError, load_douyin_cookie_file

    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "sessionid",
                    "value": COOKIE_SECRET,
                    "domain": ".example.com",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(DouyinCookieError) as exc_info:
        load_douyin_cookie_file(path)

    assert COOKIE_SECRET not in str(exc_info.value)


def test_browser_session_injects_cookie_records_through_cdp(monkeypatch):
    from collectors.browser_backend import BrowserSession

    calls = []
    session = BrowserSession()
    monkeypatch.setattr(
        session,
        "_send_cdp",
        lambda method, params: calls.append((method, params)) or {"success": True},
    )

    session.set_cookie_records(
        (
            {
                "name": "sessionid",
                "value": COOKIE_SECRET,
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
        )
    )

    assert calls == [
        (
            "Network.setCookie",
            {
                "name": "sessionid",
                "value": COOKIE_SECRET,
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
        )
    ]


def test_browser_session_rejects_failed_cookie_injection_without_secret(monkeypatch):
    from collectors.browser_backend import BrowserError, BrowserSession

    session = BrowserSession()
    monkeypatch.setattr(
        session,
        "_send_cdp",
        lambda _method, _params: {"success": False},
    )

    with pytest.raises(BrowserError) as exc_info:
        session.set_cookie_records(
            (
                {
                    "name": "sessionid",
                    "value": COOKIE_SECRET,
                    "domain": ".douyin.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
            )
        )

    assert COOKIE_SECRET not in str(exc_info.value)


def test_user_cookie_session_can_continue_past_anonymous_login_wall(monkeypatch):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    captured = {}

    def browser_collect(**request):
        captured.update(request)
        return DouyinBrowserResult(
            aweme_items=[
                {
                    "aweme_id": "7001",
                    "desc": "公开作品",
                    "create_time": 1700000000,
                    "author": {"sec_uid": "example"},
                }
            ],
            profile_raw=None,
            source="network",
            coverage={},
        )

    collector = DouyinCollector(
        browser_collect=browser_collect,
        cookie_records=(
            {
                "name": "sessionid",
                "value": COOKIE_SECRET,
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
        ),
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "登录后查看")

    assert collector.check_access(ACCOUNT_URL)["accessible"] is True
    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert posts[0]["post_id"] == "7001"
    assert captured["cookie_records"][0]["value"] == COOKIE_SECRET
    assert COOKIE_SECRET not in json.dumps(
        collector.get_collection_coverage(), ensure_ascii=False
    )


def test_user_cookie_session_continues_when_anonymous_fetch_returns_401(monkeypatch):
    from collectors._constants import STOP_LOGIN
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        cookie_records=(
            {
                "name": "sessionid",
                "value": COOKIE_SECRET,
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
        )
    )

    def fail(_url):
        raise DouyinError(STOP_LOGIN, "controlled login wall")

    monkeypatch.setattr(collector, "_fetch", fail)

    assert collector.check_access(ACCOUNT_URL)["accessible"] is True


def test_browser_profile_cache_survives_anonymous_login_wall(monkeypatch):
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        cookie_records=(
            {
                "name": "sessionid",
                "value": COOKIE_SECRET,
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
        )
    )
    collector._cache_browser_profile(
        ACCOUNT_URL,
        {
            "account_name": "目标账号",
            "profile_url": ACCOUNT_URL,
            "platform_metrics": {"sec_uid": "example"},
        },
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "登录后查看")

    assert collector.collect_profile(ACCOUNT_URL)["account_name"] == "目标账号"


def test_account_browser_transport_injects_cookie_before_navigation():
    from collectors._douyin_browser_transport import collect_account_page

    events = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def set_cookie_records(self, records):
            events.append(("cookies", records))

        def navigate(self, url, timeout):
            events.append(("navigate", url))

        def poll_event(self, timeout):
            return None

        def page_text(self):
            return "暂无公开作品"

        def scroll_by(self, viewports):
            return None

        def evaluate(self, expression):
            return {"profile": {"sec_uid": "example"}, "cards": []}

    records = (
        {
            "name": "sessionid",
            "value": COOKIE_SECRET,
            "domain": ".douyin.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        },
    )
    collect_account_page(
        ACCOUNT_URL,
        limit=1,
        max_seconds=1,
        max_scrolls=1,
        cookie_records=records,
        session_factory=Session,
    )

    assert events[:2] == [("cookies", records), ("navigate", ACCOUNT_URL)]
