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
import csv
import json
import math
import os
import re
import sys
import tempfile
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


def _stop_reason_from_exc(e: Exception) -> str:
    """从适配器异常中提取 stop_reason;无法识别时 INTERNAL_ERROR。

    优先级:
    1. 异常的 .stop_reason 属性(BilibiliError / DouyinError 使用)
    2. 异常消息中的 [REASON] 前缀(WeiboCollector 的 RuntimeError 使用)
    3. 兜底 INTERNAL_ERROR
    """
    reason = getattr(e, "stop_reason", None)
    if isinstance(reason, str) and reason:
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
    except Exception as e:  # pragma: no cover
        print(f"[warn] 加载 bilibili 适配器失败: {e}", file=sys.stderr)
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


def _write_csv(posts: list[dict], path: str) -> None:
    if posts:
        keys: list[str] = []
        for p in posts:
            for k in p:
                if k not in keys:
                    keys.append(k)
    else:
        keys = ["post_id", "post_url", "title", "published_at", "collection_status"]
    with open(path, "w", newline="", encoding="utf-8") as f:
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
    try:
        parsed = urllib.parse.urlparse(post_url)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"douyin.com", "www.douyin.com", "iesdouyin.com"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    match = re.fullmatch(r"/(?:video|note)/(\d+)/?", parsed.path)
    if match is None or match.group(1) != post_id:
        return None
    return post_url


def _set_detail_status(post: dict, status: str) -> None:
    metrics = post.get("platform_metrics")
    post["platform_metrics"] = dict(metrics) if isinstance(metrics, dict) else {}
    post["platform_metrics"]["detail_status"] = status


def _valid_comment_parent(platform: str, post: dict) -> tuple[str, str] | None:
    post_id = str(post.get("post_id") or "").strip()
    post_url = post.get("post_url")
    if not post_id or not isinstance(post_url, str):
        return None
    if platform == "douyin":
        return (post_id, post_url) if _douyin_item_url(post) else None
    try:
        parsed = urllib.parse.urlparse(post_url)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    if platform == "bilibili":
        if parsed.hostname not in {"bilibili.com", "www.bilibili.com"}:
            return None
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]+)/?", parsed.path)
        if match is None or match.group(1) != post_id:
            return None
    return post_id, post_url


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


def _workspace_paths_safe(ws: str) -> bool:
    if os.path.lexists(ws) and (os.path.islink(ws) or not os.path.isdir(ws)):
        return False
    source = os.path.join(ws, "source")
    if os.path.lexists(source) and (
        os.path.islink(source) or not os.path.isdir(source)
    ):
        return False
    return True


def _write_comments_atomic(path: str, records: list[dict]) -> bool:
    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=os.path.dirname(path),
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
        )
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
        temporary = None
        return True
    except Exception:
        return False
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


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
    if _write_comments_atomic(path, records):
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


def _load_existing_posts(ws: str) -> list[dict]:
    """读取既有采集产物中的帖子,用于增量续采去重。

    优先 source/posts.jsonl(无损 JSONL),回退 normalized-posts.csv(字段可能经 CSV 字符串化)。
    """
    src = os.path.join(ws, "source", "posts.jsonl")
    posts: list[dict] = []
    if os.path.isfile(src):
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    posts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not posts:
        csvp = os.path.join(ws, "normalized-posts.csv")
        if os.path.isfile(csvp):
            with open(csvp, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    posts.append({k: v for k, v in row.items()})
    return posts


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
        "observed_page_count",
        "observed_post_count",
        "cursor_fingerprint_count",
        "repeated_cursor_count",
        "range_match_count",
    ):
        field_value = value.get(key)
        if isinstance(field_value, int) and not isinstance(field_value, bool):
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
    collection_coverage: dict | None = None,
    comment_collection: dict | None = None,
) -> None:
    """落盘 task.json(任务状态与停止原因,见 SKILL.md「任务状态与停止原因」)。"""
    payload = {
        "platform": platform,
        "profile_url": profile_url,
        "requested_limit": requested_limit,
        "date_from": date_from,
        "date_to": date_to,
        "include_comments": include_comments,
        "enrich_details": enrich_details,
        "task_status": task_status,
        "stop_reason": stop_reason,
        "collected_count": collected_count,
        "collected_at": collected_at,
        "incremental": incremental,
        "existing_count": existing_count,
        "new_count": new_count,
        "collection_coverage": _sanitize_collection_coverage(collection_coverage),
        "comment_collection": comment_collection or {},
    }
    with open(os.path.join(ws, "task.json"), "w", encoding="utf-8") as f:
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
) -> None:
    """生成采集质量报告(含停止位置、成功/失败数量、字段覆盖率、错误日志)。"""
    lines = [
        "# 采集质量报告",
        "",
        f"- 平台: {adapter.platform}",
        f"- 账号: {url}",
        f"- 采集时间: {datetime.now(_BEIJING).isoformat()}",
        f"- 任务状态 task_status: {task_status}",
        f"- 停止原因 stop_reason: {stop_reason if stop_reason else 'null'}",
        f"- 资料 field_visibility: {profile.get('field_visibility')}",
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
        for e in error_log:
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
    with open(os.path.join(ws, "collection-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run(
    url: str,
    limit: int = 30,
    out_dir: str | None = None,
    include_comments: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    resume: bool = False,
    since: str | None = None,
    browser_fallback: bool | None = None,
    collect_all: bool = False,
    max_items: int = 10_000,
    max_seconds: float = 1800.0,
    max_scrolls: int = 2000,
    enrich_details: bool = False,
) -> int:
    if resume and not out_dir:
        print("[FAILED] 增量续采(--resume)必须配合 --out 指定既有任务目录", file=sys.stderr)
        return 2
    if out_dir and not _workspace_paths_safe(out_dir):
        print("[FAILED] 输出目录或 source 不能是符号链接", file=sys.stderr)
        return 2

    user_from = _parse_date(date_from)
    user_to = _default_date_to(date_to)
    existing_posts: list[dict] = []
    resume_mode = bool(resume)
    if resume_mode:
        existing_posts = _load_existing_posts(str(out_dir))
        if not existing_posts:
            print(f"[warn] --resume 指定目录无既有帖子数据,退化为全量采集: {out_dir}", file=sys.stderr)
            resume_mode = False
        else:
            latest = _latest_published_at(existing_posts)
            since_iso = _parse_date(since) if since else _parse_date(latest)
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
    adapter = _pick(adapters, url)
    if adapter is None:
        # URL 不属于任何已加载平台 → UNSUPPORTED_PLATFORM(见 exceptions.md §1)
        print(f"[FAILED] 无支持的适配器: {url} (stop_reason={SR_UNSUPPORTED})", file=sys.stderr)
        return 2

    platform = adapter.platform
    if collect_all and platform != "douyin":
        print("[FAILED] --all 目前仅支持抖音账号主页", file=sys.stderr)
        return 2
    if collect_all and (
        max_items <= 0
        or not math.isfinite(max_seconds)
        or max_seconds <= 0
        or max_scrolls <= 0
    ):
        print("[FAILED] --all 安全预算必须为正数", file=sys.stderr)
        return 2

    requested_count = max_items if collect_all else limit

    m = re.search(r"(\d+)", url)
    account = m.group(1) if m else "account"
    date = datetime.now(_BEIJING).strftime("%Y%m%d")
    ws = out_dir or os.path.join(
        os.path.dirname(_HERE), "workspace", f"{platform}-{account}-{date}"
    )
    src = os.path.join(ws, "source")
    if not _workspace_paths_safe(ws):
        print("[FAILED] 输出目录或 source 不能是符号链接", file=sys.stderr)
        return 2
    os.makedirs(src, exist_ok=True)

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
    collection_coverage: dict = {}
    comment_collection: dict = {}
    detail_unavailable_count = 0

    # 1) check_access:不绕过任何保护(见 base.py / exceptions.md §2)
    try:
        access = adapter.check_access(url)
        if not access.get("accessible"):
            stop_reason = access.get("stop_reason") or SR_INTERNAL
            # check_access 阶段尚无已采数据,所有受阻场景统一 FAILED(见 exceptions.md §1)
            task_status = "FAILED"
            _write_task_json(
                ws, platform=platform, profile_url=url, requested_limit=requested_count,
                date_from=date_from_iso, date_to=date_to_iso,
                include_comments=include_comments, task_status=task_status,
                enrich_details=enrich_details,
                stop_reason=stop_reason, collected_count=0, collected_at=collected_at,
                collection_coverage=collection_coverage,
            )
            _write_report(
                adapter, url, profile or {}, posts, ws,
                task_status=task_status, stop_reason=stop_reason,
                collection_coverage=collection_coverage, error_log=[{
                    "url": url, "stage": "check_access",
                    "error_code": stop_reason,
                    "message": access.get("reason", "访问受限"),
                    "occurred_at": collected_at, "retryable": False,
                }],
            )
            print(f"[STOP] task_status={task_status} stop_reason={stop_reason} reason={access.get('reason')}")
            return 3
    except Exception as e:
        # 适配器未启用(WeiboCollector._require_enabled 抛 RuntimeError 携 ADAPTER_UNAVAILABLE)
        stop_reason = _stop_reason_from_exc(e)
        task_status = "FAILED"
        _write_task_json(
            ws, platform=platform, profile_url=url, requested_limit=requested_count,
            date_from=date_from_iso, date_to=date_to_iso,
            include_comments=include_comments, task_status=task_status,
            enrich_details=enrich_details,
            stop_reason=stop_reason, collected_count=0, collected_at=collected_at,
            collection_coverage=collection_coverage,
        )
        _write_report(
            adapter, url, profile, posts, ws,
            task_status=task_status, stop_reason=stop_reason,
            collection_coverage=collection_coverage, error_log=[{
                "url": url, "stage": "check_access",
                "error_code": stop_reason, "message": str(e),
                "occurred_at": collected_at, "retryable": False,
            }],
        )
        print(f"[STOP] task_status={task_status} stop_reason={stop_reason} message={e}")
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
            "url": url, "stage": "collect_post_list",
            "error_code": stop_reason, "message": str(e),
            "occurred_at": collected_at, "retryable": False,
        }
        if isinstance(diagnostic_code, str) and diagnostic_code:
            entry["diagnostic_code"] = diagnostic_code
        error_log.append(entry)
        print(f"[warn] 内容列表采集异常 stop_reason={stop_reason}: {e}", file=sys.stderr)
    try:
        collection_coverage = _sanitize_collection_coverage(
            adapter.get_collection_coverage()
        )
    except Exception:
        collection_coverage = {}
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

    # 3) 资料(失败不阻塞已采内容)
    try:
        profile = adapter.collect_profile(url)
    except Exception as e:
        if stop_reason is None:
            stop_reason = _stop_reason_from_exc(e)
            task_status = "PARTIAL" if posts else "FAILED"
        error_log.append({
            "url": url, "stage": "collect_profile",
            "error_code": _stop_reason_from_exc(e), "message": str(e),
            "occurred_at": collected_at, "retryable": False,
        })
        print(f"[warn] 资料采集异常: {e}", file=sys.stderr)
        profile = {}

    if enrich_details and platform == "douyin" and posts:
        detail_unavailable_count = _enrich_douyin_details(
            adapter, posts, error_log, collected_at
        )

    # 4) 落盘原始数据与归一化 CSV(已采集数据必须保留,见 exceptions.md §2 规则 3)
    with open(os.path.join(src, "profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    with open(os.path.join(src, "posts.jsonl"), "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    _write_csv(posts, os.path.join(ws, "normalized-posts.csv"))

    # 5) 评论(可选;失败不阻塞主任务,见 exceptions.md §1.1)
    if include_comments:
        comment_collection = _collect_and_persist_comments(
            adapter,
            posts,
            os.path.join(src, "comments.jsonl"),
            error_log,
            collected_at,
        )
        print(
            "[OK] 评论采样: "
            f"attempted_posts={comment_collection['attempted_posts']} "
            f"comments_collected={comment_collection['comments_collected']} "
            f"empty_results={comment_collection['empty_results']} "
            f"failures={comment_collection['failures']}"
        )

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

    _write_task_json(
        ws, platform=platform, profile_url=url, requested_limit=requested_count,
        date_from=date_from_iso, date_to=date_to_iso,
        include_comments=include_comments, task_status=task_status,
        enrich_details=enrich_details,
        stop_reason=stop_reason, collected_count=len(posts), collected_at=collected_at,
        incremental=resume_mode, existing_count=len(existing_posts), new_count=new_count,
        collection_coverage=collection_coverage,
        comment_collection=comment_collection,
    )
    _write_report(
        adapter, url, profile, posts, ws,
        task_status=task_status, stop_reason=stop_reason, error_log=error_log,
        incremental=resume_mode, existing_count=len(existing_posts), new_count=new_count,
        collection_coverage=collection_coverage,
        comment_collection=comment_collection,
    )

    print(
        f"[OK] 平台={platform} 资料可见字段={_vis_count(profile)} "
        f"内容条数={len(posts)} task_status={task_status} "
        f"stop_reason={stop_reason if stop_reason else 'null'}"
    )
    print(f"[OK] 输出目录: {ws}")
    return 0 if task_status != "FAILED" else 3


def main() -> None:
    ap = argparse.ArgumentParser(description="公开社交媒体账号采集")
    ap.add_argument("url", help="账号主页 URL,如 https://space.bilibili.com/123")
    ap.add_argument("--limit", type=int, default=30, help="采集条数(默认30,最大100)")
    ap.add_argument("--all", dest="collect_all", action="store_true", help="采集抖音公开作品直到明确末页")
    ap.add_argument("--max-items", type=int, default=10_000, help="--all 最大保留作品数(默认10000)")
    ap.add_argument("--max-seconds", type=float, default=1800.0, help="--all 最长秒数(默认1800)")
    ap.add_argument("--max-scrolls", type=int, default=2000, help="--all 最大滚动次数(默认2000)")
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
             "按 post_id/bvid 去重合并(新覆盖旧)。必须配合 --out 指定既有任务目录。",
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
    limit = max(1, min(args.limit, 100))
    date_from_iso = _parse_date(args.date_from)
    date_to_iso = _default_date_to(args.date_to)
    if args.date_from and not date_from_iso:
        print(f"[FAILED] --date-from 无法解析: {args.date_from}", file=sys.stderr)
        raise SystemExit(2)
    if args.date_to and not date_to_iso:
        print(f"[FAILED] --date-to 无法解析: {args.date_to}", file=sys.stderr)
        raise SystemExit(2)
    if args.max_items <= 0:
        ap.error("--max-items 必须为正数")
    if not math.isfinite(args.max_seconds) or args.max_seconds <= 0:
        ap.error("--max-seconds 必须为正数")
    if args.max_scrolls <= 0:
        ap.error("--max-scrolls 必须为正数")
    raise SystemExit(run(
        args.url, limit, args.out, args.comments, date_from_iso, date_to_iso,
        resume=args.resume, since=args.since, browser_fallback=args.browser_fallback,
        collect_all=args.collect_all, max_items=args.max_items,
        max_seconds=args.max_seconds, max_scrolls=args.max_scrolls,
        enrich_details=args.enrich_details,
    ))


if __name__ == "__main__":
    main()
