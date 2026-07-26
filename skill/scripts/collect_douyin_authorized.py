#!/usr/bin/env python3
"""Collect the authorized token owner's profile and Douyin video history."""

from __future__ import annotations

import argparse
import csv
import functools
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from collectors.douyin_openapi import DouyinOpenAPIClient, DouyinOpenAPIError
from immutable_workspace import (
    ImmutableWorkspace,
    WorkspaceCapabilityError,
    WorkspaceCommitIndeterminate,
    WorkspaceError,
    WorkspaceExistsError,
    WorkspaceIdentityError,
    WorkspaceVerificationError,
    WorkspaceWriteError,
    ensure_container,
    preflight_backend,
    verify_committed_workspace,
)
from task_contract import (
    TaskContractError,
    new_task_id,
    validate_analysis_goal,
)
from csv_contract import serialize_csv_row


_BEIJING = timezone(timedelta(hours=8))
_PROFILE_ENDPOINT = "https://open.douyin.com/oauth/userinfo/"
_TOKEN_ENV = "DOUYIN_OPENAPI_ACCESS_TOKEN"
_INDETERMINATE_EXIT_CODE = 4
_INDETERMINATE_MESSAGE = (
    "[INDETERMINATE] 输出目录可能已有可见提交，但持久化或最终验证未确认；"
    "请保留目录并重新核验"
)
_AUTHORIZED_ARTIFACTS = frozenset({
    "source/profile.json",
    "source/posts.jsonl",
    "normalized-posts.csv",
    "task.json",
    "collection-report.md",
})


def _write_csv(
    posts: list[dict[str, Any]], reservation: ImmutableWorkspace
) -> None:
    fields: list[str] = []
    for post in posts:
        for field in post:
            if field not in fields:
                fields.append(field)
    if not fields:
        fields = [
            "post_id",
            "post_url",
            "title",
            "published_at",
            "collection_status",
        ]
    with reservation.open_text("normalized-posts.csv", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for post in posts:
            writer.writerow(serialize_csv_row(post, fields))


def _serialize_artifacts(
    reservation: ImmutableWorkspace,
    *,
    profile: dict[str, Any],
    posts: list[dict[str, Any]],
    requested_limit: int | None,
    task_status: str,
    stop_reason: str | None,
    coverage: dict[str, Any],
    task_id: str,
    analysis_goal: str | None,
    diagnostic_code: str | None = None,
) -> None:
    with reservation.open_text("source/profile.json") as handle:
        json.dump(profile, handle, ensure_ascii=False, indent=2)
    with reservation.open_text("source/posts.jsonl") as handle:
        for post in posts:
            handle.write(json.dumps(post, ensure_ascii=False) + "\n")
    _write_csv(posts, reservation)

    collected_at = datetime.now(_BEIJING).isoformat()
    task = {
        "task_id": task_id,
        "platform": "douyin",
        "profile_url": profile.get("profile_url") or _PROFILE_ENDPOINT,
        "requested_limit": requested_limit,
        "date_from": None,
        "date_to": None,
        "analysis_goal": analysis_goal,
        "include_comments": False,
        "task_status": task_status,
        "stop_reason": stop_reason,
        "collected_count": len(posts),
        "collected_at": collected_at,
        "incremental": False,
        "existing_count": 0,
        "new_count": len(posts),
        "collection_source": "douyin_openapi_token_owner",
        "collection_coverage": coverage,
    }
    if diagnostic_code:
        task["diagnostic_code"] = diagnostic_code
    with reservation.open_text("task.json") as handle:
        json.dump(task, handle, ensure_ascii=False, indent=2)

    lines = [
        "# 采集质量报告",
        "",
        "- 平台: douyin",
        "- 采集来源: douyin_openapi_token_owner",
        "- 授权范围: 仅 access token 所有者账号",
        f"- 采集时间: {collected_at}",
        f"- 任务状态 task_status: {task_status}",
        f"- 停止原因 stop_reason: {stop_reason or 'null'}",
        f"- 内容条数: {len(posts)}",
        "",
        "## 覆盖与完备性",
        "",
    ]
    for key, value in coverage.items():
        lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False)}")
    if diagnostic_code:
        lines.extend([
            "",
            "## 错误日志",
            "",
            f"- stage=collect_video_pages error_code={stop_reason} "
            f"diagnostic_code={diagnostic_code}",
        ])
    with reservation.open_text("collection-report.md") as handle:
        handle.write("\n".join(lines) + "\n")


def _write_artifacts(
    reservation: ImmutableWorkspace,
    **kwargs,
) -> str:
    _serialize_artifacts(reservation, **kwargs)
    return reservation.commit()


def _repository_root() -> str:
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def _reserve_authorized_output(
    out_dir: str | None,
) -> ImmutableWorkspace:
    preflight_backend()
    if out_dir is not None:
        return ImmutableWorkspace.reserve(
            os.path.abspath(out_dir), allowed_artifacts=_AUTHORIZED_ARTIFACTS
        )
    date = datetime.now(_BEIJING).strftime("%Y%m%d")
    parent = ensure_container(os.path.join(_repository_root(), "workspace"))
    for suffix in range(1, 1_000_001):
        name = (
            f"douyin-authorized-{date}"
            if suffix == 1
            else f"douyin-authorized-{date}-{suffix}"
        )
        try:
            return ImmutableWorkspace.reserve(
                os.path.join(parent, name),
                allowed_artifacts=_AUTHORIZED_ARTIFACTS,
            )
        except WorkspaceExistsError:
            continue
    raise WorkspaceWriteError("no collision-free output directory is available")


def _verify_authorized_workspace(path: str) -> dict:
    return verify_committed_workspace(
        path, allowed_artifacts=_AUTHORIZED_ARTIFACTS
    )


def _run_reserved_collection(
    reservation: ImmutableWorkspace,
    *,
    api: DouyinOpenAPIClient,
    limit: int,
    collect_all: bool,
    page_size: int,
    task_id: str,
    analysis_goal: str | None,
) -> int:
    profile: dict[str, Any] = {}
    posts: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {
        "requested_all": collect_all,
        "is_exhaustive": False,
        "terminal_page_observed": False,
        "observed_page_count": 0,
        "observed_post_count": 0,
        "repeated_cursor_count": 0,
        "zero_new_page_count": 0,
        "stop_condition": "api_error",
    }

    try:
        profile = api.collect_profile()
    except DouyinOpenAPIError as exc:
        _write_artifacts(
            reservation,
            profile=profile,
            posts=posts,
            requested_limit=None if collect_all else limit,
            task_status="FAILED",
            stop_reason="OPENAPI_ERROR",
            coverage=coverage,
            task_id=task_id,
            analysis_goal=analysis_goal,
            diagnostic_code=exc.error_code,
        )
        print("[FAILED] 授权账号资料请求失败", file=sys.stderr)
        return 3

    try:
        posts, coverage = api.collect_video_pages(
            limit=None if collect_all else limit,
            page_size=page_size,
        )
        if collect_all:
            complete = coverage.get("is_exhaustive") is True
        else:
            complete = (
                len(posts) >= limit
                or coverage.get("terminal_page_observed") is True
            )
        task_status = "COMPLETED" if complete else ("PARTIAL" if posts else "FAILED")
        stop_reason = None if complete else "PARSER_FAILED"
        diagnostic_code = None if complete else "OPENAPI_LIST_INCOMPLETE"
    except DouyinOpenAPIError as exc:
        posts = exc.partial_posts
        coverage = exc.coverage or coverage
        task_status = "PARTIAL" if posts else "FAILED"
        stop_reason = "OPENAPI_ERROR"
        diagnostic_code = exc.error_code

    if collect_all and task_status == "COMPLETED" and not (
        coverage.get("terminal_page_observed") is True
        and coverage.get("is_exhaustive") is True
        and coverage.get("stop_condition") == "terminal_page"
    ):
        task_status = "PARTIAL" if posts else "FAILED"
        stop_reason = "PARSER_FAILED"
        diagnostic_code = "OPENAPI_LIST_INCOMPLETE"

    _write_artifacts(
        reservation,
        profile=profile,
        posts=posts,
        requested_limit=None if collect_all else limit,
        task_status=task_status,
        stop_reason=stop_reason,
        coverage=coverage,
        task_id=task_id,
        analysis_goal=analysis_goal,
        diagnostic_code=diagnostic_code,
    )
    print(
        f"[OK] 平台=douyin 授权账号内容条数={len(posts)} "
        f"task_status={task_status} stop_reason={stop_reason or 'null'}"
    )
    return 3 if task_status == "FAILED" else 0


def _guard_authorized_entry(function):
    """Return one sanitized failure for every ordinary external exception."""

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except WorkspaceCommitIndeterminate:
            print(_INDETERMINATE_MESSAGE, file=sys.stderr)
            return _INDETERMINATE_EXIT_CODE
        except (
            WorkspaceCapabilityError,
            WorkspaceExistsError,
            WorkspaceIdentityError,
            WorkspaceVerificationError,
        ):
            print("[FAILED] 输出目录不安全、已占用或身份已改变", file=sys.stderr)
            return 2
        except WorkspaceError:
            print("[FAILED] 授权采集产物无法提交", file=sys.stderr)
            return 3
        except Exception:
            print("[FAILED] 授权采集或产物写入失败", file=sys.stderr)
            return 3

    return guarded


@_guard_authorized_entry
def run(
    *,
    out_dir: str | None = None,
    limit: int = 30,
    collect_all: bool = False,
    page_size: int = 20,
    environ: Mapping[str, str] | None = None,
    client: DouyinOpenAPIClient | None = None,
    analysis_goal: str | None = None,
) -> int:
    """Run an authorized-owner collection without OAuth lifecycle operations."""

    try:
        analysis_goal = validate_analysis_goal(analysis_goal)
    except TaskContractError:
        print("[FAILED] analysis_goal 参数无效", file=sys.stderr)
        return 2

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        print("[FAILED] --limit 必须为正整数", file=sys.stderr)
        return 2
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        print("[FAILED] page_size 必须为正整数", file=sys.stderr)
        return 2

    env = os.environ if environ is None else environ
    access_token = env.get(_TOKEN_ENV)
    if not isinstance(access_token, str) or not access_token.strip():
        print(f"[FAILED] 缺少环境变量 {_TOKEN_ENV}", file=sys.stderr)
        return 2

    task_id = new_task_id("douyin")
    reservation = _reserve_authorized_output(out_dir)
    try:
        api = client or DouyinOpenAPIClient(access_token)
        return _run_reserved_collection(
            reservation,
            api=api,
            limit=limit,
            collect_all=collect_all,
            page_size=page_size,
            task_id=task_id,
            analysis_goal=analysis_goal,
        )
    finally:
        reservation.close()




def main() -> None:
    parser = argparse.ArgumentParser(
        description="采集 Douyin OpenAPI access token 所有者的授权账号"
    )
    range_group = parser.add_mutually_exclusive_group()
    range_group.add_argument("--all", dest="collect_all", action="store_true")
    range_group.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", default=None)
    parser.add_argument("--analysis-goal", default=None)
    args = parser.parse_args()
    raise SystemExit(
        run(
            out_dir=args.out,
            limit=args.limit,
            collect_all=args.collect_all,
            analysis_goal=args.analysis_goal,
        )
    )


if __name__ == "__main__":
    main()
