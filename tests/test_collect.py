"""Focused CLI hygiene regressions for the public collection entry point."""

from __future__ import annotations

import sys

import pytest

import collect


DOUYIN_URL = "https://www.douyin.com/user/example"
WEIBO_URL = "https://weibo.com/u/123456"
XIAOHONGSHU_URL = "https://www.xiaohongshu.com/user/profile/5f2a1b3c4d5e6f708192a3b4"
BILIBILI_URL = "https://space.bilibili.com/123456"


def test_social_browser_fallback_whitelist(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SOCIAL_BROWSER_FALLBACK", "false")
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: pytest.fail("adapter loading must not run"),
    )

    assert collect.run(DOUYIN_URL, out_dir=str(tmp_path / "task")) == 2
    assert "SOCIAL_BROWSER_FALLBACK" in capsys.readouterr().err


def test_cli_leaves_budget_validation_to_run(monkeypatch):
    validation_calls = []
    forwarded = {}

    def record_validation(*values):
        validation_calls.append(values)
        return values

    def fake_run(*args, **kwargs):
        forwarded.update(kwargs)
        return 0

    monkeypatch.setattr(collect, "validate_public_all_budgets", record_validation)
    monkeypatch.setattr(collect, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect.py",
            DOUYIN_URL,
            "--all",
            "--max-items",
            "500",
            "--max-seconds",
            "60",
            "--max-scrolls",
            "20",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert validation_calls == []
    assert forwarded["max_items"] == 500
    assert forwarded["max_seconds"] == 60.0
    assert forwarded["max_scrolls"] == 20


def test_cli_forwards_douyin_cookie_file_without_reading_it(monkeypatch):
    forwarded = {}

    def fake_run(*args, **kwargs):
        forwarded.update(kwargs)
        return 0

    monkeypatch.setattr(collect, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect.py",
            DOUYIN_URL,
            "--limit",
            "1",
            "--douyin-cookie-file",
            "/run/secrets/douyin-cookies.json",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert forwarded["douyin_cookie_file"] == "/run/secrets/douyin-cookies.json"


def test_cli_forwards_bilibili_cookie_file_without_reading_it(monkeypatch):
    forwarded = {}

    def fake_run(*args, **kwargs):
        forwarded.update(kwargs)
        return 0

    monkeypatch.setattr(collect, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect.py",
            BILIBILI_URL,
            "--limit",
            "1",
            "--bilibili-cookie-file",
            "/run/secrets/bilibili-cookies.json",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert forwarded["bilibili_cookie_file"] == "/run/secrets/bilibili-cookies.json"


@pytest.mark.parametrize(
    ("url", "flag", "keyword", "path"),
    [
        (WEIBO_URL, "--weibo-cookie-file", "weibo_cookie_file", "/run/secrets/weibo.json"),
        (
            XIAOHONGSHU_URL,
            "--xiaohongshu-cookie-file",
            "xiaohongshu_cookie_file",
            "/run/secrets/xiaohongshu.json",
        ),
    ],
)
def test_cli_forwards_platform_cookie_file_without_reading_it(
    monkeypatch, url, flag, keyword, path
):
    """Secret references must reach run() without the CLI opening their contents."""
    forwarded = {}

    def fake_run(*args, **kwargs):
        forwarded.update(kwargs)
        return 0

    monkeypatch.setattr(collect, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["collect.py", url, "--limit", "1", flag, path])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert forwarded[keyword] == path


def test_invalid_douyin_cookie_file_fails_without_loading_adapters_or_leaking(
    monkeypatch, tmp_path, capsys
):
    secret = "must-not-appear"
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        '{"name":"sessionid","value":"' + secret + '","domain":"example.com"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: pytest.fail("adapter loading must not run"),
    )

    assert collect.run(
        DOUYIN_URL,
        out_dir=str(tmp_path / "task"),
        douyin_cookie_file=str(cookie_file),
    ) == 2

    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert not (tmp_path / "task").exists()


def test_invalid_weibo_cookie_file_fails_without_loading_adapters_or_leaking(
    monkeypatch, tmp_path, capsys
):
    secret = "must-not-appear"
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        '{"name":"SUB","value":"' + secret + '","domain":"example.com"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: pytest.fail("adapter loading must not run"),
    )

    assert collect.run(
        WEIBO_URL,
        out_dir=str(tmp_path / "task"),
        weibo_cookie_file=str(cookie_file),
    ) == 2

    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert not (tmp_path / "task").exists()


def test_invalid_bilibili_cookie_file_fails_without_loading_adapters_or_leaking(
    monkeypatch, tmp_path, capsys
):
    secret = "must-not-appear"
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        '{"name":"SESSDATA","value":"' + secret + '","domain":"example.com"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: pytest.fail("adapter loading must not run"),
    )

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(tmp_path / "task"),
        bilibili_cookie_file=str(cookie_file),
    ) == 2

    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert not (tmp_path / "task").exists()
