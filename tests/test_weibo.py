"""微博适配器（P2 正式接入）单元测试。

默认 ENABLED=False（ADAPTER_UNAVAILABLE 路径由 test_collectors.py 覆盖）。
本文件验证开启（WEIBO_COLLECTOR_ENABLED）后的真实采集/解析逻辑，
全程离线：用 monkeypatch 替换模块级 `_http_get_json`，不触网、不绕过登录。
"""
import pytest

import collect
import collectors.weibo as weibo
from collectors.weibo import (
    WeiboCollector,
    WeiboError,
    STOP_LOGIN,
    STOP_ADAPTER_UNAVAILABLE,
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


def test_enabled_check_access_uses_base_collector_success_contract(enabled, monkeypatch):
    monkeypatch.setattr(weibo, "_http_get_json", _fake_json)

    access = WeiboCollector().check_access("https://weibo.com/u/123456")

    assert access["accessible"] is True
    # status 是平台扩展字段：微博仍提供 ok，但 BaseCollector 不要求所有适配器使用它。
    assert access.get("status") == "ok"
    assert access["stop_reason"] is None


def test_enabled_weibo_collect_run_continues_past_access_check(enabled, monkeypatch, tmp_path):
    """已启用的微博适配器不能因 access 成功响应缺字段而在编排层失败。"""
    calls = []

    def tracked_json(url):
        calls.append(url)
        return _fake_json(url)

    monkeypatch.setattr(weibo, "_http_get_json", tracked_json)
    monkeypatch.setattr(weibo.time, "sleep", lambda _: None)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [WeiboCollector()])

    out_dir = tmp_path / "weibo-run"
    assert collect.run("https://weibo.com/u/123456", out_dir=str(out_dir)) == 0
    assert any("mymblog" in url for url in calls)
    assert (out_dir / "source" / "profile.json").exists()


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


def test_login_wall_raises_login_required(enabled, monkeypatch):
    def _boom(url: str):
        raise WeiboError(STOP_LOGIN, "微博要求登录")
    monkeypatch.setattr(weibo, "_http_get_json", _boom)
    c = WeiboCollector()
    with pytest.raises(WeiboError) as exc:
        c.collect_profile("https://weibo.com/u/123456")
    assert exc.value.stop_reason == STOP_LOGIN


def test_disabled_still_adapter_unavailable(monkeypatch):
    # 确保测试环境未开启
    monkeypatch.setattr(weibo, "ENABLED", False)
    monkeypatch.setattr(WeiboCollector, "ENABLED", False)
    c = WeiboCollector()
    with pytest.raises(RuntimeError) as exc:
        c.collect_profile("https://weibo.com/u/123456")
    assert STOP_ADAPTER_UNAVAILABLE in str(exc.value)
