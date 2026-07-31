"""Bounded Douyin complete-collection retry orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import collect_douyin_complete as retry


def _write_task(
    path: Path,
    *,
    status: str,
    reason: str | None,
    exhaustive: bool,
    collected_count: int = 0,
    diagnostic_code: str | None = None,
    platform_response_code: int | None = None,
):
    path.mkdir(parents=True)
    (path / "task.json").write_text(
        json.dumps({
            "task_status": status,
            "stop_reason": reason,
            "diagnostic_code": diagnostic_code,
            "platform_response_code": platform_response_code,
            "collected_count": collected_count,
            "collection_coverage": {"is_exhaustive": exhaustive},
        }),
        encoding="utf-8",
    )
    (path / ".complete").write_text("sealed\n", encoding="utf-8")


def test_retries_only_transient_restrictions_with_new_workspaces_and_backoff(
    tmp_path,
):
    calls: list[list[str]] = []
    waits: list[int] = []

    def run_attempt(command: list[str]) -> int:
        calls.append(command)
        output = Path(command[command.index("--out") + 1])
        if len(calls) == 1:
            _write_task(
                output,
                status="FAILED",
                reason="ACCESS_RESTRICTED",
                exhaustive=False,
            )
        else:
            _write_task(
                output,
                status="COMPLETED",
                reason=None,
                exhaustive=True,
                collected_count=42,
            )
        return 0

    result = retry.run_attempts(
        "https://www.douyin.com/user/example",
        tmp_path / "account",
        max_items=500,
        max_seconds=120,
        max_scrolls=50,
        date_from="2026-01-01",
        date_to="2026-06-30",
        analysis_goal="分析完整栏目",
        run_command=run_attempt,
        sleep_fn=waits.append,
    )

    assert waits == [30]
    assert result.success is True
    assert result.attempt_count == 2
    assert result.selected_workspace == tmp_path / "account-attempt-2"
    for command in calls:
        assert "--all" in command
        assert command[command.index("--max-items") + 1] == "500"
        assert command[command.index("--date-from") + 1] == "2026-01-01"
        assert command[command.index("--date-to") + 1] == "2026-06-30"


def test_complete_collection_prepares_one_missing_output_parent(tmp_path):
    """A cleaned generated-output root must not prevent the first attempt."""
    output_prefix = tmp_path / "workspace" / "account"

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        assert output.parent.is_dir()
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://www.douyin.com/user/example",
        output_prefix,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    assert result.selected_workspace == tmp_path / "workspace" / "account-attempt-1"


def test_forwards_requested_comments_and_detail_enrichment(tmp_path):
    commands: list[list[str]] = []

    def run_attempt(command: list[str]) -> int:
        commands.append(command)
        output = Path(command[command.index("--out") + 1])
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://www.douyin.com/user/example",
        tmp_path / "account",
        include_comments=True,
        enrich_details=True,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    assert "--comments" in commands[0]
    assert "--enrich-details" in commands[0]


def test_forwards_user_authorized_cookie_file_to_every_attempt(tmp_path):
    commands: list[list[str]] = []
    cookie_file = tmp_path / "douyin-cookies.json"
    cookie_file.write_text('[{"name":"sessionid","value":"secret"}]', encoding="utf-8")

    def run_attempt(command: list[str]) -> int:
        commands.append(command)
        output = Path(command[command.index("--out") + 1])
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://www.douyin.com/user/example",
        tmp_path / "account",
        cookie_file=cookie_file,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    assert commands[0][commands[0].index("--douyin-cookie-file") + 1] == str(cookie_file)
    assert "secret" not in " ".join(commands[0])


def test_login_and_browser_unavailable_are_not_retried(tmp_path):
    for reason, diagnostic_code in (
        ("LOGIN_REQUIRED", None),
        ("PARSER_FAILED", "BROWSER_UNAVAILABLE"),
    ):
        waits: list[int] = []

        def run_attempt(command: list[str]) -> int:
            output = Path(command[command.index("--out") + 1])
            _write_task(
                output,
                status="FAILED",
                reason=reason,
                exhaustive=False,
                diagnostic_code=diagnostic_code,
            )
            return 3

        result = retry.run_attempts(
            "https://www.douyin.com/user/example",
            tmp_path / f"account-{reason}-{diagnostic_code or 'none'}",
            run_command=run_attempt,
            sleep_fn=waits.append,
        )

        assert result.success is False
        assert result.attempt_count == 1
        assert result.task_status == "FAILED"
        assert waits == []


def test_failed_retry_series_selects_the_attempt_with_most_public_evidence(tmp_path):
    attempts = [
        ("PARTIAL", "ACCESS_RESTRICTED", 20),
        ("PARTIAL", "RATE_LIMITED", 5),
        ("FAILED", "ACCESS_RESTRICTED", 0),
    ]

    def run_attempt(command: list[str]) -> int:
        index = int(Path(command[command.index("--out") + 1]).name.rsplit("-", 1)[-1])
        status, reason, count = attempts[index - 1]
        output = Path(command[command.index("--out") + 1])
        _write_task(
            output,
            status=status,
            reason=reason,
            exhaustive=False,
            collected_count=count,
        )
        return 3

    result = retry.run_attempts(
        "https://www.douyin.com/user/example",
        tmp_path / "account",
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is False
    assert result.attempt_count == 3
    assert result.selected_workspace == tmp_path / "account-attempt-1"
    assert result.task_status == "PARTIAL"
    assert result.stop_reason == "ACCESS_RESTRICTED"


def test_main_does_not_label_a_failed_selected_attempt_as_partial(
    monkeypatch, capsys, tmp_path
):
    selected = tmp_path / "account-attempt-1"
    monkeypatch.setattr(
        retry,
        "run_attempts",
        lambda *_args, **_kwargs: retry.RetryResult(
            False,
            1,
            selected,
            "LOGIN_REQUIRED",
            None,
            "FAILED",
        ),
    )

    exit_code = retry.main([
        "https://www.douyin.com/user/example",
        "--out-prefix",
        str(tmp_path / "account"),
    ])

    captured = capsys.readouterr()
    assert exit_code == 3
    assert "[FAILED]" in captured.err
    assert "[PARTIAL]" not in captured.err
    assert "task_status=FAILED" in captured.err


def test_main_treats_a_selected_partial_collection_as_usable(
    monkeypatch, capsys, tmp_path
):
    selected = tmp_path / "account-attempt-1"
    monkeypatch.setattr(
        retry,
        "run_attempts",
        lambda *_args, **_kwargs: retry.RetryResult(
            False,
            3,
            selected,
            "ACCESS_RESTRICTED",
            "BROWSER_VISIBLE_RESTRICTION",
            "PARTIAL",
        ),
    )

    exit_code = retry.main([
        "https://www.douyin.com/user/example",
        "--out-prefix",
        str(tmp_path / "account"),
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[PARTIAL]" in captured.out
    assert "[FAILED]" not in captured.err


def test_failed_attempt_selection_prioritizes_evidence_count_over_bad_exhaustive_flag(
    tmp_path,
):
    attempts = [
        ("PARTIAL", "ACCESS_RESTRICTED", False, 20),
        ("PARTIAL", "RATE_LIMITED", True, 5),
        ("FAILED", "ACCESS_RESTRICTED", False, 0),
    ]

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        status, reason, exhaustive, count = attempts[
            int(output.name.rsplit("-", 1)[-1]) - 1
        ]
        _write_task(
            output,
            status=status,
            reason=reason,
            exhaustive=exhaustive,
            collected_count=count,
        )
        return 3

    result = retry.run_attempts(
        "https://www.douyin.com/user/example",
        tmp_path / "account",
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.selected_workspace == tmp_path / "account-attempt-1"


def test_attempt_log_includes_safe_diagnostics(capsys, tmp_path):
    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        _write_task(
            output,
            status="FAILED",
            reason="LOGIN_REQUIRED",
            exhaustive=False,
            diagnostic_code="BROWSER_VISIBLE_RESTRICTION",
            platform_response_code=403,
        )
        return 3

    retry.run_attempts(
        "https://www.douyin.com/user/example",
        tmp_path / "account",
        max_attempts=1,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    output = capsys.readouterr().out
    assert "diagnostic_code=BROWSER_VISIBLE_RESTRICTION" in output
    assert "platform_response_code=403" in output
