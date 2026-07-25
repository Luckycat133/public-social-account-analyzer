#!/usr/bin/env python3
"""Collect the authorized token owner's profile and Douyin video history."""

from __future__ import annotations

import argparse
import csv
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from collectors.douyin_openapi import DouyinOpenAPIClient, DouyinOpenAPIError


_BEIJING = timezone(timedelta(hours=8))
_PROFILE_ENDPOINT = "https://open.douyin.com/oauth/userinfo/"
_TOKEN_ENV = "DOUYIN_OPENAPI_ACCESS_TOKEN"
_ARTIFACT_CHILDREN = (
    "source",
    "normalized-posts.csv",
    "task.json",
    "collection-report.md",
)
_SOURCE_ARTIFACT_CHILDREN = ("profile.json", "posts.jsonl")


class ArtifactPromotionError(RuntimeError):
    """Sanitized final-path acquisition or child-promotion failure."""

    def __init__(self, reason: str) -> None:
        super().__init__("artifact workspace could not be promoted")
        self.reason = reason


def _entry_identity(metadata) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _snapshot_known_node(path: str, children: tuple[str, ...] = ()) -> dict | None:
    """Snapshot only collector-owned names; never adopt concurrent entries."""
    try:
        metadata = os.lstat(path)
    except OSError:
        return None
    node = {
        "identity": _entry_identity(metadata),
        "directory": stat.S_ISDIR(metadata.st_mode),
        "children": {},
    }
    if node["directory"]:
        for child in children:
            child_node = _snapshot_known_node(os.path.join(path, child))
            if child_node is not None:
                node["children"][child] = child_node
    return node


def _known_staging_snapshot(staging: str) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for child in _ARTIFACT_CHILDREN:
        nested = _SOURCE_ARTIFACT_CHILDREN if child == "source" else ()
        node = _snapshot_known_node(os.path.join(staging, child), nested)
        if node is not None:
            snapshot[child] = node
    return snapshot


def _node_matches(path: str, node: dict) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return bool(
        _entry_identity(metadata) == node["identity"]
        and stat.S_ISDIR(metadata.st_mode) is node["directory"]
    )


def _remove_exact_known_node(path: str, node: dict) -> None:
    """Remove an unchanged known node, leaving replacements and unknown children."""
    if not _node_matches(path, node):
        return
    if node["directory"]:
        for child, child_node in node["children"].items():
            if not _node_matches(path, node):
                return
            _remove_exact_known_node(os.path.join(path, child), child_node)
        if not _node_matches(path, node):
            return
        try:
            os.rmdir(path)
        except OSError:
            return
        return
    try:
        os.unlink(path)
    except OSError:
        return


def _remove_exact_empty_directory(
    path: str, identity: tuple[int, int] | None
) -> None:
    if identity is None:
        return
    try:
        metadata = os.lstat(path)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or _entry_identity(metadata) != identity
        ):
            return
        os.rmdir(path)
    except OSError:
        return


def _cleanup_known_staging(
    staging: str,
    staging_identity: tuple[int, int] | None,
    snapshot: dict[str, dict] | None = None,
) -> None:
    known = _known_staging_snapshot(staging) if snapshot is None else snapshot
    for child, node in known.items():
        _remove_exact_known_node(os.path.join(staging, child), node)
    _remove_exact_empty_directory(staging, staging_identity)


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
    """Serialize beside the target, exclusively reserve it, then move children."""

    target = os.path.abspath(workspace)
    parent = os.path.dirname(target)
    basename = os.path.basename(target)
    os.makedirs(parent, exist_ok=True)
    if os.path.lexists(target):
        raise ArtifactPromotionError("TARGET_EXISTS")
    staging = tempfile.mkdtemp(prefix=f".{basename}.staging-", dir=parent)
    try:
        staging_metadata = os.lstat(staging)
        if not stat.S_ISDIR(staging_metadata.st_mode):
            raise OSError("invalid staging directory")
        staging_identity = _entry_identity(staging_metadata)
    except OSError:
        staging_identity = None
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
    except Exception:
        _cleanup_known_staging(staging, staging_identity)
        raise

    staging_snapshot = _known_staging_snapshot(staging)
    if any(child not in staging_snapshot for child in _ARTIFACT_CHILDREN):
        _cleanup_known_staging(staging, staging_identity, staging_snapshot)
        raise ArtifactPromotionError("PROMOTION_FAILED")

    reservation_identity = None
    acquisition_error = None
    try:
        os.mkdir(target)
        try:
            target_stat = os.stat(target, follow_symlinks=False)
            if not stat.S_ISDIR(target_stat.st_mode):
                raise OSError("reserved target is not a directory")
            reservation_identity = _entry_identity(target_stat)
        except OSError:
            try:
                fallback_stat = os.lstat(target)
                fallback_identity = (
                    _entry_identity(fallback_stat)
                    if stat.S_ISDIR(fallback_stat.st_mode)
                    else None
                )
            except OSError:
                fallback_identity = None
            _remove_exact_empty_directory(target, fallback_identity)
            acquisition_error = "RESERVATION_FAILED"
    except FileExistsError:
        acquisition_error = "TARGET_EXISTS"
    except OSError:
        acquisition_error = "RESERVATION_FAILED"

    if acquisition_error is not None:
        _cleanup_known_staging(staging, staging_identity, staging_snapshot)
        raise ArtifactPromotionError(acquisition_error)

    promoted: dict[str, dict] = {}
    try:
        for child in _ARTIFACT_CHILDREN:
            source_child = os.path.join(staging, child)
            target_child = os.path.join(target, child)
            node = staging_snapshot[child]
            if not _node_matches(source_child, node) or os.path.lexists(target_child):
                raise OSError("artifact identity changed before promotion")
            os.rename(source_child, target_child)
            promoted[child] = node
            if not _node_matches(target_child, node):
                raise OSError("artifact identity changed during promotion")
        try:
            current_staging = os.lstat(staging)
        except OSError as exc:
            raise OSError("staging identity unavailable") from exc
        if (
            not stat.S_ISDIR(current_staging.st_mode)
            or _entry_identity(current_staging) != staging_identity
        ):
            raise OSError("staging identity changed")
        os.rmdir(staging)
    except OSError:
        _cleanup_known_staging(staging, staging_identity, staging_snapshot)
        try:
            current_stat = os.lstat(target)
            target_is_owned_reservation = bool(
                stat.S_ISDIR(current_stat.st_mode)
                and reservation_identity == _entry_identity(current_stat)
            )
        except OSError:
            target_is_owned_reservation = False
        if target_is_owned_reservation:
            for child, node in promoted.items():
                if not _node_matches(target, {
                    "identity": reservation_identity,
                    "directory": True,
                }):
                    break
                _remove_exact_known_node(os.path.join(target, child), node)
            _remove_exact_empty_directory(target, reservation_identity)
        raise ArtifactPromotionError("PROMOTION_FAILED")


def _promotion_failure_status(error: ArtifactPromotionError) -> int:
    if error.reason == "TARGET_EXISTS":
        print("[FAILED] 输出目录已被其他任务占用；拒绝覆盖", file=sys.stderr)
        return 2
    print("[FAILED] 输出产物提升失败；未覆盖其他目录", file=sys.stderr)
    return 3


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
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
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
        try:
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
        except ArtifactPromotionError as promotion_error:
            return _promotion_failure_status(promotion_error)
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

    try:
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
    except ArtifactPromotionError as promotion_error:
        return _promotion_failure_status(promotion_error)
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
