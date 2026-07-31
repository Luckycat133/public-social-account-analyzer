#!/usr/bin/env python3
"""Run bounded, immutable Bilibili full-collection attempts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from collectors._constants import (
    PUBLIC_ALL_DEFAULT_MAX_ITEMS,
    validate_public_all_max_items,
)
from immutable_workspace import WorkspaceError, ensure_container


RETRYABLE_REASONS = frozenset({"RATE_LIMITED", "ACCESS_RESTRICTED"})
RETRYABLE_PLATFORM_CODES = frozenset({-352})
BACKOFF_SECONDS = (30, 60)


@dataclass(frozen=True)
class RetryResult:
    success: bool
    attempt_count: int
    selected_workspace: Path
    stop_reason: str | None
    task_status: str | None = None


def _read_attempt_task(workspace: Path) -> dict:
    if not (workspace / ".complete").is_file():
        return {}
    try:
        value = json.loads((workspace / "task.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _task_score(task: dict, attempt: int) -> tuple[int, int, int, int]:
    coverage = task.get("collection_coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    count = task.get("collected_count")
    count = count if type(count) is int and count >= 0 else 0
    return (
        count,
        {"COMPLETED": 2, "PARTIAL": 1}.get(task.get("task_status"), 0),
        int(coverage.get("is_exhaustive") is True),
        -attempt,
    )


def _is_retryable_attempt(task: dict) -> bool:
    """Retry bounded protection outcomes, including Bilibili code -352."""
    return bool(
        task.get("stop_reason") in RETRYABLE_REASONS
        or task.get("platform_response_code") in RETRYABLE_PLATFORM_CODES
    )


def run_attempts(
    url: str,
    output_prefix: Path,
    *,
    max_items: int = PUBLIC_ALL_DEFAULT_MAX_ITEMS,
    max_attempts: int = 3,
    date_from: str | None = None,
    date_to: str | None = None,
    analysis_goal: str | None = None,
    include_comments: bool = False,
    run_command: Callable[[list[str]], int] | None = None,
    sleep_fn: Callable[[int], None] = time.sleep,
) -> RetryResult:
    """Retry only retryable protected attempts, always using a new workspace."""
    validate_public_all_max_items(max_items)
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be an integer from 1 to 3")
    try:
        ensure_container(str(output_prefix.parent))
    except WorkspaceError as exc:
        raise ValueError("output prefix parent is unsafe or unavailable") from exc
    runner = run_command or (lambda command: subprocess.run(command).returncode)
    script = Path(__file__).with_name("collect.py")
    selected = output_prefix.with_name(f"{output_prefix.name}-attempt-1")
    selected_task: dict = {}
    selected_score = (-1, -1, -1, -1)

    for attempt in range(1, max_attempts + 1):
        workspace = output_prefix.with_name(
            f"{output_prefix.name}-attempt-{attempt}"
        )
        if workspace.exists():
            raise ValueError(f"attempt workspace already exists: {workspace}")
        command = [
            sys.executable,
            str(script),
            url,
            "--all",
            "--max-items",
            str(max_items),
            "--out",
            str(workspace),
        ]
        if date_from is not None:
            command.extend(["--date-from", date_from])
        if date_to is not None:
            command.extend(["--date-to", date_to])
        if analysis_goal is not None:
            command.extend(["--analysis-goal", analysis_goal])
        if include_comments:
            command.append("--comments")
        runner(command)
        task = _read_attempt_task(workspace)
        score = _task_score(task, attempt)
        if score > selected_score:
            selected, selected_task, selected_score = workspace, task, score
        coverage = task.get("collection_coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        last_reason = task.get("stop_reason")
        success = bool(
            task.get("task_status") == "COMPLETED"
            and coverage.get("is_exhaustive") is True
        )
        print(
            f"attempt={attempt}/{max_attempts} workspace={workspace} "
            f"task_status={task.get('task_status') or 'INVALID'} "
            f"stop_reason={last_reason or 'null'} "
            f"diagnostic_code={task.get('diagnostic_code') or 'null'} "
            f"platform_response_code={task.get('platform_response_code') if type(task.get('platform_response_code')) is int else 'null'} "
            f"is_exhaustive={str(coverage.get('is_exhaustive') is True).lower()}"
        )
        if success:
            return RetryResult(True, attempt, workspace, None, "COMPLETED")
        if not _is_retryable_attempt(task) or attempt >= max_attempts:
            return RetryResult(
                False,
                attempt,
                selected,
                selected_task.get("stop_reason"),
                selected_task.get("task_status"),
            )
        sleep_fn(BACKOFF_SECONDS[attempt - 1])

    raise AssertionError("bounded retry loop must return")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="B站公开作品安全全量采集：新任务重试，固定30/60秒退避"
    )
    parser.add_argument("url", help="B站数字 UID 空间主页")
    parser.add_argument("--out-prefix", required=True, type=Path)
    parser.add_argument(
        "--max-items", type=int, default=PUBLIC_ALL_DEFAULT_MAX_ITEMS
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--analysis-goal", default=None)
    parser.add_argument("--comments", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_attempts(
            args.url,
            args.out_prefix,
            max_items=args.max_items,
            max_attempts=args.max_attempts,
            date_from=args.date_from,
            date_to=args.date_to,
            analysis_goal=args.analysis_goal,
            include_comments=args.comments,
        )
    except ValueError as exc:
        print(f"[FAILED] {exc}", file=sys.stderr)
        return 2
    if result.success:
        print(f"[OK] selected_workspace={result.selected_workspace}")
        return 0
    if result.task_status == "PARTIAL":
        print(
            f"[PARTIAL] selected_workspace={result.selected_workspace} "
            f"task_status=PARTIAL "
            f"stop_reason={result.stop_reason or 'null'}"
        )
        return 0
    print(
        f"[FAILED] selected_workspace={result.selected_workspace} "
        f"task_status={result.task_status or 'INVALID'} "
        f"stop_reason={result.stop_reason or 'INVALID'}",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
