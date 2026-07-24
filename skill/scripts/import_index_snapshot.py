#!/usr/bin/env python3
"""Validate and import public Douyin Web-index evidence without network access.

The Skill/Agent obtains and verifies public evidence with the environment's Web
connector. This deterministic standard-library script validates the evidence
shape, allowed URLs, and field consistency, then writes artifacts consumed by
normalize.py, analyze.py and render_report.py.
It never logs in, launches a browser, calls Douyin, or fabricates metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


BEIJING = timezone(timedelta(hours=8))
SOURCE_KINDS = {"douyin_jingxuan", "douyin_search_index"}
STOP_REASONS = {
    "LOGIN_REQUIRED",
    "VERIFICATION_REQUIRED",
    "ACCESS_RESTRICTED",
    "PARSER_FAILED",
}
METRIC_FIELDS = ("views", "likes", "comments", "favorites", "shares", "coins", "danmaku")
ACCOUNT_METRIC_FIELDS = ("douyin_id", "total_likes", "latest_post_at")
DIAGNOSTIC_CODE = "SANDBOX_INDEX_FALLBACK"


class EvidenceError(ValueError):
    """Evidence is malformed, ambiguous, or unsafe to import."""


class EmptyEvidenceError(EvidenceError):
    """Evidence is valid in shape but contains no importable records."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} 必须是 object")
    return value


def _text(value: Any, label: str, *, nullable: bool = False, maximum: int = 2000) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise EvidenceError(f"{label} 必须是字符串")
    cleaned = " ".join(unicodedata.normalize("NFKC", value).split())
    if not cleaned:
        raise EvidenceError(f"{label} 不能为空")
    if len(cleaned) > maximum:
        raise EvidenceError(f"{label} 过长")
    return cleaned


def _nonnegative_int(value: Any, label: str, *, nullable: bool = True) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        suffix = "或 null" if nullable else ""
        raise EvidenceError(f"{label} 必须是非负整数{suffix}")
    return value


def _is_douyin_host(hostname: str | None) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == "douyin.com" or host.endswith(".douyin.com")


def _canonical_url(value: Any, label: str) -> str:
    text = _text(value, label, maximum=2048)
    assert text is not None
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise EvidenceError(f"{label} 不是合法 URL") from exc
    if parsed.scheme.lower() != "https":
        raise EvidenceError(f"{label} 必须使用 https")
    if parsed.username is not None or parsed.password is not None or port is not None:
        raise EvidenceError(f"{label} 不允许 userinfo 或端口")
    if not _is_douyin_host(parsed.hostname):
        raise EvidenceError(f"{label} 必须属于 douyin.com 官方域名")
    if parsed.query or parsed.fragment:
        raise EvidenceError(f"{label} 不允许查询参数或片段")
    if not parsed.path.startswith("/"):
        raise EvidenceError(f"{label} 缺少路径")
    host = (parsed.hostname or "").lower().rstrip(".")
    path = re.sub(r"/{2,}", "/", parsed.path)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


def _profile_identity(profile_url: str) -> str:
    parsed = urlsplit(profile_url)
    if parsed.hostname not in {"douyin.com", "www.douyin.com"}:
        raise EvidenceError("profile_url 必须使用 douyin.com 或 www.douyin.com 主站主页")
    match = re.fullmatch(r"/user/([A-Za-z0-9_-]{1,512})", parsed.path)
    if not match:
        raise EvidenceError("profile_url 必须是包含安全账号 ID 的 /user/<account_id> 主站主页")
    return match.group(1)


def _post_identity(post_url: str, label: str) -> str:
    path = urlsplit(post_url).path
    match = re.fullmatch(r"/(?:m/)?(?:video|note)/(\d+)", path)
    if not match:
        raise EvidenceError(f"{label} 必须是官方 video/note 作品 URL")
    return match.group(1)


def _timestamp(
    value: Any,
    label: str,
    *,
    nullable: bool = False,
    allow_date: bool = True,
) -> tuple[str | None, str]:
    if value is None and nullable:
        return None, "unknown"
    text = _text(value, label, maximum=64)
    assert text is not None
    if allow_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            parsed_date = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise EvidenceError(f"{label} 不是合法日期") from exc
        dt = datetime.combine(parsed_date, datetime.min.time(), tzinfo=BEIJING)
        return dt.isoformat(), "date"
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise EvidenceError(f"{label} 不是合法 ISO 8601 时间") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise EvidenceError(f"{label} 必须包含时区")
    return dt.isoformat(), "datetime"


def _ensure_not_after(value: str | None, observed_at: str, label: str) -> None:
    """Reject evidence timestamps that occur after the observation time."""
    if value is None:
        return
    if datetime.fromisoformat(value) > datetime.fromisoformat(observed_at):
        raise EvidenceError(f"{label} 不得晚于 observed_at")


def _optional_bool_or_text(value: Any, label: str) -> bool | str | None:
    if value is None or isinstance(value, bool):
        return value
    return _text(value, label, maximum=500)


def _local_record_key(profile_url: str, title: str, rank: int) -> str:
    material = f"{profile_url}\0{title}\0{rank}".encode("utf-8")
    return "idx-" + hashlib.sha256(material).hexdigest()[:20]


def _validate_account(raw: Any, *, profile_id: str, observed_at: str, profile_url: str,
                      source_kind: str, source_url: str,
                      snapshot_crawled_at: str | None) -> tuple[dict[str, Any], str]:
    account = _object(raw, "account")
    account_id = _text(account.get("account_id"), "account.account_id", maximum=512)
    if account_id != profile_id:
        raise EvidenceError("account_id 必须与 profile_url 的账号 ID 完全一致")
    account_name = _text(account.get("account_name"), "account.account_name", maximum=200)
    assert account_name is not None
    bio = _text(account.get("bio"), "account.bio", nullable=True, maximum=2000)
    verified = _optional_bool_or_text(account.get("verified"), "account.verified")
    followers = _nonnegative_int(account.get("followers"), "account.followers")
    post_count = _nonnegative_int(account.get("post_count"), "account.post_count")

    raw_metrics = account.get("platform_metrics") or {}
    raw_metrics = _object(raw_metrics, "account.platform_metrics")
    safe_metrics: dict[str, Any] = {}
    for key in ACCOUNT_METRIC_FIELDS:
        value = raw_metrics.get(key)
        if value is None:
            continue
        if key == "douyin_id":
            safe_metrics[key] = _text(value, f"account.platform_metrics.{key}", maximum=200)
        elif key == "total_likes":
            safe_metrics[key] = _nonnegative_int(value, f"account.platform_metrics.{key}", nullable=False)
        else:
            timestamp = _timestamp(
                value, f"account.platform_metrics.{key}", allow_date=True
            )[0]
            _ensure_not_after(timestamp, observed_at, f"account.platform_metrics.{key}")
            safe_metrics[key] = timestamp
    safe_metrics.update({
        "collection_source": source_kind,
        "source_url": source_url,
        "snapshot_crawled_at": snapshot_crawled_at,
    })
    fields = {
        "bio": bio,
        "verified": verified,
        "followers": followers,
        "post_count": post_count,
    }
    profile = {
        "platform": "douyin",
        "account_id": account_id,
        "account_name": account_name,
        "profile_url": profile_url,
        "bio": bio,
        "verified": verified,
        "followers": followers,
        "post_count": post_count,
        "level": None,
        "platform_metrics": safe_metrics,
        "collected_at": observed_at,
        "field_visibility": {
            "account_id": "visible",
            "account_name": "visible",
            "profile_url": "visible",
            **{key: ("visible" if value is not None else "hidden") for key, value in fields.items()},
            "level": "hidden",
        },
    }
    return profile, account_name


def validate_evidence(payload: Any, *, limit: int = 30) -> dict[str, Any]:
    """Validate an evidence object and return whitelisted workspace payloads."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise EvidenceError("limit 必须是 1 到 100 的整数")
    data = _object(payload, "evidence")
    if data.get("schema_version") != 1:
        raise EvidenceError("schema_version 必须为 1")
    if data.get("platform") != "douyin":
        raise EvidenceError("platform 必须为 douyin")

    profile_url = _canonical_url(data.get("profile_url"), "profile_url")
    profile_id = _profile_identity(profile_url)
    source_kind = data.get("source_kind")
    if source_kind not in SOURCE_KINDS:
        raise EvidenceError("source_kind 不受支持")
    source_url = _canonical_url(data.get("source_url"), "source_url")
    if source_kind == "douyin_search_index" and source_url != profile_url:
        raise EvidenceError("source_url 对搜索索引必须等于精确 profile_url")
    if source_kind == "douyin_jingxuan":
        _post_identity(source_url, "source_url")

    observed_at, _ = _timestamp(data.get("observed_at"), "observed_at", allow_date=False)
    assert observed_at is not None
    snapshot_crawled_at, snapshot_precision = _timestamp(
        data.get("snapshot_crawled_at"), "snapshot_crawled_at", nullable=True
    )
    _ensure_not_after(snapshot_crawled_at, observed_at, "snapshot_crawled_at")
    snapshot_age_label = _text(
        data.get("snapshot_age_label"), "snapshot_age_label", nullable=True, maximum=200
    )
    stop_reason = data.get("upstream_stop_reason")
    if stop_reason not in STOP_REASONS:
        raise EvidenceError("upstream_stop_reason 必须是受支持的既有 stop_reason")

    profile, account_name = _validate_account(
        data.get("account"),
        profile_id=profile_id,
        observed_at=observed_at,
        profile_url=profile_url,
        source_kind=source_kind,
        source_url=source_url,
        snapshot_crawled_at=snapshot_crawled_at,
    )

    raw_posts = data.get("posts")
    if not isinstance(raw_posts, list):
        raise EvidenceError("posts 必须是数组")
    if len(raw_posts) == 0:
        raise EmptyEvidenceError("证据中没有可导入作品")
    if len(raw_posts) > 100:
        raise EvidenceError("posts 最多包含 100 条证据")

    posts: list[dict[str, Any]] = []
    safe_posts: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source_rank, raw_item in enumerate(raw_posts, 1):
        item = _object(raw_item, f"posts[{source_rank - 1}]")
        author_name = _text(
            item.get("author_name"), f"posts[{source_rank - 1}].author_name", maximum=200
        )
        if author_name != account_name:
            raise EvidenceError(
                f"posts[{source_rank - 1}].author_name 与目标账号不一致"
            )
        title = _text(item.get("title"), f"posts[{source_rank - 1}].title", maximum=2000)
        assert title is not None
        published_at, published_precision = _timestamp(
            item.get("published_at"),
            f"posts[{source_rank - 1}].published_at",
            nullable=True,
        )
        _ensure_not_after(
            published_at, observed_at, f"posts[{source_rank - 1}].published_at"
        )
        duration = _nonnegative_int(
            item.get("duration_seconds"), f"posts[{source_rank - 1}].duration_seconds"
        )
        metrics = {
            field: _nonnegative_int(
                item.get(field), f"posts[{source_rank - 1}].{field}"
            )
            for field in METRIC_FIELDS
        }
        for unsupported_metric in ("coins", "danmaku"):
            if metrics[unsupported_metric] is not None:
                raise EvidenceError(
                    f"posts[{source_rank - 1}].{unsupported_metric} 对抖音必须为 null"
                )

        if source_kind == "douyin_search_index":
            if published_at is not None:
                raise EvidenceError(
                    f"posts[{source_rank - 1}].published_at 对搜索索引必须为 null"
                )
            if duration is not None:
                raise EvidenceError(
                    f"posts[{source_rank - 1}].duration_seconds 对搜索索引必须为 null"
                )
            for unsupported_metric in ("views", "comments", "favorites", "shares"):
                if metrics[unsupported_metric] is not None:
                    raise EvidenceError(
                        f"posts[{source_rank - 1}].{unsupported_metric} 对搜索索引必须为 null"
                    )

        raw_post_id = item.get("post_id")
        raw_post_url = item.get("post_url")
        if source_kind == "douyin_jingxuan":
            post_id = _text(raw_post_id, f"posts[{source_rank - 1}].post_id", maximum=64)
            assert post_id is not None
            if not post_id.isdigit():
                raise EvidenceError(f"posts[{source_rank - 1}].post_id 必须是数字作品 ID")
            post_url = _canonical_url(raw_post_url, f"posts[{source_rank - 1}].post_url")
            if _post_identity(post_url, f"posts[{source_rank - 1}].post_url") != post_id:
                raise EvidenceError(f"posts[{source_rank - 1}].post_id 与 post_url 不一致")
            dedupe_key = (post_id,)
            item_url_known = True
            platform_post_id_known = True
            local_record_key = False
            content_type = "video" if "/video/" in urlsplit(post_url).path else "image_text"
            record_source_url = post_url
        else:
            if raw_post_id is not None:
                raise EvidenceError(f"posts[{source_rank - 1}].post_id 对搜索索引必须为 null")
            if raw_post_url is not None:
                raise EvidenceError(f"posts[{source_rank - 1}].post_url 对搜索索引必须为 null")
            dedupe_key = (title, published_at, metrics["likes"])
            post_id = _local_record_key(profile_url, title, source_rank)
            post_url = profile_url
            item_url_known = False
            platform_post_id_known = False
            local_record_key = True
            content_type = "other"
            record_source_url = profile_url

        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        platform_metrics = {
            "collection_source": source_kind,
            "platform_post_id_known": platform_post_id_known,
            "local_record_key": local_record_key,
            "item_url_known": item_url_known,
            "source_rank": source_rank,
            "published_at_precision": published_precision,
        }
        post = {
            "platform": "douyin",
            "post_id": post_id,
            "post_url": post_url,
            "published_at": published_at,
            "content_type": content_type,
            "title": title,
            "text": title,
            "duration_seconds": duration,
            "hashtags": [],
            "is_pinned": False,
            "is_repost": False,
            "is_promoted": False,
            "collection_status": "PARTIAL",
            "collected_at": observed_at,
            "source_url": record_source_url,
            "platform_metrics": platform_metrics,
            **metrics,
        }
        safe_post = {
            "post_id": raw_post_id if source_kind == "douyin_search_index" else post_id,
            "post_url": raw_post_url if source_kind == "douyin_search_index" else post_url,
            "author_name": author_name,
            "title": title,
            "published_at": published_at,
            "published_at_precision": published_precision,
            "duration_seconds": duration,
            **metrics,
        }
        posts.append(post)
        safe_posts.append(safe_post)

    if not posts:
        raise EmptyEvidenceError("证据中没有可导入作品")

    # Validate the complete evidence batch before applying the caller's output
    # limit. Otherwise malformed records after the limit could evade checks.
    posts = posts[:limit]
    safe_posts = safe_posts[:limit]

    task = {
        "task_id": None,
        "platform": "douyin",
        "profile_url": profile_url,
        "requested_limit": limit,
        "date_from": None,
        "date_to": None,
        "analysis_goal": None,
        "include_comments": False,
        "task_status": "PARTIAL",
        "stop_reason": stop_reason,
        "collected_count": len(posts),
        "collected_at": observed_at,
        "incremental": False,
        "existing_count": 0,
        "new_count": len(posts),
        "diagnostic_code": DIAGNOSTIC_CODE,
        "collection_source": source_kind,
        "source_kind": source_kind,
        "source_url": source_url,
        "snapshot_crawled_at": snapshot_crawled_at,
        "snapshot_crawled_at_precision": snapshot_precision,
        "snapshot_age_label": snapshot_age_label,
        "evidence_is_exhaustive": False,
    }
    safe_evidence = {
        "schema_version": 1,
        "platform": "douyin",
        "profile_url": profile_url,
        "account": {
            key: profile.get(key)
            for key in ("account_id", "account_name", "bio", "verified", "followers", "post_count")
        },
        "source_kind": source_kind,
        "source_url": source_url,
        "observed_at": observed_at,
        "snapshot_crawled_at": snapshot_crawled_at,
        "snapshot_crawled_at_precision": snapshot_precision,
        "snapshot_age_label": snapshot_age_label,
        "upstream_stop_reason": stop_reason,
        "evidence_is_exhaustive": False,
        "posts": safe_posts,
    }
    return {"profile": profile, "posts": posts, "task": task, "evidence": safe_evidence}


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _markdown_text(value: Any) -> str:
    """Render evidence-derived values as inert Markdown text."""
    text = "" if value is None else str(value)
    text = " ".join(text.replace("\r\n", "\n").replace("\r", "\n").splitlines())
    text = text.replace("\\", "\\\\")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in ("|", "!", "[", "]", "`", "*", "_"):
        text = text.replace(char, "\\" + char)
    return text


def _report_text(result: dict[str, Any]) -> str:
    task = result["task"]
    posts = result["posts"]
    source_kind = task["collection_source"]
    unknown_counts = {
        field: sum(1 for post in posts if post.get(field) is None)
        for field in ("published_at", "views", "likes", "comments", "favorites", "shares")
    }
    lines = [
        "# 抖音索引快照采集质量报告",
        "",
        "> 本任务导入的是公开 Web 索引快照，不是抖音实时完整作品列表。",
        "> 结果仅用于受限环境下的部分分析，不能代表账号后台数据或完整历史。",
        "",
        f"- 账号主页: {task['profile_url']}",
        f"- 证据来源: {source_kind}",
        f"- 证据 URL: {task['source_url']}",
        f"- 观察时间: {task['collected_at']}",
        f"- 索引快照时间: {task['snapshot_crawled_at'] or '未知'}",
        f"- 索引年龄标注: {_markdown_text(task['snapshot_age_label'] or '未知')}",
        f"- 是否穷尽: 否",
        f"- 导入条数: {len(posts)}",
        f"- task_status: {task['task_status']}",
        f"- stop_reason: {task['stop_reason']}",
        f"- diagnostic_code: {task['diagnostic_code']}",
        "",
        "## 未知字段数量",
        "",
    ]
    lines.extend(f"- {field}: {count}/{len(posts)}" for field, count in unknown_counts.items())
    if source_kind == "douyin_search_index":
        lines.extend([
            "",
            "> 搜索索引没有单条平台作品 ID 或详情 URL；`idx-*` 是已披露的本地记录键，",
            "> `post_url`/`source_url` 仅锚定精确账号主页，不能当作单条作品链接。",
        ])
    return "\n".join(lines).rstrip() + "\n"


def run(evidence_path: str, out_dir: str, *, limit: int = 30) -> dict[str, Any]:
    """Validate an evidence JSON file and write a partial task workspace."""
    path = Path(evidence_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"无法读取 evidence JSON: {exc}") from exc

    result = validate_evidence(payload, limit=limit)
    out = Path(out_dir).resolve()
    if out.exists():
        if not out.is_dir():
            raise EvidenceError("输出路径已存在且不是目录")
        try:
            if any(out.iterdir()):
                raise EvidenceError("输出目录非空，拒绝覆盖")
        except OSError as exc:
            raise EvidenceError(f"无法检查输出目录: {exc}") from exc

    source = out / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "index-evidence.json").write_text(_json_text(result["evidence"]), encoding="utf-8")
    (source / "profile.json").write_text(_json_text(result["profile"]), encoding="utf-8")
    posts_text = "".join(json.dumps(post, ensure_ascii=False) + "\n" for post in result["posts"])
    (source / "posts.jsonl").write_text(posts_text, encoding="utf-8")
    (out / "task.json").write_text(_json_text(result["task"]), encoding="utf-8")
    (out / "collection-report.md").write_text(_report_text(result), encoding="utf-8")

    return {
        "task_status": "PARTIAL",
        "stop_reason": result["task"]["stop_reason"],
        "collected_count": len(result["posts"]),
        "collection_source": result["task"]["collection_source"],
        "output_dir": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验并导入抖音公开 Web 索引证据（零第三方运行时依赖）"
    )
    parser.add_argument("--evidence", required=True, help="结构化 evidence JSON")
    parser.add_argument("--out", required=True, help="新的或空的任务输出目录")
    parser.add_argument("--limit", type=int, default=30, help="导入上限（1-100，默认 30）")
    args = parser.parse_args(argv)
    try:
        summary = run(args.evidence, args.out, limit=args.limit)
    except EmptyEvidenceError as exc:
        print(f"[EMPTY] {exc}", file=sys.stderr)
        return 3
    except EvidenceError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
