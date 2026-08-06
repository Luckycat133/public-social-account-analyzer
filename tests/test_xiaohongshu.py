"""Offline contracts for the Xiaohongshu public-page collector."""
from __future__ import annotations

import json
import inspect

import pytest


PROFILE_URL = "https://www.xiaohongshu.com/user/profile/5f2a1b3c4d5e6f708192a3b4"
NOTE_URL = "https://www.xiaohongshu.com/explore/66aabbccddeeff0011223344"


def test_xiaohongshu_429_maps_to_rate_limited(monkeypatch):
    import urllib.error

    from collectors.xiaohongshu import XiaohongshuError, _http_get_text

    def fake_urlopen(_request, timeout=None):
        raise urllib.error.HTTPError(
            PROFILE_URL,
            429,
            "Too Many Requests",
            None,
            None,
        )

    monkeypatch.setattr(
        "collectors.xiaohongshu.urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(XiaohongshuError) as exc_info:
        _http_get_text(PROFILE_URL)

    assert exc_info.value.stop_reason == "RATE_LIMITED"


def test_xiaohongshu_canonical_urls_bind_profile_and_note_ids():
    """Rejecting genuine Xiaohongshu public URLs would route them outside the pipeline."""
    from collectors.url_policy import canonical_item_url, canonical_profile_url

    assert canonical_profile_url("xiaohongshu", PROFILE_URL + "?source=share") == PROFILE_URL
    assert canonical_item_url("xiaohongshu", NOTE_URL + "?xsec_token=redacted") == NOTE_URL
    assert canonical_profile_url(
        "xiaohongshu", "https://www.xiaohongshu.com/explore/66aabbccddeeff0011223344"
    ) is None
    assert canonical_item_url(
        "xiaohongshu", "https://evil.example/explore/66aabbccddeeff0011223344"
    ) is None


def test_xiaohongshu_resume_identity_uses_the_canonical_profile_url():
    """Incremental collection must bind an existing Xiaohongshu workspace to one account."""
    import collect

    assert collect._canonical_resume_identity(PROFILE_URL + "?from=share") == (
        "xiaohongshu",
        PROFILE_URL,
    )


def test_xiaohongshu_collector_normalizes_public_page_state(monkeypatch):
    """Missing public fields stay null while page-state notes retain direct evidence URLs."""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    page_state = {
        "user": {
            "userId": "5f2a1b3c4d5e6f708192a3b4",
            "nickname": "测试薯",
            "desc": "公开简介",
            "follows": "12",
            "fans": "1.2万",
            "redId": "test-red-id",
        },
        "notes": [
            {
                "noteId": "66aabbccddeeff0011223344",
                "title": "夏日穿搭 #通勤#",
                "desc": "正文内容 #通勤#",
                "type": "normal",
                "time": "2026-07-01T08:00:00+08:00",
                "likedCount": "234",
                "collectedCount": "12",
                "commentCount": "7",
                "shareCount": "3",
                "isTop": False,
            }
        ],
    }
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: "<script id=\"__XHS_INITIAL_STATE__\">" + xiaohongshu.json.dumps(page_state) + "</script>")

    collector = XiaohongshuCollector()
    assert collector.check_access(PROFILE_URL)["accessible"] is True
    profile = collector.collect_profile(PROFILE_URL)
    posts = collector.collect_post_list(PROFILE_URL, limit=30)

    assert profile["account_name"] == "测试薯"
    assert profile["followers"] == 12000
    assert profile["post_count"] is None
    assert len(posts) == 1
    assert posts[0]["post_id"] == "66aabbccddeeff0011223344"
    assert posts[0]["post_url"] == NOTE_URL
    assert posts[0]["likes"] == 234
    assert posts[0]["favorites"] == 12
    assert posts[0]["comments"] == 7
    assert posts[0]["shares"] == 3
    assert posts[0]["views"] is None
    assert posts[0]["field_visibility"]["views"] == "hidden"


def test_xiaohongshu_modern_profile_state_maps_one_verified_batch(monkeypatch):
    """Modern SSR must bind the target URL, flatten its cards, and never retain tokens."""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    viewer_id = "aaaaaaaaaaaaaaaaaaaaaaaa"
    xsec_token = "private-routing-token-must-not-survive"
    state = {
        "user": {
            "userInfo": {"userId": viewer_id},
            "userPageData": {
                "basicInfo": {
                    "nickname": "现代测试薯",
                    "desc": "公开简介",
                    "redId": "modern-red-id",
                },
                "interactions": [
                    {"type": "follows", "count": "12"},
                    {"type": "fans", "count": "1.2万"},
                    {"type": "interaction", "count": "3.4万"},
                ],
                "result": {"success": True, "code": 0, "message": "success"},
            },
            "notes": [[{
                "id": "66aabbccddeeff0011223344",
                "xsecToken": xsec_token,
                "noteCard": {
                    "noteId": None,
                    "displayTitle": "主页一次返回整批笔记",
                    "type": "normal",
                    "user": {
                        "userId": "5f2a1b3c4d5e6f708192a3b4",
                        "nickname": "现代测试薯",
                    },
                    "interactInfo": {"likedCount": "234", "sticky": True},
                    "xsecToken": xsec_token,
                },
            }], [], [], [], []],
        },
        "probe": "__UNDEFINED__",
    }
    payload = json.dumps(state, ensure_ascii=False).replace(
        '"__UNDEFINED__"', "undefined"
    )
    page = f"<script>window.__INITIAL_STATE__={payload};</script>"
    calls = []

    def _fake_text(url: str):
        calls.append(url)
        return page

    monkeypatch.setattr(xiaohongshu, "_http_get_text", _fake_text)

    collector = XiaohongshuCollector()
    assert collector.check_access(PROFILE_URL)["accessible"] is True
    profile = collector.collect_profile(PROFILE_URL)
    posts = collector.collect_post_list(PROFILE_URL, limit=30)

    assert calls == [PROFILE_URL]
    assert profile["account_id"] == "5f2a1b3c4d5e6f708192a3b4"
    assert profile["account_id"] != viewer_id
    assert profile["account_name"] == "现代测试薯"
    assert profile["followers"] == 12000
    assert profile["platform_metrics"] == {
        "following": 12,
        "red_id": "modern-red-id",
        "likes_and_favorites": 34000,
        "identity_binding": "target_owned_card",
    }
    assert len(posts) == 1
    assert posts[0]["post_url"] == NOTE_URL
    assert posts[0]["title"] == "主页一次返回整批笔记"
    assert posts[0]["likes"] == 234
    assert posts[0]["is_pinned"] is True
    serialized = json.dumps({"profile": profile, "posts": posts})
    assert xsec_token not in serialized
    assert viewer_id not in serialized


def test_xiaohongshu_modern_profile_rejects_foreign_note_cards(monkeypatch):
    """An unbound foreign store cannot become the target profile or sample."""
    from collectors.xiaohongshu import (
        PARSER_FAILED,
        XiaohongshuCollector,
        XiaohongshuError,
    )
    import collectors.xiaohongshu as xiaohongshu

    state = {
        "user": {
            "userPageData": {
                "basicInfo": {"nickname": "目标账号"},
                "interactions": [],
                "result": {"success": True, "code": 0},
            },
            "notes": [[{
                "noteCard": {
                    "noteId": "66aabbccddeeff0011223344",
                    "displayTitle": "外来笔记",
                    "user": {"userId": "bbbbbbbbbbbbbbbbbbbbbbbb"},
                    "interactInfo": {"likedCount": "999"},
                }
            }]],
        }
    }
    page = "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: page)

    with pytest.raises(XiaohongshuError) as exc:
        XiaohongshuCollector().collect_post_list(PROFILE_URL)

    assert exc.value.stop_reason == PARSER_FAILED


def test_xiaohongshu_modern_profile_accepts_explicit_target_binding_without_cards(
    monkeypatch,
):
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    target_id = PROFILE_URL.rsplit("/", 1)[-1]
    state = {
        "user": {
            "userPageData": {
                "basicInfo": {
                    "userId": target_id,
                    "nickname": "明确绑定账号",
                },
                "interactions": [],
                "result": {"success": True, "code": 0},
            },
            "notes": [],
        }
    }
    page = "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: page)

    profile = XiaohongshuCollector().collect_profile(PROFILE_URL)

    assert profile["account_id"] == target_id
    assert profile["account_name"] == "明确绑定账号"
    assert profile["platform_metrics"]["identity_binding"] == "profile_user_id"


def test_xiaohongshu_direct_fetch_rejects_redirect_to_another_page(monkeypatch):
    from collectors.xiaohongshu import XiaohongshuError, _http_get_text

    class RedirectedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "https://www.xiaohongshu.com/explore/66aabbccddeeff0011223344"

        def read(self):
            return b"<html>wrong page</html>"

    monkeypatch.setattr(
        "collectors.xiaohongshu.urllib.request.urlopen",
        lambda *_args, **_kwargs: RedirectedResponse(),
    )

    with pytest.raises(XiaohongshuError) as exc_info:
        _http_get_text(PROFILE_URL)

    assert exc_info.value.stop_reason == "ACCOUNT_UNAVAILABLE"


def test_xiaohongshu_modern_anonymous_cards_remain_disclosed_partial_evidence(
    monkeypatch,
):
    """Blank platform IDs may form a batch sample, but never fake item identity."""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    state = {
        "user": {
            "userPageData": {
                "basicInfo": {"nickname": "匿名主页样本"},
                "interactions": [],
                "result": {"success": True, "code": 0},
            },
            "notes": [[{
                "id": "",
                "xsecToken": "must-not-survive",
                "noteCard": {
                    "noteId": "",
                    "displayTitle": "无作品 ID 的主页卡片",
                    "type": "video",
                    "user": {"userId": "5f2a1b3c4d5e6f708192a3b4"},
                    "interactInfo": {"likedCount": "88", "sticky": False},
                    "xsecToken": "must-not-survive",
                },
            }]],
        }
    }
    page = "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: page)

    first = XiaohongshuCollector().collect_post_list(PROFILE_URL)
    second = XiaohongshuCollector().collect_post_list(PROFILE_URL)

    assert len(first) == 1
    assert first[0]["post_id"] == second[0]["post_id"]
    assert first[0]["post_id"].startswith("xhs-card-")
    assert first[0]["post_url"] is None
    assert first[0]["source_url"] == PROFILE_URL
    assert first[0]["collection_status"] == "PARTIAL"
    assert first[0]["likes"] == 88
    assert first[0]["platform_metrics"] == {
        "note_type": "video",
        "collection_source": "xiaohongshu_profile_cards",
        "platform_post_id_known": False,
        "local_record_key": True,
        "item_url_known": False,
        "source_rank": 1,
    }
    assert "must-not-survive" not in json.dumps(first)


def test_xiaohongshu_profile_card_anchor_survives_standard_pipeline(
    monkeypatch, tmp_path
):
    """The generic URL sanitizer must retain a disclosed profile-card anchor."""
    import collect
    import collectors.xiaohongshu as xiaohongshu
    from collectors.xiaohongshu import XiaohongshuCollector

    state = {
        "user": {
            "userPageData": {
                "basicInfo": {"nickname": "匿名主页样本"},
                "interactions": [],
            },
            "notes": [[{
                "id": "",
                "noteCard": {
                    "noteId": "",
                    "displayTitle": "批量卡片",
                    "user": {"userId": "5f2a1b3c4d5e6f708192a3b4"},
                    "interactInfo": {"likedCount": "7"},
                },
            }]],
        }
    }
    page = "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: page)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [XiaohongshuCollector()])
    output = tmp_path / "xiaohongshu-profile-cards"

    assert collect.run(PROFILE_URL, limit=1, out_dir=str(output)) == 0

    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    post = json.loads(
        (output / "source" / "posts.jsonl").read_text(encoding="utf-8")
    )
    assert task["task_status"] == "PARTIAL"
    assert post["post_url"] is None
    assert post["source_url"] == PROFILE_URL


def test_xiaohongshu_authorized_cookie_records_are_passed_to_direct_page_request(
    monkeypatch,
):
    """A user session changes only the direct-page request, not the parsing contract."""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    cookie_records = ({
        "name": "web_session",
        "value": "test-session-only",
        "domain": ".xiaohongshu.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    },)
    page_state = {"user": {"userId": "u1", "nickname": "测试薯"}, "notes": []}
    seen = []

    def _fake_text(url: str, records=()):
        seen.append((url, records))
        return '<script id="__XHS_INITIAL_STATE__">' + json.dumps(page_state) + "</script>"

    monkeypatch.setattr(xiaohongshu, "_http_get_text", _fake_text)

    result = XiaohongshuCollector(cookie_records=cookie_records).check_access(
        PROFILE_URL
    )

    assert result["accessible"] is True
    assert seen == [(PROFILE_URL, cookie_records)]


def test_xiaohongshu_login_page_stops_without_profile_parse(monkeypatch):
    """A login wall must be reported instead of being treated as an empty public account."""
    from collectors.xiaohongshu import LOGIN_REQUIRED, XiaohongshuCollector, XiaohongshuError
    import collectors.xiaohongshu as xiaohongshu

    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: "请登录后继续访问")

    with pytest.raises(XiaohongshuError) as exc:
        XiaohongshuCollector().check_access(PROFILE_URL)

    assert exc.value.stop_reason == LOGIN_REQUIRED


def test_xiaohongshu_script_login_token_does_not_hide_valid_page_state(monkeypatch):
    """Only visible login-wall text may stop a page that contains public state."""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    page_state = {"user": {"userId": "u1", "nickname": "测试薯"}, "notes": []}
    page = (
        "<script>const login = {enabled: false};</script>"
        '<script id="__XHS_INITIAL_STATE__">'
        + json.dumps(page_state)
        + "</script>"
    )
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: page)

    assert XiaohongshuCollector().check_access(PROFILE_URL)["accessible"] is True


def test_xiaohongshu_cookie_login_wall_uses_one_browser_render_attempt(monkeypatch):
    """A Cookie session gets one browser-rendered page attempt, never API retries."""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    cookie_records = ({
        "name": "web_session",
        "value": "test-session-only",
        "domain": ".xiaohongshu.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    },)
    page_state = {"user": {"userId": "u1", "nickname": "测试薯"}, "notes": []}
    seen = []
    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url, _records: "请登录后继续访问")

    def _browser_html(url, records):
        seen.append((url, records))
        return '<script id="__XHS_INITIAL_STATE__">' + json.dumps(page_state) + "</script>"

    monkeypatch.setattr(
        xiaohongshu, "_browser_rendered_html", _browser_html, raising=False
    )

    result = XiaohongshuCollector(cookie_records=cookie_records).check_access(
        PROFILE_URL
    )

    assert result["accessible"] is True
    assert seen == [(PROFILE_URL, cookie_records)]


def test_xiaohongshu_browser_fallback_obeys_collector_policy():
    """The shared CLI policy must be able to disable XHS browser rendering."""
    import collect

    parameters = inspect.signature(collect._load_adapters).parameters
    assert "xiaohongshu_browser_fallback" in parameters

    adapters = collect._load_adapters(xiaohongshu_browser_fallback=False)
    collector = next(
        adapter for adapter in adapters if adapter.platform == "xiaohongshu"
    )
    assert collector._browser_fallback is False


def test_xiaohongshu_verification_page_stops_with_verification_reason(monkeypatch):
    """A challenge is not interchangeable with a login wall and must never be retried as one."""
    from collectors.xiaohongshu import (
        VERIFICATION_REQUIRED,
        XiaohongshuCollector,
        XiaohongshuError,
    )
    import collectors.xiaohongshu as xiaohongshu

    monkeypatch.setattr(xiaohongshu, "_http_get_text", lambda _url: "请完成滑块验证")

    with pytest.raises(XiaohongshuError) as exc:
        XiaohongshuCollector().check_access(PROFILE_URL)

    assert exc.value.stop_reason == VERIFICATION_REQUIRED


def test_xiaohongshu_enters_the_standard_collection_pipeline(monkeypatch, tmp_path):
    """A routed public profile must produce the same sealed collection artifacts as other platforms."""
    import collect
    import collectors.xiaohongshu as xiaohongshu
    from collectors.xiaohongshu import XiaohongshuCollector

    page_state = {
        "user": {"userId": "5f2a1b3c4d5e6f708192a3b4", "nickname": "测试薯"},
        "notes": [{
            "noteId": "66aabbccddeeff0011223344",
            "title": "测试笔记",
            "time": "2026-07-01T08:00:00+08:00",
            "likedCount": "1",
        }],
    }
    monkeypatch.setattr(
        xiaohongshu,
        "_http_get_text",
        lambda _url: '<script id="__XHS_INITIAL_STATE__">'
        + json.dumps(page_state) + "</script>",
    )
    monkeypatch.setattr(collect, "_load_adapters", lambda: [XiaohongshuCollector()])
    output = tmp_path / "xiaohongshu-collection"

    assert collect.run(PROFILE_URL, limit=1, out_dir=str(output)) == 0

    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    assert task["platform"] == "xiaohongshu"
    assert task["task_status"] == "COMPLETED"
    assert (output / "source" / "profile.json").is_file()
    assert (output / "source" / "posts.jsonl").is_file()
    assert (output / "collection-report.md").is_file()
    assert (output / ".complete").is_file()


def test_xiaohongshu_direct_http_success_never_invokes_browser(monkeypatch):
    """带 Cookie 直接 HTTP 已能解析状态时，绝不允许启动浏览器降级（对齐 eval #34）。"""
    from collectors.xiaohongshu import XiaohongshuCollector
    import collectors.xiaohongshu as xiaohongshu

    cookie_records = ({
        "name": "web_session",
        "value": "test-session-only",
        "domain": ".xiaohongshu.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    },)
    page_state = {"user": {"userId": "u1", "nickname": "测试薯"}, "notes": [{
        "noteId": "66aabbccddeeff0011223344", "title": "直接 HTTP 命中",
        "type": "normal", "time": "2026-07-01T08:00:00+08:00", "likedCount": "1",
    }]}

    def _fake_text(url: str, records=()):
        return '<script id="__XHS_INITIAL_STATE__">' + json.dumps(page_state) + "</script>"

    def _must_not_browser(url, records):
        raise AssertionError("直接 HTTP 成功时不得启动浏览器降级")

    monkeypatch.setattr(xiaohongshu, "_http_get_text", _fake_text)
    monkeypatch.setattr(xiaohongshu, "_browser_rendered_html", _must_not_browser)

    posts = XiaohongshuCollector(cookie_records=cookie_records).collect_post_list(
        PROFILE_URL, limit=10
    )
    assert len(posts) == 1
    assert posts[0]["post_id"] == "66aabbccddeeff0011223344"
