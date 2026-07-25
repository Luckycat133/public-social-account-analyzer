#!/usr/bin/env python3
"""采集入口:根据平台路由到对应采集器,采集账号资料与内容列表/详情。
对应 PRD FR-001~FR-009。

    用法:
    python scripts/collect.py <账号主页URL> [--limit N] [--out DIR] [--comments]
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD] [--browser-fallback]

    说明:
    - 通过 `from collectors.base import` / `from collectors.bilibili import` 导入
      (需 scripts/ 在 sys.path,且 scripts/collectors/__init__.py 存在,本文件已自动处理)。
    - 抖音/微博适配器若未实现,自动跳过(不会报错)。
    - 输出到 workspace/<platform>-<account>-<date>/ 下:
      source/profile.json、source/posts.jsonl、normalized-posts.csv、collection-report.md、task.json。
    - task.json 记录 task_status 与 stop_reason(见 references/exceptions.md §1)。
"""
from __future__ import annotations

import argparse
import contextvars
import csv
import functools
import io
import json
import os
import re
import stat
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

# 让脚本可直接运行:把 scripts/collectors/ 与 scripts/ 都加入 sys.path,
# 以支持采集器内的平级 `from base import` / `from bilibili import`。
_HERE = os.path.dirname(os.path.abspath(__file__))
_COLLECTORS = os.path.join(_HERE, "collectors")
for _p in (_COLLECTORS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from collectors.base import BaseCollector  # noqa: E402
from collectors._constants import (  # noqa: E402
    PUBLIC_ALL_DEFAULT_MAX_ITEMS,
    PUBLIC_ALL_DEFAULT_MAX_SCROLLS,
    PUBLIC_ALL_DEFAULT_MAX_SECONDS,
    PUBLIC_ALL_HARD_MAX_ITEMS,
    PUBLIC_ALL_HARD_MAX_SCROLLS,
    PUBLIC_ALL_HARD_MAX_SECONDS,
    PUBLIC_LIMIT_DEFAULT,
    PUBLIC_LIMIT_MAX,
    validate_public_all_budgets,
    validate_public_limit,
)
from collectors.url_policy import (  # noqa: E402
    canonical_item_url,
    canonical_profile_url,
    sanitize_routing_url,
)
from immutable_workspace import (  # noqa: E402
    FORMAT as IMMUTABLE_WORKSPACE_FORMAT,
    ImmutableWorkspace,
    WorkspaceCapabilityError,
    WorkspaceError,
    WorkspaceExistsError,
    WorkspaceIdentityError,
    WorkspaceVerificationError,
    WorkspaceWriteError,
    ensure_container,
    preflight_backend,
    read_resume_artifact,
    verify_committed_workspace,
)

# 北京时间为中国平台默认时区(见 references/data-schema.md §1)
_BEIJING = timezone(timedelta(hours=8))

# 任务级 stop_reason 取值,严格对齐 references/exceptions.md §9.2 / references/data-schema.md §9.2
SR_UNSUPPORTED = "UNSUPPORTED_PLATFORM"
SR_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
SR_LOGIN = "LOGIN_REQUIRED"
SR_VERIFICATION = "VERIFICATION_REQUIRED"
SR_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
SR_ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
SR_PARSER_FAILED = "PARSER_FAILED"
SR_NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"
SR_INTERNAL = "INTERNAL_ERROR"

_DETAIL_FIELDS = ("title", "published_at", "duration_seconds", "hashtags")

# 适配器异常类 → stop_reason 映射(按异常属性 / 类名兜底)
# 已知 stop_reason 集合,用于从异常消息前缀 [REASON] 兜底识别
_KNOWN_STOP_REASONS = frozenset({
    SR_UNSUPPORTED, SR_ADAPTER_UNAVAILABLE, SR_LOGIN, SR_VERIFICATION,
    SR_ACCOUNT_UNAVAILABLE, SR_ACCESS_RESTRICTED, SR_PARSER_FAILED,
    SR_NO_PUBLIC_CONTENT, SR_INTERNAL,
})

_ERROR_STAGE_MESSAGES = {
    "check_access": "访问检查不可用",
    "collect_post_list": "内容列表采集不可用",
    "collect_profile": "账号资料采集不可用",
    "collection_coverage": "全量采集覆盖证据不完整",
    "collect_post_detail": "作品详情补充不可用",
    "collect_comments": "公开评论采样不可用",
    "persist_comments": "评论产物写入失败",
}
_REPORT_ERROR_CODES = _KNOWN_STOP_REASONS | {
    "POST_UNAVAILABLE",
    "COMMENTS_UNAVAILABLE",
}
_MAX_COMMENT_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_RESUME_ARTIFACT_BYTES = 64 * 1024 * 1024
_ACTIVE_RESERVATIONS: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "active_workspace_reservations", default=None
)


def _stop_reason_from_exc(e: Exception) -> str:
    """从适配器异常中提取 stop_reason;无法识别时 INTERNAL_ERROR。

    优先级:
    1. 异常的 .stop_reason 属性(BilibiliError / DouyinError 使用)
    2. 异常消息中的 [REASON] 前缀(WeiboCollector 的 RuntimeError 使用)
    3. 兜底 INTERNAL_ERROR
    """
    reason = getattr(e, "stop_reason", None)
    if isinstance(reason, str) and reason in _KNOWN_STOP_REASONS:
        return reason
    msg = str(e)
    m = re.search(r"\[([A-Z_]+)\]", msg)
    if m and m.group(1) in _KNOWN_STOP_REASONS:
        return m.group(1)
    return SR_INTERNAL


def _load_adapters(
    douyin_browser_fallback: bool = True,
    bilibili_browser_fallback: bool | None = None,
) -> list[BaseCollector]:
    """加载已实现(非桩)的采集器,返回实例列表。"""
    adapters: list[BaseCollector] = []
    # B站(P0):平级导入
    try:
        from collectors.bilibili import BilibiliCollector

        adapters.append(
            BilibiliCollector(browser_fallback=bilibili_browser_fallback)
        )
    except Exception:  # pragma: no cover
        print("[warn] 加载 bilibili 适配器失败", file=sys.stderr)
    # 抖音(P0)/微博(P1):若实现则加载
    # 用 importlib.import_module 而非 __import__:后者返回顶层包,取不到子模块的类
    import importlib
    for mod, cls in (("collectors.douyin", "DouyinCollector"), ("collectors.weibo", "WeiboCollector")):
        try:
            m = importlib.import_module(mod)
            c = getattr(m, cls, None)
            if c:
                if mod == "collectors.douyin":
                    adapters.append(c(browser_fallback=douyin_browser_fallback))
                else:
                    adapters.append(c())
        except Exception:
            pass
    return adapters


def _pick(adapters: list[BaseCollector], url: str) -> BaseCollector | None:
    for a in adapters:
        try:
            if a.supports(url):
                return a
        except Exception:
            continue
    return None


def _vis_count(profile: dict) -> int:
    vis = profile.get("field_visibility") or {}
    # field_visibility 取值规范为 visible/hidden/partial(见 data-schema.md §8)，做对 "public" 的向下兼容兜底
    return sum(1 for v in vis.values() if v in ("visible", "partial", "public"))


def _write_csv(
    posts: list[dict],
    path: str,
    *,
    reservation: _WorkspaceReservation | None = None,
) -> None:
    if posts:
        keys: list[str] = []
        for p in posts:
            for k in p:
                if k not in keys:
                    keys.append(k)
    else:
        keys = ["post_id", "post_url", "title", "published_at", "collection_status"]
    handle = (
        reservation.open_text(os.path.relpath(path, reservation.path), newline="")
        if reservation is not None
        else open(path, "w", newline="", encoding="utf-8")
    )
    with handle as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for p in posts:
            row = {k: ("" if p.get(k) is None else p.get(k)) for k in keys}
            w.writerow(row)


def _parse_date(s: str | None) -> str | None:
    """把 --date-from/--date-to 规范化为 +08:00 ISO 8601(中国平台默认时区)。

    接受 YYYY-MM-DD(自动补 00:00:00 起始 / 23:59:59 结束)或完整 ISO。
    无法解析时返回 None,由调用方决定是否拒绝。
    """
    if not s:
        return None
    s = s.strip()
    # Python 3.9 的 fromisoformat 不支持 'Z' 后缀,规范化为 +00:00(见 CASE-004)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # 已带时区的 ISO 直接接受
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_BEIJING)
        return dt.isoformat()
    except ValueError:
        pass
    # YYYY-MM-DD → 起/止
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, tzinfo=_BEIJING).isoformat()
    return None


def _default_date_to(date_to_raw: str | None) -> str | None:
    """--date-to 为 YYYY-MM-DD 时补到当日 23:59:59 +08:00。"""
    if not date_to_raw:
        return None
    s = date_to_raw.strip()
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s):
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, 23, 59, 59, tzinfo=_BEIJING).isoformat()
    return _parse_date(s)


def _filter_by_date(
    posts: list[dict],
    date_from: str | None,
    date_to: str | None,
) -> list[dict]:
    """按 published_at(ISO 8601)做交集过滤;无法解析时间的条目保留(不臆造排除)。"""
    if not date_from and not date_to:
        return posts

    def parse(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            return None

    lo = parse(date_from)
    hi = parse(date_to)
    out: list[dict] = []
    for p in posts:
        pa = parse(p.get("published_at"))
        if pa is None:
            out.append(p)
            continue
        if lo is not None and pa < lo:
            continue
        if hi is not None and pa > hi:
            continue
        out.append(p)
    return out


def _missing_detail_value(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _douyin_item_url(post: dict) -> str | None:
    """Return a genuine ID-matching Douyin item URL, never a profile URL."""
    post_id = str(post.get("post_id") or "")
    post_url = post.get("post_url")
    if re.fullmatch(r"\d+", post_id) is None or not isinstance(post_url, str):
        return None
    return canonical_item_url("douyin", post_url, post_id)


def _set_detail_status(post: dict, status: str) -> None:
    metrics = post.get("platform_metrics")
    post["platform_metrics"] = dict(metrics) if isinstance(metrics, dict) else {}
    post["platform_metrics"]["detail_status"] = status


def _valid_comment_parent(platform: str, post: dict) -> tuple[str, str] | None:
    post_id = str(post.get("post_id") or "").strip()
    post_url = post.get("post_url")
    if not post_id or not isinstance(post_url, str):
        return None
    canonical = canonical_item_url(platform, post_url, post_id)
    return (post_id, canonical) if canonical else None


def _canonicalize_post_urls(platform: str, posts: list[dict]) -> None:
    """Canonicalize valid item evidence and null every untrusted URL value."""
    for post in posts:
        post_id = str(post.get("post_id") or "").strip()
        post["post_url"] = canonical_item_url(
            platform, post.get("post_url"), post_id
        )
        post["source_url"] = canonical_item_url(
            platform, post.get("source_url"), post_id
        )


def _normalize_comment_record(
    value,
    parent_post_id: str,
    parent_post_url: str,
    occurred_at: str,
) -> dict | None:
    if not isinstance(value, dict):
        return None
    for key in ("parent_post_id", "post_id"):
        supplied = value.get(key)
        if supplied is not None and str(supplied).strip() != parent_post_id:
            return None
    for key in ("parent_post_url", "post_url"):
        supplied = value.get(key)
        if supplied is not None and supplied != parent_post_url:
            return None
    comment_id = value.get("comment_id")
    if (
        isinstance(comment_id, bool)
        or not isinstance(comment_id, (str, int))
    ):
        return None
    comment_id = str(comment_id).strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", comment_id) is None:
        return None

    def optional_text(key: str) -> str | None:
        item = value.get(key)
        if item is None:
            return None
        if not isinstance(item, str):
            raise ValueError(key)
        return item.strip() or None

    try:
        author = optional_text("author")
        text = optional_text("text")
        published_at = optional_text("published_at")
        collected_at = optional_text("collected_at") or occurred_at
    except ValueError:
        return None
    for timestamp in (published_at, collected_at):
        if timestamp is None:
            continue
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
    likes = value.get("likes")
    if likes is not None and (
        isinstance(likes, bool) or not isinstance(likes, int) or likes < 0
    ):
        return None
    return {
        "comment_id": comment_id,
        "parent_post_id": parent_post_id,
        "parent_post_url": parent_post_url,
        "author": author,
        "text": text,
        "likes": likes,
        "published_at": published_at,
        "collected_at": collected_at,
    }


WorkspaceContractError = WorkspaceError
ArtifactWriteError = WorkspaceWriteError
_WorkspaceReservation = ImmutableWorkspace

_PUBLIC_ARTIFACTS = frozenset({
    "source/profile.json",
    "source/posts.jsonl",
    "source/comments.jsonl",
    "normalized-posts.csv",
    "task.json",
    "collection-report.md",
})


def _repository_root() -> str:
    return os.path.dirname(os.path.dirname(_HERE))


def _track_reservation(
    reservation: _WorkspaceReservation,
) -> _WorkspaceReservation:
    active = _ACTIVE_RESERVATIONS.get()
    if active is not None:
        active.append(reservation)
    return reservation


def _preflight_explicit_workspace(path: str, *, resume: bool) -> None:
    """Validate an explicit pathname without creating or changing it."""
    target = os.path.abspath(path)
    if resume:
        if not os.path.lexists(target):
            raise WorkspaceVerificationError("resume workspace does not exist")
        return
    if os.path.lexists(target):
        raise WorkspaceExistsError("new output directory already exists")
    parent = os.path.dirname(target)
    try:
        metadata = os.lstat(parent)
    except OSError as exc:
        raise WorkspaceWriteError("workspace parent does not exist") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise WorkspaceWriteError("workspace parent is unsafe")


def _prepare_explicit_workspace(
    path: str,
    *,
    resume: bool = False,
    expected_identities=None,
) -> _WorkspaceReservation:
    """Atomically acquire a new final-name workspace.

    Resume sources use :func:`read_resume_artifact` and are never returned as a
    writable reservation.  The legacy parameters remain only to give callers a
    stable, fail-closed error during the CLI transition.
    """
    if resume or expected_identities is not None:
        raise WorkspaceVerificationError("resume workspace is read-only")
    preflight_backend()
    return _track_reservation(
        ImmutableWorkspace.reserve(
            os.path.abspath(path), allowed_artifacts=_PUBLIC_ARTIFACTS
        )
    )


def _reserve_unique_workspace(parent: str, base_name: str) -> _WorkspaceReservation:
    for suffix in range(1, 1_000_001):
        name = base_name if suffix == 1 else f"{base_name}-{suffix}"
        try:
            return _track_reservation(
                ImmutableWorkspace.reserve(
                    os.path.join(parent, name),
                    allowed_artifacts=_PUBLIC_ARTIFACTS,
                )
            )
        except WorkspaceExistsError:
            continue
    raise WorkspaceWriteError("no collision-free output directory is available")


def _reserve_default_workspace(base_name: str) -> _WorkspaceReservation:
    repository_root = _repository_root()
    workspace = ensure_container(os.path.join(repository_root, "workspace"))
    return _reserve_unique_workspace(workspace, base_name)


def _reserve_resume_workspace(
    source_workspace: str,
    *,
    resume_out: str | None,
    date: str,
) -> _WorkspaceReservation:
    if resume_out is not None:
        return _prepare_explicit_workspace(resume_out)
    source = os.path.abspath(source_workspace)
    return _reserve_unique_workspace(
        os.path.dirname(source), f"{os.path.basename(source)}-resume-{date}"
    )


def _verify_public_workspace(path: str) -> dict:
    return verify_committed_workspace(
        path, allowed_artifacts=_PUBLIC_ARTIFACTS
    )


def _write_comments_atomic(
    path: str,
    records: list[dict],
    *,
    reservation: _WorkspaceReservation | None = None,
) -> bool:
    if reservation is None:
        return False
    try:
        relative_path = os.path.relpath(path, reservation.path)
        with reservation.open_text(relative_path) as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except ArtifactWriteError:
        return False
    except WorkspaceContractError:
        raise
    except Exception:
        return False


def _enrich_douyin_details(
    adapter,
    posts: list[dict],
    error_log: list[dict],
    occurred_at: str,
) -> int:
    """Fill only missing public fields; isolate and sanitize item failures."""
    unavailable_count = 0
    for post in posts:
        missing = [field for field in _DETAIL_FIELDS if _missing_detail_value(post.get(field))]
        if not missing:
            _set_detail_status(post, "NOT_NEEDED")
            continue
        item_url = _douyin_item_url(post)
        if item_url is None:
            unavailable_count += 1
            _set_detail_status(post, "UNAVAILABLE")
            if post.get("collection_status") == "SUCCESS":
                post["collection_status"] = "PARTIAL"
            error_log.append({
                "url": None,
                "stage": "collect_post_detail",
                "error_code": "POST_UNAVAILABLE",
                "message": "作品详情补充跳过：缺少可验证的单条作品 URL",
                "occurred_at": occurred_at,
                "retryable": False,
            })
            continue
        try:
            detail = adapter.collect_post_detail(item_url)
            if not isinstance(detail, dict):
                raise ValueError("invalid detail result")
            if str(detail.get("post_id") or "") != str(post.get("post_id") or ""):
                raise ValueError("mismatched detail post id")
        except Exception:
            unavailable_count += 1
            _set_detail_status(post, "UNAVAILABLE")
            if post.get("collection_status") == "SUCCESS":
                post["collection_status"] = "PARTIAL"
            error_log.append({
                "url": item_url,
                "stage": "collect_post_detail",
                "error_code": "POST_UNAVAILABLE",
                "message": "作品详情补充不可用",
                "occurred_at": occurred_at,
                "retryable": False,
            })
            continue
        for field in missing:
            value = detail.get(field)
            if not _missing_detail_value(value):
                post[field] = value
        _set_detail_status(post, "SUCCESS")
    return unavailable_count


def _collect_and_persist_comments(
    adapter,
    posts: list[dict],
    path: str,
    error_log: list[dict],
    occurred_at: str,
    reservation: _WorkspaceReservation | None = None,
) -> dict:
    per_post_limit = 20
    records: list[dict] = []
    outcome = {
        "attempted_posts": 0,
        "comments_collected": 0,
        "empty_results": 0,
        "failures": 0,
        "per_post_limit": per_post_limit,
    }
    seen: set[tuple[str, str]] = set()
    failed_parents: set[str] = set()
    for post in posts:
        parent = _valid_comment_parent(str(adapter.platform), post)
        if parent is None:
            outcome["failures"] += 1
            error_log.append({
                "url": None,
                "stage": "collect_comments",
                "error_code": "COMMENTS_UNAVAILABLE",
                "message": "公开评论采样不可用",
                "occurred_at": occurred_at,
                "retryable": False,
            })
            continue
        post_id, post_url = parent
        outcome["attempted_posts"] += 1
        try:
            returned = adapter.collect_comments(post_url, limit=per_post_limit)
            if not isinstance(returned, list):
                raise ValueError("invalid comments result")
        except Exception:
            outcome["failures"] += 1
            failed_parents.add(post_id)
            error_log.append({
                "url": post_url or None,
                "stage": "collect_comments",
                "error_code": "COMMENTS_UNAVAILABLE",
                "message": "公开评论采样不可用",
                "occurred_at": occurred_at,
                "retryable": False,
            })
            continue
        if not returned:
            outcome["empty_results"] += 1
            continue
        malformed = False
        for comment in returned[:per_post_limit]:
            record = _normalize_comment_record(
                comment, post_id, post_url, occurred_at
            )
            if record is None:
                malformed = True
                continue
            key = (post_id, record["comment_id"])
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
        if malformed:
            outcome["failures"] += 1
            failed_parents.add(post_id)
            error_log.append({
                "url": post_url,
                "stage": "collect_comments",
                "error_code": "COMMENTS_UNAVAILABLE",
                "message": "公开评论响应包含无效记录",
                "occurred_at": occurred_at,
                "retryable": False,
            })
    if reservation is not None:
        reservation.verify_identity()
    if _write_comments_atomic(path, records, reservation=reservation):
        outcome["comments_collected"] = len(records)
    else:
        affected = {record["parent_post_id"] for record in records}
        outcome["failures"] += len(affected - failed_parents)
        outcome["comments_collected"] = 0
        error_log.append({
            "url": None,
            "stage": "persist_comments",
            "error_code": "COMMENTS_UNAVAILABLE",
            "message": "评论产物写入失败",
            "occurred_at": occurred_at,
            "retryable": False,
        })
    return outcome


def _post_key(p: dict) -> str:
    """增量去重主键:post_id > bvid > post_url。"""
    return str(p.get("post_id") or p.get("bvid") or p.get("post_url") or "")


def _load_existing_posts(ws: str) -> tuple[list[dict], str, str]:
    """读取既有采集产物中的帖子,用于增量续采去重。

    优先 source/posts.jsonl(无损 JSONL),回退 normalized-posts.csv(字段可能经 CSV 字符串化)。
    """
    posts: list[dict] = []
    snapshot = read_resume_artifact(
        ws,
        "source/posts.jsonl",
        allowed_artifacts=_PUBLIC_ARTIFACTS,
        max_bytes=_MAX_RESUME_ARTIFACT_BYTES,
    )
    try:
        posts_payload = snapshot.payload
        if posts_payload is not None:
            for line in posts_payload.decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    posts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except UnicodeDecodeError as exc:
        raise WorkspaceContractError("resume artifact encoding is invalid") from exc
    if not posts:
        csv_snapshot = read_resume_artifact(
            ws,
            "normalized-posts.csv",
            allowed_artifacts=_PUBLIC_ARTIFACTS,
            max_bytes=_MAX_RESUME_ARTIFACT_BYTES,
        )
        try:
            csv_payload = csv_snapshot.payload
            if csv_payload is not None:
                with io.StringIO(
                    csv_payload.decode("utf-8"), newline=""
                ) as handle:
                    for row in csv.DictReader(handle):
                        posts.append({k: v for k, v in row.items()})
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                "resume artifact encoding is invalid"
            ) from exc
        if csv_payload is not None:
            snapshot = csv_snapshot
    return posts, snapshot.source_format, snapshot.source_digest


def _latest_published_at(posts: list[dict]) -> str | None:
    """返回既有帖子中最新(published_at 最大)的 ISO 字符串;无法解析则 None。"""

    def parse(iso):
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            return None

    best, best_dt = None, None
    for p in posts:
        dt = parse(p.get("published_at"))
        if dt is not None and (best_dt is None or dt > best_dt):
            best_dt, best = dt, p.get("published_at")
    return best


def _merge_incremental(existing: list[dict], new: list[dict]) -> tuple[list[dict], int]:
    """合并既有与新抓取的帖子,按 post_id/bvid 去重(新抓取覆盖旧)。

    返回 (合并后列表, 新增条数)。无主键的帖子直接追加,不参与去重。
    """
    merged_map: dict[str, dict] = {}
    for p in existing:
        k = _post_key(p)
        if k:
            merged_map[k] = p
    kept_no_key: list[dict] = []
    new_count = 0
    for p in new:
        k = _post_key(p)
        if not k:
            kept_no_key.append(p)
            continue
        if k not in merged_map:
            new_count += 1
        merged_map[k] = p  # 新覆盖旧(指标可能更新)
    return list(merged_map.values()) + kept_no_key, new_count


def _sanitize_collection_coverage(value) -> dict:
    """Enforce the persisted coverage allowlist at the workspace boundary."""
    if not isinstance(value, dict):
        return {}
    clean = {}
    requested_all = value.get("requested_all") is True
    terminal_observed = value.get("terminal_page_observed") is True
    clean["requested_all"] = requested_all
    clean["terminal_page_observed"] = terminal_observed
    for key in (
        "max_items",
        "observed_page_count",
        "observed_post_count",
        "cursor_fingerprint_count",
        "repeated_cursor_count",
        "range_match_count",
    ):
        field_value = value.get(key)
        if isinstance(field_value, int) and not isinstance(field_value, bool):
            if key == "max_items":
                if 1 <= field_value <= PUBLIC_ALL_HARD_MAX_ITEMS:
                    clean[key] = field_value
            else:
                clean[key] = max(0, field_value)
    stop_condition = value.get("stop_condition")
    if isinstance(stop_condition, str) and stop_condition in {
        "terminal_page",
        "idle",
        "timeout",
        "repeated_cursor",
        "max_items",
        "max_scrolls",
        "date_lower_bound",
        "limit",
    }:
        clean["stop_condition"] = stop_condition
    clean["is_exhaustive"] = bool(
        value.get("is_exhaustive") is True
        and requested_all
        and terminal_observed
        and stop_condition == "terminal_page"
    )
    range_filter_applied = value.get("range_filter_applied") is True
    range_match_count = clean.get("range_match_count")
    clean["range_filter_applied"] = range_filter_applied
    clean["range_no_match"] = bool(
        value.get("range_no_match") is True
        and range_filter_applied
        and clean.get("observed_post_count", 0) > 0
        and range_match_count == 0
    )
    return clean


def _safe_public_url(value) -> str | None:
    """Return a credential/query/fragment-free public URL for output fields."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urllib.parse.urlparse(value)
        hostname = parsed.hostname
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            return None
    except ValueError:
        return None
    return urllib.parse.urlunsplit(("https", hostname.lower(), parsed.path or "/", "", ""))


def _safe_stop_reason(value) -> str:
    return (
        value
        if isinstance(value, str) and value in _KNOWN_STOP_REASONS
        else SR_INTERNAL
    )


def _safe_timestamp(value) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _sanitize_report_error(value) -> dict:
    """Map an internal/adaptor error to the report's fixed public vocabulary."""
    source = value if isinstance(value, dict) else {}
    stage = source.get("stage")
    if not isinstance(stage, str) or stage not in _ERROR_STAGE_MESSAGES:
        stage = "check_access"
    error_code = source.get("error_code")
    if not isinstance(error_code, str) or error_code not in _REPORT_ERROR_CODES:
        error_code = SR_INTERNAL
    clean = {
        "stage": stage,
        "error_code": error_code,
        "url": _safe_public_url(source.get("url")),
        "message": _ERROR_STAGE_MESSAGES[stage],
        "occurred_at": _safe_timestamp(source.get("occurred_at")),
    }
    diagnostic_code = source.get("diagnostic_code")
    if (
        isinstance(diagnostic_code, str)
        and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", diagnostic_code)
    ):
        clean["diagnostic_code"] = diagnostic_code
    return clean


def _write_task_json(
    ws: str,
    *,
    platform: str,
    profile_url: str,
    requested_limit: int,
    date_from: str | None,
    date_to: str | None,
    include_comments: bool,
    enrich_details: bool = False,
    task_status: str,
    stop_reason: str | None,
    collected_count: int,
    collected_at: str,
    incremental: bool = False,
    existing_count: int = 0,
    new_count: int = 0,
    resume_source_format: str | None = None,
    resume_source_digest: str | None = None,
    collection_coverage: dict | None = None,
    comment_collection: dict | None = None,
    reservation: _WorkspaceReservation | None = None,
) -> None:
    """落盘 task.json(任务状态与停止原因,见 SKILL.md「任务状态与停止原因」)。"""
    payload = {
        "platform": platform,
        "profile_url": _safe_public_url(profile_url),
        "requested_limit": requested_limit,
        "date_from": date_from,
        "date_to": date_to,
        "include_comments": include_comments,
        "enrich_details": enrich_details,
        "task_status": task_status,
        "stop_reason": (
            _safe_stop_reason(stop_reason) if stop_reason is not None else None
        ),
        "collected_count": collected_count,
        "collected_at": _safe_timestamp(collected_at),
        "incremental": incremental,
        "existing_count": existing_count,
        "new_count": new_count,
        "resume_source": (
            {
                "format": resume_source_format,
                "digest_algorithm": "sha256",
                "digest": resume_source_digest,
            }
            if resume_source_format is not None
            and resume_source_digest is not None
            else None
        ),
        "collection_coverage": _sanitize_collection_coverage(collection_coverage),
        "comment_collection": comment_collection or {},
    }
    handle = (
        reservation.open_text("task.json")
        if reservation is not None
        else open(os.path.join(ws, "task.json"), "w", encoding="utf-8")
    )
    with handle as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_report(
    adapter,
    url: str,
    profile: dict,
    posts: list[dict],
    ws: str,
    *,
    task_status: str,
    stop_reason: str | None,
    error_log: list[dict],
    incremental: bool = False,
    existing_count: int = 0,
    new_count: int = 0,
    collection_coverage: dict | None = None,
    comment_collection: dict | None = None,
    reservation: _WorkspaceReservation | None = None,
) -> None:
    """生成采集质量报告(含停止位置、成功/失败数量、字段覆盖率、错误日志)。"""
    lines = [
        "# 采集质量报告",
        "",
        f"- 平台: {adapter.platform}",
        f"- 账号: {_safe_public_url(url)}",
        f"- 采集时间: {datetime.now(_BEIJING).isoformat()}",
        f"- 任务状态 task_status: {task_status}",
        "- 停止原因 stop_reason: "
        f"{_safe_stop_reason(stop_reason) if stop_reason else 'null'}",
        f"- 资料 field_visibility 可见字段数: {_vis_count(profile)}",
        f"- 内容条数: {len(posts)}",
    ]
    if incremental:
        lines.append(f"- 增量续采: 是(既有 {existing_count} 条 + 新增 {new_count} 条)")
    lines.append("")
    lines.append("## 覆盖与完备性")
    lines.append("")
    coverage = _sanitize_collection_coverage(collection_coverage)
    if coverage:
        for key, value in coverage.items():
            rendered = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {rendered}")
    else:
        lines.append("- collection_coverage: {}")
    if comment_collection:
        lines.append("")
        lines.append("## 评论采集")
        lines.append("")
        for key, value in comment_collection.items():
            lines.append(f"- {key}: {value}")
    lines.append("")
    if posts:
        for fld in ("views", "likes", "comments", "favorites", "shares", "coins", "danmaku"):
            visible = sum(1 for p in posts if p.get(fld) is not None)
            lines.append(f"- 指标 {fld}: {visible}/{len(posts)} 可见")
    if error_log:
        lines.append("")
        lines.append("## 错误日志")
        lines.append("")
        for raw_error in error_log:
            e = _sanitize_report_error(raw_error)
            diagnostic_code = e.get("diagnostic_code")
            diagnostic = (
                f" diagnostic_code={diagnostic_code}"
                if isinstance(diagnostic_code, str) and diagnostic_code
                else ""
            )
            lines.append(
                f"- stage={e.get('stage')} error_code={e.get('error_code')} "
                f"url={e.get('url')} message={e.get('message')} occurred_at={e.get('occurred_at')}"
                f"{diagnostic}"
            )
    handle = (
        reservation.open_text("collection-report.md")
        if reservation is not None
        else open(
            os.path.join(ws, "collection-report.md"), "w", encoding="utf-8"
        )
    )
    with handle as f:
        f.write("\n".join(lines) + "\n")


def _guard_workspace_reservations(function):
    """Close every reservation created by one run, including exceptional exits."""

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        active: list[_WorkspaceReservation] = []
        token = _ACTIVE_RESERVATIONS.set(active)
        try:
            return function(*args, **kwargs)
        except (
            WorkspaceCapabilityError,
            WorkspaceExistsError,
            WorkspaceIdentityError,
            WorkspaceVerificationError,
        ):
            print("[FAILED] 输出目录不安全、已占用或身份已改变", file=sys.stderr)
            return 2
        except WorkspaceError:
            print("[FAILED] 产物序列化或提交失败", file=sys.stderr)
            return 3
        except Exception:
            print("[FAILED] 产物序列化或发布失败", file=sys.stderr)
            return 3
        finally:
            for reservation in reversed(active):
                reservation.close()
            _ACTIVE_RESERVATIONS.reset(token)

    return guarded


@_guard_workspace_reservations
def run(
    url: str,
    limit: int = PUBLIC_LIMIT_DEFAULT,
    out_dir: str | None = None,
    include_comments: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    resume: bool = False,
    resume_out: str | None = None,
    since: str | None = None,
    browser_fallback: bool | None = None,
    collect_all: bool = False,
    max_items: int | None = None,
    max_seconds: float | None = None,
    max_scrolls: int | None = None,
    enrich_details: bool = False,
) -> int:
    if resume and not out_dir:
        print("[FAILED] 增量续采(--resume)必须配合 --out 指定既有任务目录", file=sys.stderr)
        return 2
    if resume_out is not None and not resume:
        print("[FAILED] --resume-out 必须与 --resume 联用", file=sys.stderr)
        return 2
    if (
        resume
        and resume_out is not None
        and os.path.abspath(str(out_dir)) == os.path.abspath(resume_out)
    ):
        print("[FAILED] --resume-out 必须不同于只读的 --out", file=sys.stderr)
        return 2
    if since is not None and not resume:
        print("[FAILED] --since 必须与 --resume 联用", file=sys.stderr)
        return 2

    budget_was_supplied = any(
        value is not None for value in (max_items, max_seconds, max_scrolls)
    )
    try:
        if collect_all:
            if validate_public_limit(limit) != PUBLIC_LIMIT_DEFAULT:
                raise ValueError("--all cannot be combined with a non-default limit")
            max_items = (
                PUBLIC_ALL_DEFAULT_MAX_ITEMS if max_items is None else max_items
            )
            max_seconds = (
                PUBLIC_ALL_DEFAULT_MAX_SECONDS if max_seconds is None else max_seconds
            )
            max_scrolls = (
                PUBLIC_ALL_DEFAULT_MAX_SCROLLS if max_scrolls is None else max_scrolls
            )
            max_items, max_seconds, max_scrolls = validate_public_all_budgets(
                max_items, max_seconds, max_scrolls
            )
        else:
            limit = validate_public_limit(limit)
            if budget_was_supplied:
                raise ValueError("--all budgets require --all")
    except ValueError as exc:
        print(f"[FAILED] 参数无效: {exc}", file=sys.stderr)
        return 2

    if out_dir:
        try:
            _preflight_explicit_workspace(out_dir, resume=resume)
        except WorkspaceContractError:
            print("[FAILED] 输出目录不安全或已包含其他任务数据", file=sys.stderr)
            return 2
    if resume_out is not None:
        try:
            _preflight_explicit_workspace(resume_out, resume=False)
        except WorkspaceContractError:
            print("[FAILED] 续采输出目录不安全或已被占用", file=sys.stderr)
            return 2

    user_from = _parse_date(date_from)
    user_to = _default_date_to(date_to)
    explicit_since = _parse_date(since) if since is not None else None
    if date_from is not None and user_from is None:
        print("[FAILED] --date-from 无法解析", file=sys.stderr)
        return 2
    if date_to is not None and user_to is None:
        print("[FAILED] --date-to 无法解析", file=sys.stderr)
        return 2
    if since is not None and explicit_since is None:
        print("[FAILED] --since 无法解析", file=sys.stderr)
        return 2
    existing_posts: list[dict] = []
    resume_source_format: str | None = None
    resume_source_digest: str | None = None
    resume_mode = bool(resume)
    if resume_mode:
        try:
            (
                existing_posts,
                resume_source_format,
                resume_source_digest,
            ) = _load_existing_posts(str(out_dir))
        except (OSError, WorkspaceContractError):
            print("[FAILED] 增量续采目录无法安全读取", file=sys.stderr)
            return 2
        if not existing_posts:
            print(f"[warn] --resume 指定目录无既有帖子数据,退化为全量采集: {out_dir}", file=sys.stderr)
            resume_mode = False
        else:
            latest = _latest_published_at(existing_posts)
            since_iso = explicit_since if since is not None else _parse_date(latest)
            if since_iso and (user_from is None or since_iso > user_from):
                user_from = since_iso
    if user_from and user_to:
        if datetime.fromisoformat(user_from) > datetime.fromisoformat(user_to):
            print("[FAILED] --date-from 不能晚于 --date-to", file=sys.stderr)
            return 2

    env_value = os.environ.get("SOCIAL_BROWSER_FALLBACK")
    douyin_enabled = browser_fallback if browser_fallback is not None else env_value != "0"
    # Keep the default zero-argument loader call compatible with integrations
    # that replace it, while passing the policy only when it disables Douyin.
    if browser_fallback is not None:
        # An explicit CLI policy is global: False overrides even the legacy
        # BILIBILI_BROWSER_FALLBACK=1 environment setting.
        adapters = _load_adapters(
            douyin_browser_fallback=browser_fallback,
            bilibili_browser_fallback=browser_fallback,
        )
    elif douyin_enabled:
        adapters = _load_adapters()
    else:
        adapters = _load_adapters(douyin_browser_fallback=False)
    if not adapters:
        print("[FAILED] 没有可用适配器(采集器均未实现)", file=sys.stderr)
        return 2
    routing_url = sanitize_routing_url(url)
    if routing_url is None:
        print("[FAILED] 账号主页 URL 权限或路径格式无效", file=sys.stderr)
        return 2
    adapter = _pick(adapters, routing_url)
    if adapter is None:
        # URL 不属于任何已加载平台 → UNSUPPORTED_PLATFORM(见 exceptions.md §1)
        print(f"[FAILED] 无支持的适配器 (stop_reason={SR_UNSUPPORTED})", file=sys.stderr)
        return 2

    platform = adapter.platform
    adapter_canonicalizer = getattr(adapter, "canonicalize_profile_url", None)
    canonical_url = (
        adapter_canonicalizer(routing_url)
        if callable(adapter_canonicalizer)
        else canonical_profile_url(platform, routing_url)
    )
    if canonical_url is None:
        print("[FAILED] 账号主页 URL 不符合平台公开路径规范", file=sys.stderr)
        return 2
    url = canonical_url
    safe_url = canonical_url
    if collect_all and platform != "douyin":
        print("[FAILED] --all 目前仅支持抖音账号主页", file=sys.stderr)
        return 2
    if enrich_details and platform != "douyin":
        print("[FAILED] --enrich-details 仅支持抖音账号主页", file=sys.stderr)
        return 2

    requested_count = max_items if collect_all else limit

    m = re.search(r"(\d+)", url)
    account = m.group(1) if m else "account"
    date = datetime.now(_BEIJING).strftime("%Y%m%d")
    reservation: _WorkspaceReservation
    try:
        if resume:
            reservation = _reserve_resume_workspace(
                str(out_dir), resume_out=resume_out, date=date
            )
        elif out_dir:
            reservation = _prepare_explicit_workspace(out_dir)
        else:
            reservation = _reserve_default_workspace(
                f"{platform}-{account}-{date}"
            )
    except (OSError, WorkspaceContractError):
        print("[FAILED] 输出目录无法安全预留", file=sys.stderr)
        return 2
    ws = reservation.path
    src = reservation.source_path

    # 增量续采:基于既有 posts 的 published_at / bvid 去重续采,避免重复打满配额
    # 规范化日期范围(中国平台默认 +08:00);增量续采时起点取既有最新发布时间
    date_from_iso = user_from
    date_to_iso = user_to
    date_range = None
    if date_from_iso or date_to_iso:
        date_range = (date_from_iso, date_to_iso)

    # 执行前回显:平台、采集范围、最大数量、评论开关(见 SKILL.md §1「任务创建」)
    echo_parts = [
        f"platform={platform}",
        f"limit={requested_count}",
        f"date_range={date_range if date_range else 'unset'}",
        f"include_comments={include_comments}",
    ]
    if collect_all:
        echo_parts.extend([
            "all=on",
            f"max_seconds={max_seconds}",
            f"max_scrolls={max_scrolls}",
        ])
    if resume_mode:
        echo_parts.append(f"resume=on existing={len(existing_posts)} since={date_from_iso}")
    print(f"[echo] " + " ".join(echo_parts))

    collected_at = datetime.now(_BEIJING).isoformat()
    task_status = "COLLECTING"
    stop_reason: str | None = None
    error_log: list[dict] = []
    posts: list = []
    profile: dict = {}
    collection_coverage: dict = (
        {"requested_all": True, "max_items": max_items}
        if collect_all
        else {}
    )
    comment_collection: dict = {}
    detail_unavailable_count = 0

    def persist_access_failure(reason: str) -> int | None:
        error = {
            "url": safe_url,
            "stage": "check_access",
            "error_code": reason,
            "message": _ERROR_STAGE_MESSAGES["check_access"],
            "occurred_at": collected_at,
            "retryable": False,
        }
        try:
            _write_task_json(
                ws,
                platform=platform,
                profile_url=url,
                requested_limit=requested_count,
                date_from=date_from_iso,
                date_to=date_to_iso,
                include_comments=include_comments,
                task_status="FAILED",
                enrich_details=enrich_details,
                stop_reason=reason,
                collected_count=0,
                collected_at=collected_at,
                resume_source_format=resume_source_format,
                resume_source_digest=resume_source_digest,
                collection_coverage=collection_coverage,
                reservation=reservation,
            )
            _write_report(
                adapter,
                url,
                profile,
                posts,
                ws,
                task_status="FAILED",
                stop_reason=reason,
                collection_coverage=collection_coverage,
                error_log=[error],
                reservation=reservation,
            )
            reservation.commit()
            return None
        except (
            WorkspaceCapabilityError,
            WorkspaceExistsError,
            WorkspaceIdentityError,
            WorkspaceVerificationError,
        ):
            return 2
        except WorkspaceError:
            return 3

    # 1) check_access:不绕过任何保护(见 base.py / exceptions.md §2)
    access_failed = False
    try:
        access = adapter.check_access(url)
    except Exception as e:
        # 适配器未启用(WeiboCollector._require_enabled 抛 RuntimeError 携 ADAPTER_UNAVAILABLE)
        stop_reason = _stop_reason_from_exc(e)
        task_status = "FAILED"
        access_failed = True
    else:
        if not access.get("accessible"):
            stop_reason = _safe_stop_reason(access.get("stop_reason"))
            # check_access 阶段尚无已采数据,所有受阻场景统一 FAILED(见 exceptions.md §1)
            task_status = "FAILED"
            access_failed = True
    if access_failed:
        persistence_failure = persist_access_failure(stop_reason)
        if persistence_failure is not None:
            reservation.close()
            print("[FAILED] 输出产物无法安全提交", file=sys.stderr)
            return persistence_failure
        print(f"[STOP] task_status={task_status} stop_reason={stop_reason} stage=check_access")
        reservation.close()
        return 3

    # 2) 内容列表(先于资料,便于回填;失败不阻断资料写入)
    try:
        if collect_all:
            posts = adapter.collect_all_post_list(
                url,
                date_range=date_range,
                max_items=max_items,
                max_seconds=max_seconds,
                max_scrolls=max_scrolls,
            )
        else:
            posts = adapter.collect_post_list(url, limit=limit, date_range=date_range)
    except Exception as e:
        partial_posts = getattr(e, "partial_posts", None)
        if isinstance(partial_posts, list):
            posts = partial_posts[:requested_count]
        diagnostic_code = getattr(e, "diagnostic_code", None)
        stop_reason = _stop_reason_from_exc(e)
        # 登录/验证/频控/解析失败 → PARTIAL(已有数据保留)或 FAILED(无已采数据)
        task_status = "PARTIAL" if posts else "FAILED"
        entry = {
            "url": safe_url, "stage": "collect_post_list",
            "error_code": stop_reason,
            "message": _ERROR_STAGE_MESSAGES["collect_post_list"],
            "occurred_at": collected_at, "retryable": False,
        }
        if isinstance(diagnostic_code, str) and diagnostic_code:
            entry["diagnostic_code"] = diagnostic_code
        error_log.append(entry)
        print(f"[warn] 内容列表采集异常 stop_reason={stop_reason}", file=sys.stderr)
    try:
        collection_coverage = _sanitize_collection_coverage(
            adapter.get_collection_coverage()
        )
    except Exception:
        collection_coverage = {}
    if collect_all:
        collection_coverage["requested_all"] = True
        collection_coverage["max_items"] = max_items
    if (
        collect_all
        and stop_reason is None
        and not collection_coverage.get("is_exhaustive", False)
    ):
        stop_reason = SR_PARSER_FAILED
        task_status = "PARTIAL" if posts else "FAILED"
        error_log.append({
            "url": url,
            "stage": "collection_coverage",
            "error_code": SR_PARSER_FAILED,
            "message": "全量采集覆盖账本缺少一致的末页完备性证据",
            "occurred_at": collected_at,
            "retryable": False,
            "diagnostic_code": "ALL_POSTS_INCOMPLETE",
        })

    # limit 与 date_range 的交集:适配器可能仅应用其一,此处再做一次本地交集过滤
    # (见 SKILL.md §1「采集数量和日期范围同时存在时,取两者共同限定的结果」)
    if posts and (date_from_iso or date_to_iso):
        posts = _filter_by_date(posts, date_from_iso, date_to_iso)
    if posts and not resume_mode:
        posts = posts[:requested_count]

    # 增量续采:合并既有帖子,按 post_id/bvid 去重(新抓取的覆盖旧的)
    new_count = 0
    if resume_mode and existing_posts:
        posts, new_count = _merge_incremental(existing_posts, posts)
    _canonicalize_post_urls(platform, posts)

    # 3) 资料(失败不阻塞已采内容)
    try:
        profile = adapter.collect_profile(url)
        if not isinstance(profile, dict):
            raise ValueError("invalid profile result")
        profile["profile_url"] = url
    except Exception as e:
        if stop_reason is None:
            stop_reason = _stop_reason_from_exc(e)
            task_status = "PARTIAL" if posts else "FAILED"
        error_log.append({
            "url": safe_url, "stage": "collect_profile",
            "error_code": _stop_reason_from_exc(e),
            "message": _ERROR_STAGE_MESSAGES["collect_profile"],
            "occurred_at": collected_at, "retryable": False,
        })
        print("[warn] 资料采集异常", file=sys.stderr)
        profile = {}

    if enrich_details and platform == "douyin" and posts:
        detail_unavailable_count = _enrich_douyin_details(
            adapter, posts, error_log, collected_at
        )

    # 4) 落盘原始数据与归一化 CSV(已采集数据必须保留,见 exceptions.md §2 规则 3)
    try:
        with reservation.open_text("source/profile.json") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        with reservation.open_text("source/posts.jsonl") as f:
            for p in posts:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

        _write_csv(
            posts,
            os.path.join(ws, "normalized-posts.csv"),
            reservation=reservation,
        )

        # 5) 评论(可选;失败不阻塞主任务,见 exceptions.md §1.1)
        if include_comments:
            comment_collection = _collect_and_persist_comments(
                adapter,
                posts,
                os.path.join(src, "comments.jsonl"),
                error_log,
                collected_at,
                reservation=reservation,
            )
            print(
                "[OK] 评论采样: "
                f"attempted_posts={comment_collection['attempted_posts']} "
                f"comments_collected={comment_collection['comments_collected']} "
                f"empty_results={comment_collection['empty_results']} "
                f"failures={comment_collection['failures']}"
            )
    except (
        WorkspaceCapabilityError,
        WorkspaceExistsError,
        WorkspaceIdentityError,
        WorkspaceVerificationError,
    ):
        reservation.close()
        print("[FAILED] 输出目录身份已改变；拒绝写入", file=sys.stderr)
        return 2
    except WorkspaceError:
        reservation.close()
        print("[FAILED] 输出产物序列化失败", file=sys.stderr)
        return 3

    # 6) 最终任务状态:无 stop_reason → COMPLETED;有 stop_reason 但有数据 → PARTIAL
    exhaustive_range_no_match = bool(
        collect_all
        and date_range is not None
        and collection_coverage.get("is_exhaustive") is True
        and collection_coverage.get("range_filter_applied") is True
        and collection_coverage.get("range_no_match") is True
        and collection_coverage.get("observed_post_count", 0) > 0
        and collection_coverage.get("range_match_count") == 0
        and not posts
    )
    if stop_reason is None:
        task_status = "COMPLETED" if posts or exhaustive_range_no_match else "FAILED"
        if task_status == "COMPLETED" and detail_unavailable_count:
            task_status = "PARTIAL"
        if not posts and not profile:
            stop_reason = SR_NO_PUBLIC_CONTENT
            task_status = "FAILED"
    else:
        task_status = "PARTIAL" if posts else "FAILED"

    try:
        _write_task_json(
            ws, platform=platform, profile_url=url,
            requested_limit=requested_count,
            date_from=date_from_iso, date_to=date_to_iso,
            include_comments=include_comments, task_status=task_status,
            enrich_details=enrich_details,
            stop_reason=stop_reason, collected_count=len(posts),
            collected_at=collected_at,
            incremental=resume_mode, existing_count=len(existing_posts),
            new_count=new_count,
            resume_source_format=resume_source_format,
            resume_source_digest=resume_source_digest,
            collection_coverage=collection_coverage,
            comment_collection=comment_collection,
            reservation=reservation,
        )
        _write_report(
            adapter, url, profile, posts, ws,
            task_status=task_status, stop_reason=stop_reason,
            error_log=error_log,
            incremental=resume_mode, existing_count=len(existing_posts),
            new_count=new_count,
            collection_coverage=collection_coverage,
            comment_collection=comment_collection,
            reservation=reservation,
        )
        reservation.commit()
    except (
        WorkspaceCapabilityError,
        WorkspaceExistsError,
        WorkspaceIdentityError,
        WorkspaceVerificationError,
    ):
        reservation.close()
        print("[FAILED] 输出目录身份已改变；拒绝写入", file=sys.stderr)
        return 2
    except WorkspaceError:
        reservation.close()
        print("[FAILED] 输出产物提交失败", file=sys.stderr)
        return 3

    print(
        f"[OK] 平台={platform} 资料可见字段={_vis_count(profile)} "
        f"内容条数={len(posts)} task_status={task_status} "
        f"stop_reason={stop_reason if stop_reason else 'null'}"
    )
    print(f"[OK] 输出目录: {ws}")
    reservation.close()
    return 0 if task_status != "FAILED" else 3


def main() -> None:
    ap = argparse.ArgumentParser(description="公开社交媒体账号采集")
    ap.add_argument("url", help="账号主页 URL,如 https://space.bilibili.com/123")
    range_group = ap.add_mutually_exclusive_group()
    range_group.add_argument(
        "--limit",
        type=int,
        default=None,
        help="采集条数(默认30,最大100)",
    )
    range_group.add_argument(
        "--all",
        dest="collect_all",
        action="store_true",
        help="采集抖音公开作品直到明确末页",
    )
    ap.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="--all 最大保留作品数(默认10000,硬上限50000)",
    )
    ap.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="--all 最长秒数(默认1800,硬上限14400)",
    )
    ap.add_argument(
        "--max-scrolls",
        type=int,
        default=None,
        help="--all 最大滚动次数(默认2000,硬上限20000)",
    )
    ap.add_argument(
        "--out", default=None, help="输出目录(默认 workspace/<platform>-<account>-<date>/)"
    )
    ap.add_argument("--comments", action="store_true", help="开启评论采样(默认关)")
    ap.add_argument(
        "--enrich-details",
        action="store_true",
        help="仅对缺少公开基础字段的抖音作品补充详情",
    )
    ap.add_argument("--date-from", default=None, help="起始日期 YYYY-MM-DD 或 ISO 8601(北京时间)")
    ap.add_argument("--date-to", default=None, help="结束日期 YYYY-MM-DD 或 ISO 8601(北京时间)")
    ap.add_argument(
        "--resume", action="store_true",
        help="增量续采:读取 --out 目录既有 source/posts.jsonl,以其最新 published_at 为起点续采,"
             "按 post_id/bvid 去重合并(新覆盖旧),并写入新的不可变任务目录。必须配合 --out。",
    )
    ap.add_argument(
        "--resume-out",
        default=None,
        help="增量续采的新输出目录；省略时原子预留 OLD-resume-<date> 及数字后缀。",
    )
    ap.add_argument(
        "--since", default=None,
        help="增量续采起点(YYYY-MM-DD 或 ISO 8601,北京时间);覆盖从既有数据推导的起始时间。仅与 --resume 联用。",
    )
    browser_group = ap.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--browser-fallback", dest="browser_fallback", action="store_true",
        help="显式启用系统浏览器传输层降级。",
    )
    browser_group.add_argument(
        "--no-browser-fallback", dest="browser_fallback", action="store_false",
        help="禁止启动系统浏览器；仅使用 HTTP/SSR 快速路径。",
    )
    ap.set_defaults(browser_fallback=None)
    args = ap.parse_args()
    if args.since is not None and not args.resume:
        ap.error("--since 必须与 --resume 联用")
    if args.resume_out is not None and not args.resume:
        ap.error("--resume-out 必须与 --resume 联用")
    custom_all_budget = any(
        value is not None
        for value in (args.max_items, args.max_seconds, args.max_scrolls)
    )
    if custom_all_budget and not args.collect_all:
        ap.error("--max-items/--max-seconds/--max-scrolls 必须与 --all 联用")
    try:
        limit = validate_public_limit(
            PUBLIC_LIMIT_DEFAULT if args.limit is None else args.limit
        )
        if args.collect_all:
            max_items = (
                PUBLIC_ALL_DEFAULT_MAX_ITEMS
                if args.max_items is None
                else args.max_items
            )
            max_seconds = (
                PUBLIC_ALL_DEFAULT_MAX_SECONDS
                if args.max_seconds is None
                else args.max_seconds
            )
            max_scrolls = (
                PUBLIC_ALL_DEFAULT_MAX_SCROLLS
                if args.max_scrolls is None
                else args.max_scrolls
            )
            max_items, max_seconds, max_scrolls = validate_public_all_budgets(
                max_items, max_seconds, max_scrolls
            )
        else:
            max_items = max_seconds = max_scrolls = None
    except ValueError as exc:
        ap.error(str(exc))
    date_from_iso = _parse_date(args.date_from)
    date_to_iso = _default_date_to(args.date_to)
    if args.date_from and not date_from_iso:
        print(f"[FAILED] --date-from 无法解析: {args.date_from}", file=sys.stderr)
        raise SystemExit(2)
    if args.date_to and not date_to_iso:
        print(f"[FAILED] --date-to 无法解析: {args.date_to}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(
        args.url, limit, args.out, args.comments, date_from_iso, date_to_iso,
        resume=args.resume, resume_out=args.resume_out, since=args.since,
        browser_fallback=args.browser_fallback,
        collect_all=args.collect_all, max_items=max_items,
        max_seconds=max_seconds, max_scrolls=max_scrolls,
        enrich_details=args.enrich_details,
    ))


if __name__ == "__main__":
    main()
