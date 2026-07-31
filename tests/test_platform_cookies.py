"""Cookie-file contracts shared by the Weibo and Xiaohongshu session modes."""
from __future__ import annotations

import json

import pytest


COOKIE_SECRET = "session-secret-value"


def test_platform_cookie_file_accepts_matching_exported_domain(tmp_path):
    from collectors.platform_cookies import load_platform_cookie_file

    path = tmp_path / "weibo.json"
    path.write_text(
        json.dumps(
            [{
                "name": "SUB",
                "value": COOKIE_SECRET,
                "domain": ".weibo.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }]
        ),
        encoding="utf-8",
    )

    assert load_platform_cookie_file(path, "weibo.com") == (
        {
            "name": "SUB",
            "value": COOKIE_SECRET,
            "domain": ".weibo.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        },
    )


def test_platform_cookie_file_accepts_pasted_cookie_request_header(tmp_path):
    from collectors.platform_cookies import load_platform_cookie_file

    path = tmp_path / "weibo-header.txt"
    path.write_text(
        "Cookie: SUB=session-secret-value; XSRF-TOKEN=request-token",
        encoding="utf-8",
    )

    assert load_platform_cookie_file(path, "weibo.com") == (
        {
            "name": "SUB",
            "value": "session-secret-value",
            "domain": ".weibo.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
        {
            "name": "XSRF-TOKEN",
            "value": "request-token",
            "domain": ".weibo.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
    )


def test_platform_cookie_file_rejects_foreign_domain_without_leaking_secret(tmp_path):
    from collectors.platform_cookies import (
        PlatformCookieError,
        load_platform_cookie_file,
    )

    path = tmp_path / "foreign.json"
    path.write_text(
        json.dumps([{
            "name": "SUB",
            "value": COOKIE_SECRET,
            "domain": ".example.com",
        }]),
        encoding="utf-8",
    )

    with pytest.raises(PlatformCookieError) as exc:
        load_platform_cookie_file(path, "weibo.com")

    assert COOKIE_SECRET not in str(exc.value)


def test_cookie_loader_routes_bilibili_and_douyin_to_their_contracts(
    monkeypatch, tmp_path
):
    from collectors import cookie_loader

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cookie_loader,
        "load_platform_cookie_file",
        lambda path, domain: calls.append((str(path), domain)) or ({"name": domain},),
    )
    monkeypatch.setattr(
        cookie_loader,
        "load_douyin_cookie_file",
        lambda path: calls.append((str(path), "douyin")) or ({"name": "douyin"},),
    )

    assert cookie_loader.load_cookie_records(tmp_path / "bili.txt", "bilibili") == (
        {"name": "bilibili.com"},
    )
    assert cookie_loader.load_cookie_records(tmp_path / "douyin.txt", "douyin") == (
        {"name": "douyin"},
    )
    assert calls == [
        (str(tmp_path / "bili.txt"), "bilibili.com"),
        (str(tmp_path / "douyin.txt"), "douyin"),
    ]
