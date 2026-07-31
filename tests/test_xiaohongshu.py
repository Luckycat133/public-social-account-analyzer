"""Offline contracts for the Xiaohongshu public-page collector."""
from __future__ import annotations

import json

import pytest


PROFILE_URL = "https://www.xiaohongshu.com/user/profile/5f2a1b3c4d5e6f708192a3b4"
NOTE_URL = "https://www.xiaohongshu.com/explore/66aabbccddeeff0011223344"


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
