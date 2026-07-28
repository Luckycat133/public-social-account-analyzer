"""微博适配器（P2 正式接入）单元测试。

默认 ENABLED=False（ADAPTER_UNAVAILABLE 路径由 test_collectors.py 覆盖）。
本文件验证开启（WEIBO_COLLECTOR_ENABLED）后的真实采集/解析逻辑，
全程离线：用 monkeypatch 替换模块级 `_http_get_json`，不触网、不绕过登录。
"""
import pytest

import collectors.weibo as weibo
from collectors.weibo import (
    WeiboCollector,
    WeiboError,
    LOGIN_REQUIRED,
    ADAPTER_UNAVAILABLE,
)


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
