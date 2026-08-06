"""User-authorized Cookie persistence contracts (workspace cache + auto-load)."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

import collect


COOKIE_SECRET = "session-secret-value"
BILI_RECORD = {
    "name": "sessionid",
    "value": COOKIE_SECRET,
    "domain": ".bilibili.com",
    "path": "/",
    "secure": True,
    "httpOnly": True,
}
DOUYIN_RECORD = {
    "name": "ttwid",
    "value": COOKIE_SECRET,
    "domain": ".douyin.com",
    "path": "/",
    "secure": True,
    "httpOnly": True,
}
WEIBO_RECORD = {
    "name": "SUB",
    "value": COOKIE_SECRET,
    "domain": ".weibo.com",
    "path": "/",
    "secure": True,
    "httpOnly": True,
}
XHS_RECORD = {
    "name": "web_session",
    "value": COOKIE_SECRET,
    "domain": ".xiaohongshu.com",
    "path": "/",
    "secure": True,
    "httpOnly": True,
}


def _save_records(platform: str, records, path):
    from collectors.cookie_loader import save_cookie_records

    save_cookie_records(tuple(records), path, platform)


def _read_mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_save_then_load_round_trip_for_bilibili(tmp_path):
    from collectors.cookie_loader import load_cookie_records

    target = tmp_path / "bilibili-cookies.json"
    _save_records("bilibili", [BILI_RECORD], target)
    assert _read_mode(target) == 0o600
    loaded = load_cookie_records(target, "bilibili")
    assert len(loaded) == 1
    assert loaded[0]["name"] == BILI_RECORD["name"]
    assert loaded[0]["value"] == COOKIE_SECRET


def test_save_then_load_round_trip_for_douyin(tmp_path):
    from collectors.cookie_loader import load_cookie_records

    target = tmp_path / "douyin-cookies.json"
    _save_records("douyin", [DOUYIN_RECORD], target)
    assert _read_mode(target) == 0o600
    loaded = load_cookie_records(target, "douyin")
    assert loaded[0]["domain"] == ".douyin.com"


def test_save_then_load_round_trip_for_weibo_and_xiaohongshu(tmp_path):
    from collectors.cookie_loader import load_cookie_records

    weibo_target = tmp_path / "weibo-cookies.json"
    _save_records("weibo", [WEIBO_RECORD], weibo_target)
    assert _read_mode(weibo_target) == 0o600
    assert load_cookie_records(weibo_target, "weibo")[0]["name"] == "SUB"

    xhs_target = tmp_path / "xiaohongshu-cookies.json"
    _save_records("xiaohongshu", [XHS_RECORD], xhs_target)
    assert _read_mode(xhs_target) == 0o600
    assert load_cookie_records(xhs_target, "xiaohongshu")[0]["name"] == "web_session"


def test_save_rejects_empty_records(tmp_path):
    from collectors.cookie_loader import save_cookie_records
    from collectors.platform_cookies import PlatformCookieError

    with pytest.raises(PlatformCookieError):
        save_cookie_records((), tmp_path / "x.json", "bilibili")


def test_save_rejects_cross_domain_record(tmp_path):
    from collectors.cookie_loader import save_cookie_records
    from collectors.platform_cookies import PlatformCookieError

    bad = {**BILI_RECORD, "domain": ".not-bilibili.com"}
    with pytest.raises(PlatformCookieError):
        save_cookie_records((bad,), tmp_path / "x.json", "bilibili")


def test_load_cached_cookie_records_returns_empty_when_missing(tmp_path):
    from collectors.cookie_loader import load_cached_cookie_records

    assert load_cached_cookie_records(str(tmp_path), "bilibili") == ()


def test_load_cached_cookie_records_round_trip(tmp_path):
    from collectors.cookie_loader import load_cached_cookie_records, save_cookie_records

    save_cookie_records((BILI_RECORD,), tmp_path / "bilibili-cookies.json", "bilibili")
    cached = load_cached_cookie_records(str(tmp_path), "bilibili")
    assert len(cached) == 1
    assert cached[0]["value"] == COOKIE_SECRET


def test_load_cached_cookie_records_per_platform_isolation(tmp_path):
    from collectors.cookie_loader import load_cached_cookie_records, save_cookie_records

    save_cookie_records((BILI_RECORD,), tmp_path / "bilibili-cookies.json", "bilibili")
    assert load_cached_cookie_records(str(tmp_path), "douyin") == ()


def test_load_cached_cookie_records_swallows_corrupt_file(tmp_path):
    from collectors.cookie_loader import load_cached_cookie_records

    target = tmp_path / "bilibili-cookies.json"
    target.write_text("{not-json-and-not-cookie-header}", encoding="utf-8")
    assert load_cached_cookie_records(str(tmp_path), "bilibili") == ()


def test_save_overwrites_existing_file(tmp_path):
    from collectors.cookie_loader import load_cookie_records, save_cookie_records

    target = tmp_path / "bilibili-cookies.json"
    save_cookie_records((BILI_RECORD,), target, "bilibili")
    newer = {**BILI_RECORD, "name": "refresh", "value": "v2"}
    save_cookie_records((newer,), target, "bilibili")
    assert _read_mode(target) == 0o600
    loaded = load_cookie_records(target, "bilibili")
    assert loaded[0]["name"] == "refresh"
    assert loaded[0]["value"] == "v2"


def test_save_replaces_permissive_existing_file_with_mode_0600(tmp_path):
    target = tmp_path / "bilibili-cookies.json"
    target.write_text("stale", encoding="utf-8")
    target.chmod(0o644)

    _save_records("bilibili", [BILI_RECORD], target)

    assert _read_mode(target) == 0o600


def test_save_rejects_symlink_without_touching_its_target(tmp_path):
    from collectors.platform_cookies import PlatformCookieError

    victim = tmp_path / "victim.json"
    victim.write_text("do-not-touch", encoding="utf-8")
    target = tmp_path / "bilibili-cookies.json"
    target.symlink_to(victim)

    with pytest.raises(PlatformCookieError):
        _save_records("bilibili", [BILI_RECORD], target)

    assert victim.read_text(encoding="utf-8") == "do-not-touch"
    assert target.is_symlink()


def test_load_cached_cookie_records_rejects_symlink(tmp_path):
    from collectors.cookie_loader import load_cached_cookie_records

    source = tmp_path / "source.json"
    _save_records("bilibili", [BILI_RECORD], source)
    (tmp_path / "bilibili-cookies.json").symlink_to(source)

    assert load_cached_cookie_records(str(tmp_path), "bilibili") == ()


def test_save_creates_parent_directory(tmp_path):
    from collectors.cookie_loader import load_cookie_records, save_cookie_records

    target = tmp_path / "nested" / "bilibili-cookies.json"
    save_cookie_records((BILI_RECORD,), target, "bilibili")
    assert load_cookie_records(target, "bilibili")[0]["name"] == "sessionid"


def test_saved_payload_is_valid_json(tmp_path):
    from collectors.cookie_loader import save_cookie_records

    target = tmp_path / "bilibili-cookies.json"
    save_cookie_records((BILI_RECORD,), target, "bilibili")
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    assert parsed[0]["name"] == "sessionid"


def test_cached_cookie_for_another_platform_does_not_block_target_run(
    monkeypatch, tmp_path, capsys
):
    from collectors.base import BaseCollector

    cache_root = tmp_path / "cookies"
    _save_records(
        "bilibili",
        [BILI_RECORD],
        cache_root / "bilibili-cookies.json",
    )

    class RestrictedDouyinAdapter(BaseCollector):
        platform = "douyin"

        def supports(self, url):
            return "douyin.com/user/" in url

        def check_access(self, url):
            return {"accessible": False, "stop_reason": "LOGIN_REQUIRED"}

        def collect_profile(self, url):
            raise AssertionError("restricted access must stop before profile")

        def collect_post_list(self, url, limit=30, date_range=None):
            raise AssertionError("restricted access must stop before posts")

        def collect_post_detail(self, post_url):
            raise AssertionError("restricted access must stop before details")

    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: [RestrictedDouyinAdapter()],
    )

    result = collect.run(
        "https://www.douyin.com/user/example",
        limit=1,
        out_dir=str(tmp_path / "output"),
        cookie_workspace_root=str(cache_root),
    )

    captured = capsys.readouterr()
    assert result == 3
    assert "只适用于B站账号主页" not in captured.err


def test_persist_failure_stops_before_network_and_does_not_touch_symlink_target(
    monkeypatch, tmp_path
):
    from collectors.base import BaseCollector

    source = tmp_path / "provided.json"
    _save_records("bilibili", [BILI_RECORD], source)
    cache_root = tmp_path / "cookies"
    cache_root.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("unchanged", encoding="utf-8")
    (cache_root / "bilibili-cookies.json").symlink_to(victim)

    class MatchingBilibiliAdapter(BaseCollector):
        platform = "bilibili"

        def supports(self, url):
            return True

        def check_access(self, url):
            raise AssertionError("persistence must finish before network")

        def collect_profile(self, url):
            raise AssertionError("must not collect")

        def collect_post_list(self, url, limit=30, date_range=None):
            raise AssertionError("must not collect")

        def collect_post_detail(self, post_url):
            raise AssertionError("must not collect")

    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: [MatchingBilibiliAdapter()],
    )

    result = collect.run(
        "https://space.bilibili.com/123",
        limit=1,
        out_dir=str(tmp_path / "output"),
        bilibili_cookie_file=str(source),
        persist_cookie=True,
        cookie_workspace_root=str(cache_root),
    )

    assert result == 2
    assert victim.read_text(encoding="utf-8") == "unchanged"
    assert not (tmp_path / "output").exists()


def test_clear_cached_cookie_is_standalone_and_skips_collection(
    monkeypatch, tmp_path, capsys
):
    cache_root = tmp_path / "cookies"
    target = cache_root / "bilibili-cookies.json"
    _save_records("bilibili", [BILI_RECORD], target)
    monkeypatch.setattr(
        collect,
        "run",
        lambda *args, **kwargs: pytest.fail("clear action must not collect"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect.py",
            "--clear-cached-cookie",
            "bilibili",
            "--cookie-store-path",
            str(cache_root),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert not target.exists()
    assert "bilibili" in capsys.readouterr().out


def test_cli_still_requires_url_for_collection(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["collect.py"])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2
