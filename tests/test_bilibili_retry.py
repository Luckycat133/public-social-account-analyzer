"""Bounded Bilibili complete-collection retry orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import collect_bilibili_complete as retry


def _write_task(
    path: Path,
    *,
    status: str,
    reason: str | None,
    exhaustive: bool,
    collected_count: int = 0,
    platform_response_code: int | None = None,
    diagnostic_code: str | None = None,
):
    path.mkdir(parents=True)
    (path / "task.json").write_text(
        json.dumps({
            "task_status": status,
            "stop_reason": reason,
            "platform_response_code": platform_response_code,
            "diagnostic_code": diagnostic_code,
            "collected_count": collected_count,
            "collection_coverage": {"is_exhaustive": exhaustive},
        }),
        encoding="utf-8",
    )
    (path / ".complete").write_text("sealed\n", encoding="utf-8")


def test_retries_restricted_attempts_with_fixed_backoff_and_new_directories(tmp_path):
    calls: list[Path] = []
    waits: list[int] = []

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        calls.append(output)
        if len(calls) == 1:
            _write_task(
                output,
                status="PARTIAL",
                reason="ACCESS_RESTRICTED",
                exhaustive=False,
            )
        else:
            _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        run_command=run_attempt,
        sleep_fn=waits.append,
    )

    assert calls == [
        tmp_path / "account-attempt-1",
        tmp_path / "account-attempt-2",
    ]
    assert waits == [30]
    assert result.success is True
    assert result.selected_workspace == calls[1]


def test_complete_collection_prepares_one_missing_output_parent(tmp_path):
    """A cleaned generated-output root must not prevent the first attempt."""
    output_prefix = tmp_path / "workspace" / "account"

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        assert output.parent.is_dir()
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        output_prefix,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    assert result.selected_workspace == tmp_path / "workspace" / "account-attempt-1"


def test_does_not_retry_verification_required(tmp_path):
    waits: list[int] = []

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        _write_task(
            output,
            status="FAILED",
            reason="VERIFICATION_REQUIRED",
            exhaustive=False,
        )
        return 3

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        run_command=run_attempt,
        sleep_fn=waits.append,
    )

    assert result.success is False
    assert result.attempt_count == 1
    assert result.task_status == "FAILED"
    assert waits == []


def test_retries_bilibili_minus_352_with_fresh_bounded_attempt(tmp_path):
    calls: list[Path] = []
    waits: list[int] = []

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        calls.append(output)
        if len(calls) == 1:
            _write_task(
                output,
                status="FAILED",
                reason="VERIFICATION_REQUIRED",
                exhaustive=False,
                platform_response_code=-352,
            )
            return 3
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        run_command=run_attempt,
        sleep_fn=waits.append,
    )

    assert calls == [
        tmp_path / "account-attempt-1",
        tmp_path / "account-attempt-2",
    ]
    assert waits == [30]
    assert result.success is True


def test_forwards_explicit_date_window_to_every_complete_attempt(tmp_path):
    commands: list[list[str]] = []

    def run_attempt(command: list[str]) -> int:
        commands.append(command)
        output = Path(command[command.index("--out") + 1])
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        date_from="2026-01-01",
        date_to="2026-06-30",
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    command = commands[0]
    assert command[command.index("--date-from") + 1] == "2026-01-01"
    assert command[command.index("--date-to") + 1] == "2026-06-30"


def test_forwards_requested_comment_collection(tmp_path):
    commands: list[list[str]] = []

    def run_attempt(command: list[str]) -> int:
        commands.append(command)
        output = Path(command[command.index("--out") + 1])
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        include_comments=True,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    assert "--comments" in commands[0]


def test_forwards_authorized_cookie_file_to_every_attempt(tmp_path):
    commands: list[list[str]] = []

    def run_attempt(command: list[str]) -> int:
        commands.append(command)
        output = Path(command[command.index("--out") + 1])
        _write_task(output, status="COMPLETED", reason=None, exhaustive=True)
        return 0

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        bilibili_cookie_file="/run/secrets/bilibili-cookie.txt",
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is True
    assert commands[0][commands[0].index("--bilibili-cookie-file") + 1] == (
        "/run/secrets/bilibili-cookie.txt"
    )


def test_failed_retry_series_selects_attempt_with_most_evidence(tmp_path):
    outcomes = [
        ("PARTIAL", "ACCESS_RESTRICTED", 40),
        ("PARTIAL", "RATE_LIMITED", 3),
        ("FAILED", "ACCESS_RESTRICTED", 0),
    ]

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        index = int(output.name.rsplit("-", 1)[-1])
        status, reason, count = outcomes[index - 1]
        _write_task(
            output,
            status=status,
            reason=reason,
            exhaustive=False,
            collected_count=count,
        )
        return 3

    result = retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    assert result.attempt_count == 3
    assert result.selected_workspace == tmp_path / "account-attempt-1"
    assert result.task_status == "PARTIAL"


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
            "PARTIAL",
        ),
    )

    exit_code = retry.main([
        "https://space.bilibili.com/123",
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
    outcomes = [
        ("PARTIAL", "ACCESS_RESTRICTED", False, 40),
        ("PARTIAL", "RATE_LIMITED", True, 3),
        ("FAILED", "ACCESS_RESTRICTED", False, 0),
    ]

    def run_attempt(command: list[str]) -> int:
        output = Path(command[command.index("--out") + 1])
        status, reason, exhaustive, count = outcomes[
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
        "https://space.bilibili.com/123",
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
            reason="VERIFICATION_REQUIRED",
            exhaustive=False,
            platform_response_code=-352,
            diagnostic_code="BILIBILI_MEDIALIST_DISCOVERY",
        )
        return 3

    retry.run_attempts(
        "https://space.bilibili.com/123",
        tmp_path / "account",
        max_attempts=1,
        run_command=run_attempt,
        sleep_fn=lambda _seconds: None,
    )

    output = capsys.readouterr().out
    assert "diagnostic_code=BILIBILI_MEDIALIST_DISCOVERY" in output
    assert "platform_response_code=-352" in output
