"""Focused CLI hygiene regressions for the public collection entry point."""

from __future__ import annotations

import sys

import pytest

import collect


DOUYIN_URL = "https://www.douyin.com/user/example"


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

