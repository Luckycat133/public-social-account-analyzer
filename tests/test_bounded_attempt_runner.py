"""Shared immutable-attempt orchestration contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_task(
    workspace: Path,
    *,
    status: str,
    reason: str | None,
    exhaustive: bool,
    collected_count: int,
) -> None:
    workspace.mkdir(parents=True)
    (workspace / "task.json").write_text(
        json.dumps({
            "task_status": status,
            "stop_reason": reason,
            "collected_count": collected_count,
            "collection_coverage": {"is_exhaustive": exhaustive},
        }),
        encoding="utf-8",
    )
    (workspace / ".complete").write_text("sealed\n", encoding="utf-8")


def test_shared_runner_retries_only_policy_approved_results_and_keeps_best_evidence(
    tmp_path,
):
    from bounded_attempt_runner import run_bounded_attempts

    waits: list[int] = []
    calls: list[Path] = []

    def run_command(command: list[str]) -> int:
        workspace = Path(command[-1])
        calls.append(workspace)
        if len(calls) == 1:
            _write_task(
                workspace,
                status="PARTIAL",
                reason="ACCESS_RESTRICTED",
                exhaustive=False,
                collected_count=12,
            )
        else:
            _write_task(
                workspace,
                status="FAILED",
                reason="LOGIN_REQUIRED",
                exhaustive=False,
                collected_count=0,
            )
        return 3

    result = run_bounded_attempts(
        output_prefix=tmp_path / "account",
        max_attempts=3,
        build_command=lambda workspace: ["collector", str(workspace)],
        is_success=lambda task: task.get("task_status") == "COMPLETED",
        is_retryable=lambda task: task.get("stop_reason") == "ACCESS_RESTRICTED",
        run_command=run_command,
        sleep_fn=waits.append,
    )

    assert [path.name for path in calls] == ["account-attempt-1", "account-attempt-2"]
    assert waits == [30]
    assert result.success is False
    assert result.attempt_count == 2
    assert result.selected_workspace == tmp_path / "account-attempt-1"
    assert result.selected_task["collected_count"] == 12


def test_shared_runner_ignores_unsealed_attempt_metadata(tmp_path):
    from bounded_attempt_runner import run_bounded_attempts

    def run_command(command: list[str]) -> int:
        workspace = Path(command[-1])
        workspace.mkdir()
        (workspace / "task.json").write_text(
            '{"task_status":"COMPLETED"}', encoding="utf-8"
        )
        return 0

    result = run_bounded_attempts(
        output_prefix=tmp_path / "account",
        max_attempts=1,
        build_command=lambda workspace: ["collector", str(workspace)],
        is_success=lambda task: task.get("task_status") == "COMPLETED",
        is_retryable=lambda task: False,
        run_command=run_command,
        sleep_fn=lambda _seconds: None,
    )

    assert result.success is False
    assert result.selected_task == {}


def test_shared_runner_reports_command_start_failures_without_command_details(tmp_path):
    from bounded_attempt_runner import AttemptCommandError, run_bounded_attempts

    def unavailable(_command: list[str]) -> int:
        raise OSError("/private/secret/collector is unavailable")

    with pytest.raises(AttemptCommandError) as exc_info:
        run_bounded_attempts(
            output_prefix=tmp_path / "account",
            max_attempts=1,
            build_command=lambda workspace: ["collector", str(workspace)],
            is_success=lambda _task: False,
            is_retryable=lambda _task: False,
            run_command=unavailable,
            sleep_fn=lambda _seconds: None,
        )

    assert "secret" not in str(exc_info.value)
