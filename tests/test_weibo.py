"""微博适配器（P2 正式接入）单元测试。

默认 ENABLED=True；显式停用的 ADAPTER_UNAVAILABLE 路径由 test_collectors.py 覆盖。
本文件验证公开采集/解析逻辑，
全程离线：用 monkeypatch 替换模块级 `_http_get_json`，不触网、不绕过登录。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import collectors.weibo as weibo
from collectors.weibo import (
    WeiboCollector,
    WeiboError,
    LOGIN_REQUIRED,
    ADAPTER_UNAVAILABLE,
    ACCOUNT_UNAVAILABLE,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_weibo_is_enabled_by_default(monkeypatch):
    """A P1 collector must be usable without an opt-in environment switch."""
    monkeypatch.delenv("WEIBO_COLLECTOR_ENABLED", raising=False)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'skill/scripts'); "
            "from collectors.weibo import ENABLED; raise SystemExit(not ENABLED)",
        ],
        cwd=REPO_ROOT,
        env={key: value for key, value in os.environ.items()
             if key != "WEIBO_COLLECTOR_ENABLED"},
        check=False,
    )

    assert result.returncode == 0


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(weibo, "ENABLED", True)
    monkeypatch.setattr(WeiboCollector, "ENABLED", True)
    yield


def _fake_json(url: str) -> dict:
    if "profile/info" in url:
        return {"data": {"user": {
            "id": 123456, "screen_name": "测试号", "description": "简介",
            "verified": True, "followers_count": 1000, "friends_count": 50,
            "statuses_count": 200,
        }}}
    if "mymblog" in url:
        # 仅第 1 页返回数据，后续页为空，模拟真实分页结束（避免无限翻页）
        if "page=1" in url:
            return {"data": {"list": [
                {"id": "a1", "text": "正文 #话题1# 内容", "created_at": "2026-01-01 12:00:00",
                 "isTop": True, "attitudes_count": 10, "comments_count": 5, "reposts_count": 3},
                {"id": "a2", "text": "转发 <a href='#'>@某人</a> 观点 #话题2#",
                 "created_at": "2026-01-02 08:30:00",
                 "retweeted_status": {"user": {"screen_name": "原博主"}},
                 "attitudes_count": 8, "comments_count": 2, "reposts_count": 1},
            ]}}
        return {"data": {"list": []}}
    if "statuses/show" in url:
        return {"data": {"status": {
            "id": "a1", "text": "单条详情 #话题1#", "created_at": "2026-01-01 12:00:00",
            "attitudes_count": 10, "comments_count": 5, "reposts_count": 3,
        }}}
    return {}


def test_enabled_collect_profile_parses(enabled, monkeypatch):
    monkeypatch.setattr(weibo, "_http_get_json", _fake_json)
    c = WeiboCollector()
    prof = c.collect_profile("https://weibo.com/u/123456")
    assert prof["account_name"] == "测试号"
    assert prof["followers"] == 1000
    assert prof["post_count"] == 200
    assert prof["verified"] is True
    # field_visibility 据实际字段可见性标注 visible
    assert prof["field_visibility"]["followers"] == "visible"
    assert prof["field_visibility"]["post_count"] == "visible"


def test_weibo_public_access_check_reports_accessible(enabled, monkeypatch):
    """Returning no `accessible` flag makes the orchestration reject public pages."""
    monkeypatch.setattr(weibo, "_http_get_json", _fake_json)

    assert WeiboCollector().check_access("https://weibo.com/u/123456") == {
        "accessible": True,
        "status": "ok",
        "stop_reason": None,
    }


def test_weibo_authorized_cookie_records_are_passed_to_public_requests(
    enabled, monkeypatch
):
    """A user-provided session must be used in-memory, never serialized by the adapter."""
    cookie_records = ({
        "name": "SUB",
        "value": "test-session-only",
        "domain": ".weibo.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    },)
    seen = []
    original_fake_json = _fake_json

    def _fake_json_with_records(url: str, records=()):
        seen.append((url, records))
        return original_fake_json(url)

    monkeypatch.setattr(weibo, "_http_get_json", _fake_json_with_records)

    profile = WeiboCollector(cookie_records=cookie_records).collect_profile(
        "https://weibo.com/u/123456"
    )

    assert profile["account_name"] == "测试号"
    assert seen == [
        ("https://weibo.com/ajax/profile/info?uid=123456", cookie_records)
    ]


def test_weibo_login_json_response_is_not_misclassified_as_missing_account():
    """The platform's explicit login marker must surface as LOGIN_REQUIRED."""
    response = {"ok": -100, "url": "https://weibo.com/login.php?url=example"}

    with pytest.raises(WeiboError) as exc:
        weibo._parse_json_response(response)

    assert exc.value.stop_reason == LOGIN_REQUIRED


def test_enabled_profile_canonicalizes_direct_profile_url(enabled, monkeypatch):
    monkeypatch.setattr(weibo, "_http_get_json", _fake_json)
    c = WeiboCollector()

    profile = c.collect_profile(
        "https://www.weibo.com/u/123456?token=PROFILE_SECRET#PROFILE_FRAGMENT"
    )

    assert profile["profile_url"] == "https://weibo.com/u/123456"


def test_enabled_collect_post_list_parses(enabled, monkeypatch):
    monkeypatch.setattr(weibo, "_http_get_json", _fake_json)
    c = WeiboCollector()
    posts = c.collect_post_list("https://weibo.com/u/123456", limit=30)
    assert len(posts) == 2
    # 置顶识别
    assert posts[0]["is_pinned"] is True
    # 转发识别 + 话题标签提取（HTML 已剥离）
    assert posts[1]["is_repost"] is True
    assert "话题2" in (posts[1].get("hashtags") or [])
    # 时间解析为 ISO(+08:00)
    assert posts[0]["published_at"] == "2026-01-01T12:00:00+08:00"
    # 指标映射：shares=转发, likes=点赞, favorites=微博恒为 None
    assert posts[0]["likes"] == 10
    assert posts[0]["shares"] == 3
    assert posts[0]["favorites"] is None


def test_enabled_collect_post_detail_parses(enabled, monkeypatch):
    monkeypatch.setattr(weibo, "_http_get_json", _fake_json)
    c = WeiboCollector()
    post = c.collect_post_detail("https://weibo.com/123456/a1")
    assert post["post_id"] == "a1"
    assert "话题1" in (post.get("hashtags") or [])
    assert post["is_pinned"] is None
    assert post["is_repost"] is None
    assert post["is_promoted"] is None


def test_weibo_time_normalized_to_beijing():
    assert weibo._parse_weibo_time(
        "Wed Oct 10 20:40:00 +0000 2012"
    ) == "2012-10-11T04:40:00+08:00"


def test_weibo_boolean_evidence_parses_explicit_zero_without_truthiness():
    raw = weibo._build_post_raw(
        {
            "id": "a1",
            "isTop": "0",
            "retweeted_status": None,
        },
        "123456",
    )

    assert raw["is_pinned"] is False
    assert raw["is_repost"] is False
    assert raw["is_promoted"] is None


def test_enabled_detail_rejects_item_id_hidden_in_untrusted_host(
    enabled, monkeypatch
):
    monkeypatch.setattr(
        weibo,
        "_http_get_json",
        lambda _url: pytest.fail("invalid item URL must not fetch"),
    )
    c = WeiboCollector()

    with pytest.raises(WeiboError) as exc:
        c.collect_post_detail(
            "https://evil.example/path/weibo.com/123456/a1?token=EVIL_SECRET"
        )

    assert exc.value.stop_reason == "PARSER_FAILED"
    assert "EVIL_SECRET" not in str(exc.value)


def test_enabled_comments_raise_unavailable_instead_of_false_empty(enabled):
    c = WeiboCollector()

    with pytest.raises(WeiboError) as exc:
        c.collect_comments("https://weibo.com/123456/a1")

    assert exc.value.stop_reason == "COMMENTS_UNAVAILABLE"
    assert str(exc.value) == "[COMMENTS_UNAVAILABLE] 微博公开评论采样未实现"


def test_login_wall_raises_login_required(enabled, monkeypatch):
    def _boom(url: str):
        raise WeiboError(LOGIN_REQUIRED, "微博要求登录")
    monkeypatch.setattr(weibo, "_http_get_json", _boom)
    c = WeiboCollector()
    with pytest.raises(WeiboError) as exc:
        c.collect_profile("https://weibo.com/u/123456")
    assert exc.value.stop_reason == LOGIN_REQUIRED


def test_disabled_still_adapter_unavailable(monkeypatch):
    # 确保测试环境未开启
    monkeypatch.setattr(weibo, "ENABLED", False)
    monkeypatch.setattr(WeiboCollector, "ENABLED", False)
    c = WeiboCollector()
    with pytest.raises(RuntimeError) as exc:
        c.collect_profile("https://weibo.com/u/123456")
    assert ADAPTER_UNAVAILABLE in str(exc.value)


def test_weibo_does_not_treat_302_as_login_required():
    """C3: a 302 is a normal HTTP redirect. urllib follows 30x by default, so
    HTTPError 302 only fires when the redirect lands on a non-HTTP scheme
    or a chain. It must not be classified as LOGIN_REQUIRED, which would
    block every name-based account URL on the first redirect.

    The docstring on the weibo collector now claims 401/403 are the only
    login-wall triggers; this test pins that contract.
    """
    import urllib.error

    from collectors.weibo import WeiboError, _http_get_text

    class _Boom:
        def __init__(self, code):
            self.code = code

    request = _Boom(302)

    def fake_urlopen(_req, timeout=None):
        raise urllib.error.HTTPError(
            "https://weibo.com/jack",
            302,
            "Found",
            None,
            None,
        )

    import collectors.weibo as weibo_mod
    original = weibo_mod.urllib.request.urlopen
    weibo_mod.urllib.request.urlopen = fake_urlopen
    try:
        with pytest.raises(WeiboError) as exc_info:
            _http_get_text("https://weibo.com/jack")
    finally:
        weibo_mod.urllib.request.urlopen = original

    # 302 must NOT be LOGIN_REQUIRED — the redirect target is unknown,
    # so ACCESS_RESTRICTED is the conservative fallback.
    assert exc_info.value.stop_reason != "LOGIN_REQUIRED"


def test_weibo_401_still_triggers_login_required():
    """Pinned positive control: 401 still maps to LOGIN_REQUIRED after
    the 302/405 removal."""
    import urllib.error

    from collectors.weibo import WeiboError, _http_get_text

    def fake_urlopen(_req, timeout=None):
        raise urllib.error.HTTPError(
            "https://weibo.com/u/123456",
            401,
            "Unauthorized",
            None,
            None,
        )

    import collectors.weibo as weibo_mod
    original = weibo_mod.urllib.request.urlopen
    weibo_mod.urllib.request.urlopen = fake_urlopen
    try:
        with pytest.raises(WeiboError) as exc_info:
            _http_get_text("https://weibo.com/u/123456")
    finally:
        weibo_mod.urllib.request.urlopen = original

    assert exc_info.value.stop_reason == "LOGIN_REQUIRED"


def test_weibo_429_maps_to_rate_limited(monkeypatch):
    import urllib.error

    from collectors.weibo import WeiboError, _http_get_text

    def fake_urlopen(_req, timeout=None):
        raise urllib.error.HTTPError(
            "https://weibo.com/u/123456",
            429,
            "Too Many Requests",
            None,
            None,
        )

    monkeypatch.setattr("collectors.weibo.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(WeiboError) as exc_info:
        _http_get_text("https://weibo.com/u/123456")

    assert exc_info.value.stop_reason == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# 命名主页 UID 身份绑定（真实 smoke 发现：带 cookie 页面首个 "uid" 是会话主人）
# ---------------------------------------------------------------------------

_SESSION_UID_FIRST_PAGE = """
<script>window.__INITIAL_STATE__={"user":{"id":0,"screen_name":"...","url":"https://weibo.com/u/7962883086"},
"uid":7962883086,"isLogin":true,"env":{"uid":7962883086}}</script>
<div class="profile">{"domain":"cctvnews","screen_name":"央视新闻","url":"https://weibo.com/cctvnews","id":1686546714}</div>
"""


def _page_fetcher(page_text):
    def fetch_text(url):
        return page_text
    return fetch_text


def _verified_fetch_json(profiles: dict):
    """profile/info 回证器：按 uid 返回预设 user；未预置则返回空 user。"""
    def fetch_json(url):
        for uid, user in profiles.items():
            if f"uid={uid}" in url:
                return {"data": {"user": user}}
        return {"data": {"user": {}}}
    return fetch_json


def test_named_page_skips_session_uid_and_binds_owner_via_verification():
    """首个 uid 是会话主人时必须通过 profile/info 回证绑定到 handle 主人。"""
    fetch_text = _page_fetcher(_SESSION_UID_FIRST_PAGE)
    fetch_json = _verified_fetch_json({
        "7962883086": {"id": 7962883086, "screen_name": "用户7962883086",
                       "url": "https://weibo.com/u/7962883086", "domain": ""},
        "1686546714": {"id": 1686546714, "screen_name": "央视新闻",
                       "url": "https://weibo.com/cctvnews", "domain": "cctvnews"},
    })
    uid = weibo._resolve_uid("https://weibo.com/cctvnews", fetch_text, fetch_json)
    assert uid == "1686546714"


def test_named_page_owner_uid_alone_resolves_when_verified():
    """只有 handle 锚定的 owner uid 时，回证通过即返回该 uid。"""
    page = '<div id="profile">{"id":1686546714,"domain":"cctvnews","url":"https://weibo.com/cctvnews"}</div>'
    fetch_json = _verified_fetch_json({
        "1686546714": {"id": 1686546714, "domain": "cctvnews",
                       "url": "https://weibo.com/cctvnews"},
    })
    assert weibo._resolve_uid("https://weibo.com/cctvnews", _page_fetcher(page), fetch_json) == "1686546714"


def test_named_page_unverified_session_uid_fails_honestly():
    """页面只有会话主人 uid 且回证不匹配时，绝不返回错误账号，如实失败。"""
    page = '<script>window.__INITIAL_STATE__={"uid":7962883086,"isLogin":true}</script>'
    fetch_json = _verified_fetch_json({
        "7962883086": {"id": 7962883086, "screen_name": "用户7962883086",
                       "url": "https://weibo.com/u/7962883086", "domain": ""},
    })
    with pytest.raises(WeiboError) as exc:
        weibo._resolve_uid("https://weibo.com/cctvnews", _page_fetcher(page), fetch_json)
    assert exc.value.stop_reason == ACCOUNT_UNAVAILABLE
    assert "身份未回证" in str(exc.value)


def test_named_page_login_stub_raises_login_required():
    """匿名访问命名主页拿到登录 stub 时上报 LOGIN_REQUIRED 而非 ACCOUNT_UNAVAILABLE。"""
    stub = '<html><head><title>登录</title></head><body><script>window.location.href="passport.weibo.com"</script></body></html>'
    with pytest.raises(WeiboError) as exc:
        weibo._resolve_uid("https://weibo.com/cctvnews", _page_fetcher(stub), None)
    assert exc.value.stop_reason == LOGIN_REQUIRED


def test_named_page_verification_propagates_login_wall():
    """回证 profile/info 遇到登录墙时保留 LOGIN_REQUIRED，不降级为找不到账号。"""
    def fetch_json(url):
        raise WeiboError(LOGIN_REQUIRED, "微博公开接口要求登录")
    with pytest.raises(WeiboError) as exc:
        weibo._resolve_uid("https://weibo.com/cctvnews", _page_fetcher(_SESSION_UID_FIRST_PAGE), fetch_json)
    assert exc.value.stop_reason == LOGIN_REQUIRED


def test_numeric_uid_never_fetches_html():
    """数字 UID 主页不请求 HTML，也不触发回证。"""
    calls = []

    def fetch_text(url):
        calls.append(url)
        return ""

    def fetch_json(url):
        calls.append(url)
        return {}

    uid = weibo._resolve_uid("https://weibo.com/u/123456", fetch_text, fetch_json)
    assert uid == "123456"
    assert calls == []
