#!/usr/bin/env python3
"""Collect the authorized token owner's profile and Douyin video history."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from collectors.douyin_openapi import DouyinOpenAPIClient, DouyinOpenAPIError


_BEIJING = timezone(timedelta(hours=8))
_PROFILE_ENDPOINT = "https://open.douyin.com/oauth/userinfo/"
_TOKEN_ENV = "DOUYIN_OPENAPI_ACCESS_TOKEN"


def _write_csv(posts: list[dict[str, Any]], path: str) -> None:
    fields: list[str] = []
    for post in posts:
        for field in post:
            if field not in fields:
                fields.append(field)
    if not fields:
        fields = ["post_id", "post_url", "title", "published_at", "collection_status"]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(posts)


def _serialize_artifacts(
    workspace: str,
    *,
    profile: dict[str, Any],
    posts: list[dict[str, Any]],
    requested_limit: int | None,
    task_status: str,
    stop_reason: str | None,
    coverage: dict[str, Any],
    diagnostic_code: str | None = None,
) -> None:
    source = os.path.join(workspace, "source")
    os.makedirs(source, exist_ok=True)
    with open(os.path.join(source, "profile.json"), "w", encoding="utf-8") as handle:
        json.dump(profile, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(source, "posts.jsonl"), "w", encoding="utf-8") as handle:
        for post in posts:
            handle.write(json.dumps(post, ensure_ascii=False) + "\n")
    _write_csv(posts, os.path.join(workspace, "normalized-posts.csv"))

    collected_at = datetime.now(_BEIJING).isoformat()
    task = {
        "platform": "douyin",
        "profile_url": profile.get("profile_url") or _PROFILE_ENDPOINT,
        "requested_limit": requested_limit,
        "date_from": None,
        "date_to": None,
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
    with open(os.path.join(workspace, "task.json"), "w", encoding="utf-8") as handle:
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
    with open(
        os.path.join(workspace, "collection-report.md"), "w", encoding="utf-8"
    ) as handle:
        handle.write("\n".join(lines) + "\n")


def _write_artifacts(
    workspace: str,
    *,
    profile: dict[str, Any],
    posts: list[dict[str, Any]],
    requested_limit: int | None,
    task_status: str,
    stop_reason: str | None,
    coverage: dict[str, Any],
    diagnostic_code: str | None = None,
) -> None:
    """Serialize in a sibling directory, then atomically promote on success."""

    target = os.path.abspath(workspace)
    parent = os.path.dirname(target)
    basename = os.path.basename(target)
    os.makedirs(parent, exist_ok=True)
    if os.path.lexists(target):
        raise FileExistsError("output workspace already exists")
    staging = tempfile.mkdtemp(prefix=f".{basename}.staging-", dir=parent)
    promoted = False
    try:
        _serialize_artifacts(
            staging,
            profile=profile,
            posts=posts,
            requested_limit=requested_limit,
            task_status=task_status,
            stop_reason=stop_reason,
            coverage=coverage,
            diagnostic_code=diagnostic_code,
        )
        if os.path.lexists(target):
            raise FileExistsError("output workspace already exists")
        os.rename(staging, target)
        promoted = True
    finally:
        if not promoted and os.path.isdir(staging):
            shutil.rmtree(staging)


def run(
    *,
    out_dir: str | None = None,
    limit: int = 30,
    collect_all: bool = False,
    page_size: int = 20,
    environ: Mapping[str, str] | None = None,
    client: DouyinOpenAPIClient | None = None,
) -> int:
    """Run an authorized-owner collection without OAuth lifecycle operations."""

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

    if out_dir is None:
        date = datetime.now(_BEIJING).strftime("%Y%m%d")
        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "workspace",
            f"douyin-authorized-{date}",
        )
    if os.path.lexists(out_dir):
        print("[FAILED] 输出目录已存在；拒绝覆盖", file=sys.stderr)
        return 2

    api = client or DouyinOpenAPIClient(access_token)
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
            out_dir,
            profile=profile,
            posts=posts,
            requested_limit=None if collect_all else limit,
            task_status="FAILED",
            stop_reason="OPENAPI_ERROR",
            coverage=coverage,
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
        out_dir,
        profile=profile,
        posts=posts,
        requested_limit=None if collect_all else limit,
        task_status=task_status,
        stop_reason=stop_reason,
        coverage=coverage,
        diagnostic_code=diagnostic_code,
    )
    print(
        f"[OK] 平台=douyin 授权账号内容条数={len(posts)} "
        f"task_status={task_status} stop_reason={stop_reason or 'null'}"
    )
    return 3 if task_status == "FAILED" else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="采集 Douyin OpenAPI access token 所有者的授权账号"
    )
    range_group = parser.add_mutually_exclusive_group()
    range_group.add_argument("--all", dest="collect_all", action="store_true")
    range_group.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    raise SystemExit(
        run(out_dir=args.out, limit=args.limit, collect_all=args.collect_all)
    )


if __name__ == "__main__":
    main()
