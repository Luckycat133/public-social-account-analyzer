"""Offline tests for the Douyin browser-response transport."""

import json

import pytest

from collectors._constants import STOP_LOGIN, STOP_VERIFICATION


AWEME = {
    "aweme_id": "7001",
    "desc": "公开作品 #测试",
    "create_time": 1700000000,
    "statistics": {"digg_count": 12, "comment_count": 3},
    "video": {"duration": 9000},
}


ACCOUNT_URL = "https://www.douyin.com/user/example"


def _ssr_html(data):
    return '<script id="RENDER_DATA">' + json.dumps(data) + "</script>"


def test_collect_post_list_keeps_ssr_fast_path_without_browser(monkeypatch):
    """A valid SSR document must not start the optional browser fallback."""
    from collectors.douyin import DouyinCollector

    browser_calls = []
    collector = DouyinCollector(
        browser_collect=lambda **kwargs: browser_calls.append(kwargs),
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda url: _ssr_html({"user": {"post": {"data": [AWEME]}}}),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert [post["post_id"] for post in posts] == ["7001"]
    assert browser_calls == []


def test_collect_post_list_uses_browser_when_ssr_is_missing(monkeypatch):
    """Browser-aweme data shares the existing normalization path."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []

    def browser_collect(**kwargs):
        browser_calls.append(kwargs)
        return DouyinBrowserResult(aweme_items=[AWEME], source="network")

    collector = DouyinCollector(browser_collect=browser_collect)
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert browser_calls == [{"url": ACCOUNT_URL, "limit": 1, "date_range": None}]
    assert posts[0]["post_id"] == "7001"
    assert posts[0]["likes"] == 12


def test_collect_post_list_can_disable_browser_fallback(monkeypatch):
    """The opt-out preserves the previous public parser-failure behavior."""
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_fallback=False,
        browser_collect=lambda **kwargs: pytest.fail("browser should stay disabled"),
    )
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED


def test_collect_post_list_retains_normalized_partial_posts_on_restriction(monkeypatch):
    """A browser restriction retains already-collected normalized post data."""
    from collectors._constants import STOP_VERIFICATION
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[AWEME],
            source="network",
            restriction=STOP_VERIFICATION,
            diagnostics={"stop_condition": STOP_VERIFICATION},
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_VERIFICATION
    assert exc_info.value.partial_posts[0]["post_id"] == "7001"


class FakeBrowser:
    """Small in-memory CDP page double for bounded collection tests."""

    def __init__(self, events=(), bodies=None, body_errors=None, page_texts=(), cards=()):
        self.events = list(events)
        self.bodies = dict(bodies or {})
        self.body_errors = dict(body_errors or {})
        self.page_texts = list(page_texts)
        self.cards = list(cards)
        self.navigations = []
        self.scrolls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def navigate(self, url, timeout):
        self.navigations.append((url, timeout))

    def poll_event(self, timeout):
        return self.events.pop(0) if self.events else None

    def get_response_body(self, request_id):
        if request_id in self.body_errors:
            raise self.body_errors[request_id]
        return self.bodies[request_id]

    def page_text(self):
        return self.page_texts.pop(0) if self.page_texts else ""

    def scroll_by(self, viewports):
        self.scrolls.append(viewports)

    def evaluate(self, expression):
        return self.cards


RESPONSE_EVENT = {
    "method": "Network.responseReceived",
    "params": {
        "requestId": "r1",
        "type": "Fetch",
        "response": {
            "url": "https://www.douyin.com/aweme/v1/web/aweme/post/?signed=secret#x",
            "mimeType": "application/json",
        },
    },
}


def test_extract_aweme_items_deduplicates_nested_lists():
    from collectors._douyin_browser_transport import extract_aweme_items

    data = {"data": {"aweme_list": [AWEME, dict(AWEME)]}}
    assert [item["aweme_id"] for item in extract_aweme_items(data)] == ["7001"]


def test_extract_dom_items_only_keeps_post_links():
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://www.douyin.com/video/7002?x=1", "text": "作品二"},
        {"href": "https://www.douyin.com/search?q=x", "text": "搜索"},
    ]
    result = extract_dom_items(cards)
    assert result[0]["aweme_id"] == "7002"
    assert result[0]["statistics"] == {}
    assert result[0]["_collection_source"] == "dom"


def test_extract_dom_items_requires_exact_post_path():
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://www.douyin.com/video/7002/extra", "text": "无效"},
        {"href": "https://www.douyin.com/note/7003?x=1#part", "text": "有效"},
    ]

    result = extract_dom_items(cards)

    assert [item["aweme_id"] for item in result] == ["7003"]
    assert result[0]["share_url"] == "https://www.douyin.com/note/7003"


def test_restriction_priority_and_url_sanitization():
    from collectors._douyin_browser_transport import (
        detect_restriction,
        sanitize_response_url,
    )

    assert detect_restriction("请先登录并完成滑动验证") == STOP_VERIFICATION
    assert detect_restriction("登录后查看") == STOP_LOGIN
    assert sanitize_response_url("https://www.douyin.com/aweme/post/?secret=1#x") == (
        "https://www.douyin.com/aweme/post/"
    )


def test_sanitize_response_url_removes_userinfo_and_handles_ports():
    from collectors._douyin_browser_transport import sanitize_response_url

    assert sanitize_response_url(
        "https://name:password@www.douyin.com:8443/aweme/post/?secret=1#x"
    ) == "https://www.douyin.com:8443/aweme/post/"
    assert sanitize_response_url(
        "https://name:password@[2001:db8::1]:8443/aweme/post/?secret=1"
    ) == "https://[2001:db8::1]:8443/aweme/post/"
    assert sanitize_response_url(
        "https://name:password@www.douyin.com:not-a-port/aweme/post/?secret=1"
    ) == "https://www.douyin.com/aweme/post/"


def test_collect_account_page_keeps_allowed_network_items_and_safe_paths():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[RESPONSE_EVENT],
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example?secret=1",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.aweme_items == [AWEME]
    assert result.source == "network"
    assert result.diagnostics["response_paths"] == [
        "https://www.douyin.com/aweme/v1/web/aweme/post/"
    ]
    assert result.diagnostics["candidate_response_count"] == 1


def test_collect_account_page_returns_restriction_with_retained_items():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[RESPONSE_EVENT, None],
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
        page_texts=["", "请完成滑动验证"],
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=2,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.restriction == STOP_VERIFICATION
    assert result.aweme_items == [AWEME]
    assert result.diagnostics["stop_condition"] == STOP_VERIFICATION


def test_collect_account_page_uses_dom_cards_when_network_is_empty():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        cards=[{"href": "https://www.douyin.com/video/7002?token=secret", "text": "作品二"}],
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.source == "dom"
    assert result.aweme_items[0]["aweme_id"] == "7002"
    assert result.aweme_items[0]["share_url"] == "https://www.douyin.com/video/7002"


def test_collect_account_page_continues_after_response_body_is_unavailable():
    from collectors._douyin_browser_transport import collect_account_page
    from collectors.browser_backend import BrowserError

    later_event = {
        "method": "Network.responseReceived",
        "params": {
            "requestId": "r2",
            "type": "Fetch",
            "response": {
                "url": "https://www.iesdouyin.com/aweme/v1/web/aweme/post/?signed=later",
                "mimeType": "application/json",
            },
        },
    }
    browser = FakeBrowser(
        events=[RESPONSE_EVENT, later_event],
        bodies={"r2": json.dumps({"aweme_list": [AWEME]})},
        body_errors={"r1": BrowserError("response body is no longer available")},
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.aweme_items == [AWEME]
    assert result.diagnostics["response_paths"] == [
        "https://www.iesdouyin.com/aweme/v1/web/aweme/post/"
    ]
