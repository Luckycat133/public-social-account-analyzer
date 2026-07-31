#!/usr/bin/env python3
"""Run bounded, immutable Douyin complete-collection attempts."""

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
    PUBLIC_ALL_DEFAULT_MAX_SCROLLS,
    PUBLIC_ALL_DEFAULT_MAX_SECONDS,
    validate_public_all_budgets,
)
from immutable_workspace import WorkspaceError, ensure_container


RETRYABLE_REASONS = frozenset({"RATE_LIMITED", "ACCESS_RESTRICTED"})
BACKOFF_SECONDS = (30, 60)


@dataclass(frozen=True)
class RetryResult:
    success: bool
    attempt_count: int
    selected_workspace: Path
    stop_reason: str | None
    diagnostic_code: str | None = None
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
    status = task.get("task_status")
    return (
        count,
        {"COMPLETED": 2, "PARTIAL": 1}.get(status, 0),
        int(coverage.get("is_exhaustive") is True),
        -attempt,
    )


def run_attempts(
    url: str,
    output_prefix: Path,
    *,
    max_items: int = PUBLIC_ALL_DEFAULT_MAX_ITEMS,
    max_seconds: float = PUBLIC_ALL_DEFAULT_MAX_SECONDS,
    max_scrolls: int = PUBLIC_ALL_DEFAULT_MAX_SCROLLS,
    max_attempts: int = 3,
    date_from: str | None = None,
    date_to: str | None = None,
    analysis_goal: str | None = None,
    include_comments: bool = False,
    enrich_details: bool = False,
    cookie_file: Path | None = None,
    run_command: Callable[[list[str]], int] | None = None,
    sleep_fn: Callable[[int], None] = time.sleep,
) -> RetryResult:
    """Retry transient restrictions only and retain the richest safe attempt."""
    max_items, max_seconds, max_scrolls = validate_public_all_budgets(
        max_items, max_seconds, max_scrolls
    )
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be an integer from 1 to 3")
    try:
        ensure_container(str(output_prefix.parent))
    except WorkspaceError as exc:
        raise ValueError("output prefix parent is unsafe or unavailable") from exc
    runner = run_command or (lambda command: subprocess.run(command).returncode)
    script = Path(__file__).with_name("collect.py")
    best_workspace = output_prefix.with_name(f"{output_prefix.name}-attempt-1")
    best_task: dict = {}
    best_score = (-1, -1, -1, -1)

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
            "--max-seconds",
            str(max_seconds),
            "--max-scrolls",
            str(max_scrolls),
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
        if enrich_details:
            command.append("--enrich-details")
        if cookie_file is not None:
            command.extend(["--douyin-cookie-file", str(cookie_file)])
        runner(command)
        task = _read_attempt_task(workspace)
        score = _task_score(task, attempt)
        if score > best_score:
            best_workspace, best_task, best_score = workspace, task, score
        coverage = task.get("collection_coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        reason = task.get("stop_reason")
        success = bool(
            task.get("task_status") == "COMPLETED"
            and coverage.get("is_exhaustive") is True
        )
        print(
            f"attempt={attempt}/{max_attempts} workspace={workspace} "
            f"task_status={task.get('task_status') or 'INVALID'} "
            f"stop_reason={reason or 'null'} "
            f"diagnostic_code={task.get('diagnostic_code') or 'null'} "
            f"platform_response_code={task.get('platform_response_code') if type(task.get('platform_response_code')) is int else 'null'} "
            f"is_exhaustive={str(coverage.get('is_exhaustive') is True).lower()} "
            f"collected_count={task.get('collected_count') or 0}"
        )
        if success:
            return RetryResult(True, attempt, workspace, None, None, "COMPLETED")
        if reason not in RETRYABLE_REASONS or attempt >= max_attempts:
            return RetryResult(
                False,
                attempt,
                best_workspace,
                best_task.get("stop_reason"),
                best_task.get("diagnostic_code"),
                best_task.get("task_status"),
            )
        sleep_fn(BACKOFF_SECONDS[attempt - 1])

    raise AssertionError("bounded retry loop must return")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="抖音公开作品完整采集：独立任务重试，固定30/60秒退避"
    )
    parser.add_argument("url", help="抖音公开账号主页 URL")
    parser.add_argument("--out-prefix", required=True, type=Path)
    parser.add_argument("--max-items", type=int, default=PUBLIC_ALL_DEFAULT_MAX_ITEMS)
    parser.add_argument("--max-seconds", type=float, default=PUBLIC_ALL_DEFAULT_MAX_SECONDS)
    parser.add_argument("--max-scrolls", type=int, default=PUBLIC_ALL_DEFAULT_MAX_SCROLLS)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--analysis-goal", default=None)
    parser.add_argument("--comments", action="store_true")
    parser.add_argument("--enrich-details", action="store_true")
    parser.add_argument(
        "--douyin-cookie-file",
        type=Path,
        default=None,
        help="用户授权的抖音 Cookie 文件；仅在进程内读取，不写入采集工作区",
    )
    args = parser.parse_args(argv)
    try:
        result = run_attempts(
            args.url,
            args.out_prefix,
            max_items=args.max_items,
            max_seconds=args.max_seconds,
            max_scrolls=args.max_scrolls,
            max_attempts=args.max_attempts,
            date_from=args.date_from,
            date_to=args.date_to,
            analysis_goal=args.analysis_goal,
            include_comments=args.comments,
            enrich_details=args.enrich_details,
            cookie_file=args.douyin_cookie_file,
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
            f"stop_reason={result.stop_reason or 'null'} "
            f"diagnostic_code={result.diagnostic_code or 'null'}"
        )
        return 0
    print(
        f"[FAILED] selected_workspace={result.selected_workspace} "
        f"task_status={result.task_status or 'INVALID'} "
        f"stop_reason={result.stop_reason or 'INVALID'} "
        f"diagnostic_code={result.diagnostic_code or 'null'}",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
