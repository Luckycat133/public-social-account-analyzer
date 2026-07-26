#!/usr/bin/env python3
# 分析:确定性指标计算 + 模型分类槽位准备
# 对应 references/analysis-rules.md §3 发布节奏 / §4 公开表现指标 / §5 模型分类 / §6 高低表现内容
# 纯 Python + 标准库实现,无模型、无网络、无 LLM。所有计算确定性、可复现。

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from immutable_workspace import WorkspaceError, reject_sealed_workspace
from csv_contract import parse_hashtag_cell, parse_structured_object_cell
from collectors.url_policy import (
    canonical_item_url,
    canonical_profile_url,
    sanitize_routing_url,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 统一指标字段(见 data-schema.md §6)
METRIC_FIELDS = ["views", "likes", "comments", "favorites", "shares", "coins", "danmaku"]
VALID_STATUS = {"SUCCESS", "PARTIAL"}  # 参与默认统计的采集状态(§1)
COLLECTION_STATUS_ORDER = (
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "DELETED",
    "RESTRICTED",
)
COLLECTION_STATUS_CANON = {
    "success": "SUCCESS",
    "ok": "SUCCESS",
    "partial": "PARTIAL",
    "failed": "FAILED",
    "fail": "FAILED",
    "deleted": "DELETED",
    "restricted": "RESTRICTED",
}
# 默认排除的标记(§1)
FLAG_FIELDS = ["is_pinned", "is_repost", "is_promoted"]

# 高低表现分组阈值(§6.3)
MIN_SAMPLE_FOR_HIGH_LOW = 15

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def die(msg: str) -> None:
    """以非零状态退出并打印清晰错误。"""
    print(msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------

def parse_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("null", "none", "nan"):
        return None
    try:
        f = float(s)
    except (ValueError, TypeError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f)


def parse_bool(
    v: Any, default: Optional[bool] = None
) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if v in (0, 0.0):
            return False
        if v in (1, 1.0):
            return True
        return default
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f"):
        return False
    return default


def parse_hashtags(v: Any) -> List[str]:
    return parse_hashtag_cell(v)


def parse_json_object(v: Any) -> Dict[str, Any]:
    """Read a structured CSV cell or in-memory object without sharing state."""
    return parse_structured_object_cell(v)


def parse_collection_status(v: Any) -> Tuple[str, str]:
    """Return a trusted collection status and its provenance."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return "PARTIAL", "inferred_missing"
    status = COLLECTION_STATUS_CANON.get(str(v).strip().lower())
    if status is None:
        return "PARTIAL", "inferred_invalid"
    return status, "declared"


def parse_dt(v: Any) -> Optional[datetime]:
    """解析 ISO 8601 时间;无时区时按平台默认 +08:00 标注(§3)。"""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("null", "none"):
        return None
    s2 = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s2.replace(" ", "T", 1))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt


def format_published_at_for_boundary(post: Dict[str, Any]) -> Optional[str]:
    """Format a sample-boundary timestamp without inventing midnight precision."""
    published_at = post.get("published_at")
    if not isinstance(published_at, datetime):
        return None
    if post.get("published_at_precision") == "date":
        return published_at.date().isoformat()
    return published_at.isoformat()


def percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    """线性插值分位数(numpy 默认行为),确定性强,兼容 Python 3.9+。"""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    rank = p * (n - 1)
    lo = math.floor(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def rnd(x: Any, nd: int = 6) -> Any:
    if x is None:
        return None
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return round(x, nd)
    return x


# ---------------------------------------------------------------------------
# 加载输入
# ---------------------------------------------------------------------------

def load_profile(task_dir: str) -> Dict[str, Any]:
    p = os.path.join(task_dir, "source", "profile.json")
    if not os.path.exists(p):
        die(f"ERROR: 缺少必要输入文件: {p}")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        die(f"ERROR: 解析 profile.json 失败: {p} ({e})")


def load_posts(task_dir: str) -> List[Dict[str, Any]]:
    p = os.path.join(task_dir, "normalized-posts.csv")
    if not os.path.exists(p):
        die(f"ERROR: 缺少必要输入文件: {p}")
    rows: List[Dict[str, Any]] = []
    try:
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except (OSError, csv.Error) as e:
        die(f"ERROR: 读取 normalized-posts.csv 失败: {p} ({e})")
    return rows


def build_posts(raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将 CSV 行映射为统一 Post 结构(见 data-schema.md §5 / §6)。"""
    posts: List[Dict[str, Any]] = []
    for row in raw_rows:
        collection_status, derived_status_source = parse_collection_status(
            row.get("collection_status")
        )
        supplied_status_source = row.get("collection_status_source")
        if (
            derived_status_source == "declared"
            and (
                supplied_status_source == "declared"
                or (
                    collection_status == "PARTIAL"
                    and supplied_status_source
                    in {"inferred_missing", "inferred_invalid"}
                )
            )
        ):
            collection_status_source = supplied_status_source
        else:
            collection_status_source = derived_status_source
        post: Dict[str, Any] = {
            "platform": row.get("platform"),
            "post_id": row.get("post_id"),
            "post_url": row.get("post_url"),
            "published_at": parse_dt(row.get("published_at")),
            "content_type": row.get("content_type") or "other",
            "title": row.get("title") or None,
            "text": row.get("text") or None,
            "duration_seconds": parse_int(row.get("duration_seconds")),
            "hashtags": parse_hashtags(row.get("hashtags")),
            "is_pinned": parse_bool(row.get("is_pinned")),
            "is_repost": parse_bool(row.get("is_repost")),
            "is_promoted": parse_bool(row.get("is_promoted")),
            "collection_status": collection_status,
            "collection_status_source": collection_status_source,
            "collected_at": row.get("collected_at") or None,
            "source_url": row.get("source_url") or row.get("post_url"),
            "collection_source": row.get("collection_source") or None,
            "platform_post_id_known": parse_bool(
                row.get("platform_post_id_known"), default=bool(row.get("post_id"))
            ),
            "local_record_key": parse_bool(
                row.get("local_record_key"), default=False
            ),
            "item_url_known": parse_bool(
                row.get("item_url_known"), default=bool(row.get("post_url"))
            ),
            "source_rank": parse_int(row.get("source_rank")),
            "published_at_precision": (
                row.get("published_at_precision")
                if row.get("published_at_precision") in ("datetime", "date", "unknown")
                else ("datetime" if parse_dt(row.get("published_at")) else "unknown")
            ),
            "platform_metrics": parse_json_object(row.get("platform_metrics")),
            "field_visibility": parse_json_object(row.get("field_visibility")),
        }
        for m in METRIC_FIELDS:
            post[m] = parse_int(row.get(m))
        posts.append(post)
    return posts


# ---------------------------------------------------------------------------
# 采样拆分(§1 分析前置条件)
# ---------------------------------------------------------------------------

def split_samples(all_posts: List[Dict[str, Any]]) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict], List[Dict]]:
    valid = [
        p for p in all_posts
        if p["collection_status"] in VALID_STATUS
        and not (p["is_pinned"] or p["is_repost"] or p["is_promoted"])
    ]
    flagged = [
        p for p in all_posts
        if (p["is_pinned"] or p["is_repost"] or p["is_promoted"])
        and p["collection_status"] not in ("FAILED", "DELETED", "RESTRICTED")
    ]
    missing = [p for p in all_posts if p["collection_status"] in ("FAILED", "DELETED")]
    restricted = [p for p in all_posts if p["collection_status"] == "RESTRICTED"]
    return all_posts, valid, flagged, missing, restricted


def collection_status_counts(all_posts: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count every collected row before flag-based analysis exclusions."""
    counts = {status: 0 for status in COLLECTION_STATUS_ORDER}
    for post in all_posts:
        status = post.get("collection_status")
        if status in counts:
            counts[status] += 1
    return counts


# ---------------------------------------------------------------------------
# §3 发布节奏
# ---------------------------------------------------------------------------

def compute_cadence(valid: List[Dict[str, Any]]) -> Dict[str, Any]:
    dates = [p["published_at"] for p in valid if p["published_at"] is not None]
    total = len(valid)
    date_only_count = sum(
        1 for p in valid
        if p.get("published_at") is not None and p.get("published_at_precision") == "date"
    )
    datetime_count = sum(
        1 for p in valid
        if p.get("published_at") is not None and p.get("published_at_precision") == "datetime"
    )

    if not dates:
        return {
            "total_posts": total,
            "coverage_days": 0,
            "coverage_weeks": 0,
            "weekly_avg": None,
            "median_interval_hours": None,
            "longest_gap_hours": None,
            "weekday_distribution": {str(i): 0 for i in range(7)},
            "hour_distribution": {str(i): 0 for i in range(24)},
            "weekday_weekend": {
                "weekday_count": 0,
                "weekend_count": 0,
                "weekday_pct": None,
                "weekend_pct": None,
            },
            "monthly_distribution": {},
            "seasonal_intensity": None,
            "break_month_share": None,
            "seasonal_note": "有效内容均无 published_at,无法计算季节性/学期指标",
            "interval_unit": "hours",
            "time_precision": {
                "datetime": 0,
                "date_only": 0,
                "unknown": total,
            },
            "note": "有效内容均无 published_at,无法计算基于时间的节奏指标",
        }

    min_d, max_d = min(dates), max(dates)
    span_days = (max_d - min_d).days
    coverage_weeks = max(math.ceil(span_days / 7), 1)  # 覆盖周数不小于 1
    coverage_days = len({(d.year, d.month, d.day) for d in dates})
    weekly_avg = len(dates) / coverage_weeks if coverage_weeks else None

    sorted_dates = sorted(dates)
    gaps: List[float] = []
    for i in range(1, len(sorted_dates)):
        gaps.append((sorted_dates[i] - sorted_dates[i - 1]).total_seconds() / 3600.0)
    median_gap = percentile(sorted(gaps), 0.5) if gaps else None
    longest_gap = max(gaps) if gaps else None
    if date_only_count:
        # 日期级证据只能支持日期/星期/月度节奏，不能声称精确到小时的发布间隔。
        median_gap = None
        longest_gap = None

    # 星期 / 小时分布:使用帖子自身时区的墙上时间(无时区按 +08:00,见 parse_dt)
    wd = {str(i): 0 for i in range(7)}
    for d in dates:
        wd[str(d.weekday())] += 1
    hr = {str(i): 0 for i in range(24)}
    for p in valid:
        d = p.get("published_at")
        if d is not None and p.get("published_at_precision") == "datetime":
            hr[str(d.hour)] += 1

    wd_count = sum(v for k, v in wd.items() if int(k) < 5)
    we_count = sum(v for k, v in wd.items() if int(k) >= 5)
    tot = wd_count + we_count

    # 月度分布与季节性/学期检测（§3 扩展，确定性启发式，非因果）
    monthly: Dict[str, int] = {}
    if dates:
        curr_y, curr_m = min_d.year, min_d.month
        end_y, end_m = max_d.year, max_d.month
        while (curr_y < end_y) or (curr_y == end_y and curr_m <= end_m):
            monthly[f"{curr_y}-{curr_m:02d}"] = 0
            curr_m += 1
            if curr_m > 12:
                curr_m = 1
                curr_y += 1
        for d in dates:
            key = f"{d.year}-{d.month:02d}"
            monthly[key] = monthly.get(key, 0) + 1
    monthly_distribution = dict(sorted(monthly.items()))

    month_counts = list(monthly_distribution.values())
    seasonal_intensity = None
    if len(month_counts) >= 2:
        mean_m = sum(month_counts) / len(month_counts)
        if mean_m > 0:
            var = sum((x - mean_m) ** 2 for x in month_counts) / len(month_counts)
            seasonal_intensity = rnd(math.sqrt(var) / mean_m, 4)
    # 寒暑假窗口（1/2/7/8 月）发布占比
    break_months = (1, 2, 7, 8)
    break_count = sum(v for k, v in monthly_distribution.items()
                     if int(k.split("-")[1]) in break_months)
    valid_dates_count = len(dates)
    break_month_share = rnd(break_count / valid_dates_count, 4) if valid_dates_count else None
    if seasonal_intensity is None:
        seasonal_note = None
    elif seasonal_intensity >= 1.0:
        seasonal_note = "发布高度集中于少数月份（季节性/断更脉冲明显），节奏结论需谨慎。"
    elif seasonal_intensity >= 0.5:
        seasonal_note = "发布存在中等季节性波动。"
    else:
        seasonal_note = "发布在各月分布较均匀，季节性不明显。"

    return {
        "total_posts": total,
        "coverage_days": coverage_days,
        "coverage_weeks": coverage_weeks,
        "weekly_avg": rnd(weekly_avg, 4),
        "median_interval_hours": rnd(median_gap, 2),
        "longest_gap_hours": rnd(longest_gap, 2),
        "weekday_distribution": wd,
        "hour_distribution": hr,
        "weekday_weekend": {
            "weekday_count": wd_count,
            "weekend_count": we_count,
            "weekday_pct": rnd(wd_count / tot, 4) if tot else None,
            "weekend_pct": rnd(we_count / tot, 4) if tot else None,
        },
        "monthly_distribution": monthly_distribution,
        "seasonal_intensity": seasonal_intensity,
        "break_month_share": break_month_share,
        "seasonal_note": seasonal_note,
        "interval_unit": "hours",
        "time_precision": {
            "datetime": datetime_count,
            "date_only": date_only_count,
            "unknown": total - len(dates),
        },
        "note": (
            f"{date_only_count} 条仅有日期精度，未计入具体时段分布。"
            if date_only_count
            else None
        ),
    }


def restrict_nonexhaustive_index_cadence(cadence: Dict[str, Any]) -> Dict[str, Any]:
    """Keep sample date counts while suppressing account-level cadence claims."""
    restricted = dict(cadence)
    for field in (
        "weekly_avg",
        "median_interval_hours",
        "longest_gap_hours",
        "seasonal_intensity",
        "break_month_share",
        "seasonal_note",
    ):
        restricted[field] = None
    restricted["cadence_inference_allowed"] = False
    boundary_note = (
        "当前为非穷尽索引样本，仅展示可见作品的日期分布；不计算账号周均发布量、"
        "发布间隔、断更、季节性或排播建议。"
    )
    previous_note = restricted.get("note")
    restricted["note"] = (
        f"{previous_note} {boundary_note}" if previous_note else boundary_note
    )
    return restricted


# ---------------------------------------------------------------------------
# §4 公开表现指标
# ---------------------------------------------------------------------------

def metric_stats(values_nonnull: List[float], valid_count: int) -> Dict[str, Any]:
    n = len(values_nonnull)
    missing_rate = (valid_count - n) / valid_count if valid_count else None
    if n == 0:
        return {
            "count": 0,
            "median": None,
            "p25": None,
            "p75": None,
            "iqr": None,
            "dispersion_ratio": None,
            "minimum": None,
            "maximum": None,
            "missing_rate": (1.0 if valid_count else None),
        }
    s = sorted(values_nonnull)
    median = percentile(s, 0.5)
    p25 = percentile(s, 0.25)
    p75 = percentile(s, 0.75)
    iqr = (p75 - p25) if (p75 is not None and p25 is not None) else None
    dispersion_ratio = (rnd(iqr / median, 4)
                        if (median not in (None, 0) and iqr is not None) else None)
    return {
        "count": n,
        "median": rnd(median, 4),
        "p25": rnd(p25, 4),
        "p75": rnd(p75, 4),
        "iqr": rnd(iqr, 4) if iqr is not None else None,
        "dispersion_ratio": dispersion_ratio,
        "minimum": s[0],
        "maximum": s[-1],
        "missing_rate": rnd(missing_rate, 6),
    }


def compute_metric_summary(valid: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
    fv = profile.get("field_visibility") or {}
    summary: Dict[str, Any] = {}
    valid_count = len(valid)
    for m in METRIC_FIELDS:
        vals = [float(p[m]) for p in valid if p[m] is not None]
        st = metric_stats(vals, valid_count)
        # visible:field_visibility 标注 visible/partial/public(向下兼容),或实际存在非 null 值
        st["visible"] = bool(fv.get(m) in ("visible", "partial", "public") or len(vals) > 0)
        summary[m] = st
    return summary


def compute_medians(valid: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    medians: Dict[str, Optional[float]] = {}
    for m in METRIC_FIELDS:
        vals = [float(p[m]) for p in valid if p[m] is not None]
        medians[m] = percentile(sorted(vals), 0.5) if vals else None
    return medians


# ---------------------------------------------------------------------------
# 互动率(§4 分母透明)
# ---------------------------------------------------------------------------

def _is_search_index_post(p: Dict[str, Any]) -> bool:
    return p.get("collection_source") == "douyin_search_index"


def engagement_numerator(p: Dict[str, Any]) -> Optional[float]:
    # 分子固定 = likes + comments + favorites + shares;
    # 至少一个组件可见时，其他 null 组件按 0 计入（如微博 favorites 不提供）；
    # 四个组件全未知时必须保持 null，不能把“完全不可见”伪装成真实 0。
    values = [p.get("likes"), p.get("comments"), p.get("favorites"), p.get("shares")]
    if all(value is None for value in values):
        return None
    return sum(value or 0 for value in values)


def view_based_rate(p: Dict[str, Any]) -> Optional[float]:
    if _is_search_index_post(p):
        return None
    v = p["views"]
    if v is None or v == 0:
        return None
    numerator = engagement_numerator(p)
    return None if numerator is None else numerator / v


def follower_based_ratio(p: Dict[str, Any], followers: Optional[int]) -> Optional[float]:
    if _is_search_index_post(p):
        return None
    if followers is None or followers == 0:
        return None
    numerator = engagement_numerator(p)
    return None if numerator is None else numerator / followers


def deep_approval_rate(p: Dict[str, Any]) -> Optional[float]:
    """四分法·深度认可率 = (coins + favorites) / views（§4 扩展，混合口径）。

    分母 views 为 null/0 时该条置 null（分母透明，禁止用 0 做分母）。
    coins/favorites 全部未知时返回 null；至少一项有证据时，另一项 null 按 0 计。
    """
    if _is_search_index_post(p):
        return None
    views = p["views"]
    if views is None or views == 0:
        return None
    if p.get("coins") is None and p.get("favorites") is None:
        return None
    coins = p.get("coins") or 0
    favorites = p.get("favorites") or 0
    return (coins + favorites) / views


def community_discussion_rate(p: Dict[str, Any]) -> Optional[float]:
    """四分法·社群讨论率 = (comments + danmaku) / views（§4 扩展）。

    分母 views 为 null/0 时该条置 null（分母透明）。
    comments/danmaku 全部未知时返回 null；至少一项有证据时，另一项 null 按 0 计。
    """
    if _is_search_index_post(p):
        return None
    views = p["views"]
    if views is None or views == 0:
        return None
    if p.get("comments") is None and p.get("danmaku") is None:
        return None
    comments = p.get("comments") or 0
    danmaku = p.get("danmaku") or 0
    return (comments + danmaku) / views


def compute_engagement(valid: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
    followers = parse_int(profile.get("followers"))
    vb: List[float] = []
    fb: List[float] = []
    deep: List[float] = []
    disc: List[float] = []
    for p in valid:
        r = view_based_rate(p)
        if r is not None:
            vb.append(r)
        fr = follower_based_ratio(p, followers)
        if fr is not None:
            fb.append(fr)
        dr = deep_approval_rate(p)
        if dr is not None:
            deep.append(dr)
        cr = community_discussion_rate(p)
        if cr is not None:
            disc.append(cr)
    valid_count = len(valid)
    return {
        "view_based_engagement_rate": metric_stats(vb, valid_count),
        "follower_based_engagement_ratio": metric_stats(fb, valid_count),
        "deep_approval_rate": metric_stats(deep, valid_count),
        "community_discussion_rate": metric_stats(disc, valid_count),
        "followers": followers,
        "denominator_note": (
            "四分法互动率，分母各自透明、禁止混用(§4):"
            "view_based 以 views 为分母=(likes+comments+favorites+shares)/views;"
            "follower_based 以 followers 为分母=(likes+comments+favorites+shares)/followers;"
            "deep_approval_rate 以 views 为分母=(coins+favorites)/views;"
            "community_discussion_rate 以 views 为分母=(comments+danmaku)/views。"
            "所有比率的对应分子全部为 null 时比率为 null；"
            "至少一项已知时其余 null 按 0 计入。"
            "统一互动率分子 = likes+comments+favorites+shares;coins/danmaku 不并入统一互动率。"
        ),
    }


# ---------------------------------------------------------------------------
# §6 高低表现内容
# ---------------------------------------------------------------------------

def post_metric_value(p: Dict[str, Any], metric: str) -> Optional[float]:
    if metric == "views":
        return p["views"]
    if metric == "engagement_sum":
        if _is_search_index_post(p):
            return None
        return engagement_numerator(p)
    if metric == "view_based_engagement_rate":
        return view_based_rate(p)
    if metric in METRIC_FIELDS:
        return p[metric]
    return None


def choose_main_metric(analysis_goal: Optional[str], valid: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """§6.1 主排序指标选择。

    规则:
    - `analysis_goal` 未指定或无法确定 -> 默认 `view_based_engagement_rate`(§6.1 权威默认)。
    - goal 含 认知/awareness/曝光/播放/浏览 -> `views`;
      含 互动/engagement -> `engagement_sum`(=likes+comments+favorites+shares,§4 可见计算字段)。
    - 安全约束(§6.1):主排序指标须为已成功计算的可见指标,禁止使用 null 充斥的字段排序。
      当选定指标不可用(全 null)时,按 `view_based_engagement_rate` / `engagement_sum` / `views`
      优先级回退到下一个可用可见指标;若全部不可用于,返回原指标并返回跳过提示。

    返回: (主排序指标, 回退/跳过说明 note 或 None)
    """
    if valid and all(_is_search_index_post(p) for p in valid):
        if any(p.get("likes") is not None for p in valid):
            return (
                "likes",
                "搜索索引只确认了卡片可见点赞数；不把缺失的评论/收藏/分享推算为总互动。",
            )
        return (
            "likes",
            "搜索索引没有可用于高低表现比较的公开指标，保持 likes 为空并跳过该模块。",
        )

    goal = (analysis_goal or "").lower()
    if any(k in goal for k in ["互动", "engagement", "interact"]):
        metric = "engagement_sum"
    elif any(k in goal for k in ["awareness", "认知", "曝光", "播放", "浏览", "views", "play", "reach"]):
        metric = "views"
    else:
        metric = "view_based_engagement_rate"  # §6.1 默认

    def usable(m: str) -> bool:
        return any(post_metric_value(p, m) is not None for p in valid)

    if usable(metric):
        return metric, None

    # 选定指标不可用(全 null),按 §6.1 安全约束回退到下一个可用可见指标
    for cand in ("view_based_engagement_rate", "engagement_sum", "views"):
        if cand != metric and usable(cand):
            return cand, f"指定指标 {metric} 全为 null,已回退至 {cand}"
    # 全部不可用:保留原指标,由调用方跳过高低表现并标注
    return metric, (f"指定指标 {metric} 及所有回退指标均不可用,跳过高低表现")


def _measured_metric_items(
    valid: List[Dict[str, Any]], main_metric: str
) -> List[Tuple[Dict[str, Any], float]]:
    return [
        (post, value)
        for post, value in (
            (post, post_metric_value(post, main_metric)) for post in valid
        )
        if value is not None
    ]


def _main_metric_median(
    measured_items: List[Tuple[Dict[str, Any], float]],
) -> Optional[float]:
    values = sorted(float(value) for _, value in measured_items)
    return percentile(values, 0.5) if values else None


def _high_low_sort_key(
    item: Tuple[Dict[str, Any], float],
) -> Tuple[float, int, int, str, str]:
    post, value = item
    source_rank = post.get("source_rank")
    has_valid_source_rank = (
        isinstance(source_rank, int)
        and not isinstance(source_rank, bool)
        and source_rank >= 1
    )
    return (
        -float(value),
        0 if has_valid_source_rank else 1,
        source_rank if has_valid_source_rank else 0,
        str(post.get("post_id") or ""),
        str(post.get("platform") or ""),
    )


def _canonical_jingxuan_item_url(
    value: Any, expected_post_id: Any
) -> Optional[str]:
    """Validate the official Jingxuan item shape without widening Douyin URLs."""
    expected = str(expected_post_id or "").strip()
    if not expected.isdigit():
        return None
    safe_url = sanitize_routing_url(value)
    if safe_url is None:
        return None
    parsed = urlsplit(safe_url)
    if parsed.hostname != "jingxuan.douyin.com":
        return None
    segments = parsed.path.strip("/").split("/")
    if segments != ["m", "video", expected]:
        return None
    return f"https://jingxuan.douyin.com/m/video/{expected}"


def _canonical_post_evidence_url(p: Dict[str, Any]) -> Optional[str]:
    item_url_known = p.get("item_url_known", bool(p.get("post_url")))
    if item_url_known is not True:
        return None
    candidate = p.get("post_url")
    if p.get("collection_source") == "douyin_jingxuan":
        if p.get("platform") != "douyin":
            return None
        return _canonical_jingxuan_item_url(candidate, p.get("post_id"))
    platform = p.get("platform")
    if not isinstance(platform, str) or not platform:
        return None
    return canonical_item_url(platform, candidate, p.get("post_id"))


def _is_coherent_search_index_record(p: Dict[str, Any]) -> bool:
    return (
        p.get("platform") == "douyin"
        and p.get("collection_source") == "douyin_search_index"
        and p.get("item_url_known") is False
        and p.get("platform_post_id_known") is False
        and p.get("local_record_key") is True
    )


def _resolve_post_evidence(p: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical item evidence or the frozen search-index exception."""
    source_url = p.get("source_url") or p.get("post_url")
    item_url = _canonical_post_evidence_url(p)
    if item_url is not None:
        return {
            "post_url": item_url,
            "evidence_url": item_url,
            "source_url": source_url,
            "item_url_known": True,
            "url_kind": "item",
        }
    if _is_coherent_search_index_record(p):
        profile_anchor = canonical_profile_url("douyin", source_url)
        if profile_anchor is not None:
            return {
                "post_url": None,
                "evidence_url": profile_anchor,
                "source_url": source_url,
                "item_url_known": False,
                "url_kind": "profile_index",
            }
    return {
        "post_url": None,
        "evidence_url": None,
        "source_url": source_url,
        "item_url_known": False,
        "url_kind": "missing",
    }


def _has_auditable_collection_time(value: Any) -> bool:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _item_has_complete_evidence(item: Dict[str, Any]) -> bool:
    return (
        item.get("url_kind") == "item"
        and item.get("item_url_known") is True
        and isinstance(item.get("post_url"), str)
        and item.get("post_url") == item.get("evidence_url")
        and _has_auditable_collection_time(item.get("collected_at"))
        and isinstance(item.get("metrics"), dict)
        and item.get("value") is not None
        and isinstance(item.get("main_metric"), str)
    )


def _empty_evidence_coverage() -> Dict[str, Any]:
    return {
        "selected_count": 0,
        "complete_count": 0,
        "missing_count": 0,
        "missing_post_ids": [],
        "rate": None,
        "status": "COMPLETE",
    }


def _evidence_coverage(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return _empty_evidence_coverage()
    missing = [item for item in items if not _item_has_complete_evidence(item)]
    complete_count = len(items) - len(missing)
    return {
        "selected_count": len(items),
        "complete_count": complete_count,
        "missing_count": len(missing),
        "missing_post_ids": [item.get("post_id") for item in missing],
        "rate": rnd(complete_count / len(items), 4),
        "status": "PARTIAL_EVIDENCE" if missing else "COMPLETE",
    }


def _core_insight(
    insight_id: str,
    kind: str,
    label: str,
    main_metric: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    evidence = [
        {
            "post_id": item.get("post_id"),
            "url": item.get("evidence_url"),
            "url_kind": item.get("url_kind"),
            "collected_at": item.get("collected_at"),
            "metrics": copy.deepcopy(item.get("metrics") or {}),
            "rank": item.get("rank"),
            "value": item.get("value"),
        }
        for item in items
    ]
    return {
        "id": insight_id,
        "kind": kind,
        "statement": (
            f"样本中主指标 {main_metric} 的{label}组包含 {len(items)} 条被选记录。"
        ),
        "main_metric": main_metric,
        "evidence": evidence,
    }


def compute_high_low(valid: List[Dict[str, Any]], main_metric: str) -> Optional[Dict[str, Any]]:
    measured_items = _measured_metric_items(valid, main_metric)
    n_meas = len(measured_items)
    if n_meas < MIN_SAMPLE_FOR_HIGH_LOW:
        return None  # 标记 INSUFFICIENT_SAMPLE

    main_metric_median = _main_metric_median(measured_items)

    items_sorted = sorted(measured_items, key=_high_low_sort_key)

    k = math.ceil(n_meas * 0.2)
    if k < 3:
        k = 3  # 每组至少 3 条(§6.2)
    if k > n_meas // 2:
        k = n_meas // 2

    high = items_sorted[:k]
    low = items_sorted[-k:]

    def to_item(t: Tuple[Dict, Optional[float]], rank: int) -> Dict[str, Any]:
        p, v = t
        evidence = _resolve_post_evidence(p)
        published_at = p.get("published_at")
        if isinstance(published_at, datetime):
            published_at = published_at.isoformat()
        relative_to_main_median = (
            None
            if main_metric_median in (None, 0)
            else rnd(float(v) / main_metric_median, 4)
        )
        return {
            "platform": p.get("platform"),
            "post_id": p["post_id"],
            "title": p.get("title"),
            "post_url": evidence["post_url"],
            "evidence_url": evidence["evidence_url"],
            "source_url": evidence["source_url"],
            "published_at": published_at,
            "published_at_precision": p.get("published_at_precision", "unknown"),
            "collection_status": p.get("collection_status"),
            "collection_status_source": p.get("collection_status_source"),
            "collected_at": p.get("collected_at"),
            "collection_source": p.get("collection_source"),
            "platform_post_id_known": p.get(
                "platform_post_id_known", bool(p.get("post_id"))
            ),
            "local_record_key": p.get("local_record_key", False),
            "item_url_known": evidence["item_url_known"],
            "source_rank": p.get("source_rank"),
            "metrics": {metric: p.get(metric) for metric in METRIC_FIELDS},
            "value": rnd(v, 6) if v is not None else None,
            "rank": rank,
            "reason": f"主指标 {main_metric} = {rnd(v, 6) if v is not None else 'null'}",
            "relative_to_main_median": relative_to_main_median,
            "duration_seconds": p.get("duration_seconds"),
            "hashtags": list(p.get("hashtags") or []),
            "content_type": p.get("content_type"),
            "is_pinned": p.get("is_pinned"),
            "is_repost": p.get("is_repost"),
            "is_promoted": p.get("is_promoted"),
            "platform_metrics": copy.deepcopy(p.get("platform_metrics") or {}),
            "field_visibility": copy.deepcopy(p.get("field_visibility") or {}),
            "main_metric": main_metric,
            "url_kind": evidence["url_kind"],
        }

    high_items = [to_item(t, i + 1) for i, t in enumerate(high)]
    low_items = [to_item(t, n_meas - k + i + 1) for i, t in enumerate(low)]
    selected_items = high_items + low_items
    return {
        "high": high_items,
        "low": low_items,
        "group_size": k,
        "measured_count": n_meas,
        "main_metric_median": main_metric_median,
        "main_metric": main_metric,
        "note": "高低表现仅描述样本中的相关特征,不构成因果结论(§6.4)",
        "evidence_coverage": _evidence_coverage(selected_items),
        "core_insights": [
            _core_insight(
                "performance-high",
                "high_performance",
                "高表现",
                main_metric,
                high_items,
            ),
            _core_insight(
                "performance-low",
                "low_performance",
                "低表现",
                main_metric,
                low_items,
            ),
        ],
    }


# ---------------------------------------------------------------------------
# §5 模型分类槽位准备(仅结构,运行时由模型填充)
# ---------------------------------------------------------------------------

def build_post_records(
    valid: List[Dict[str, Any]],
    medians: Dict[str, Optional[float]],
    followers: Optional[int],
) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    for p in valid:
        rel: Dict[str, Any] = {}
        for m in METRIC_FIELDS:
            med = medians[m]
            if med is None or med == 0:
                rel[m] = None  # 禁止用 0 做分母(§4)
            else:
                rel[m] = rnd(p[m] / med, 4) if p[m] is not None else None
        evidence = _resolve_post_evidence(p)
        recs.append({
            "platform": p.get("platform"),
            "post_id": p["post_id"],
            "post_url": evidence["post_url"],
            "evidence_url": evidence["evidence_url"],
            "source_url": evidence["source_url"],
            "title": p.get("title"),
            "text": p.get("text"),
            "content_type": p.get("content_type"),
            "duration_seconds": p.get("duration_seconds"),
            "hashtags": list(p.get("hashtags") or []),
            "is_pinned": p.get("is_pinned"),
            "is_repost": p.get("is_repost"),
            "is_promoted": p.get("is_promoted"),
            "collection_status": p.get("collection_status"),
            "collection_status_source": p.get("collection_status_source"),
            "collected_at": p.get("collected_at"),
            "platform_metrics": copy.deepcopy(p.get("platform_metrics") or {}),
            "field_visibility": copy.deepcopy(p.get("field_visibility") or {}),
            "published_at": p["published_at"].isoformat() if p["published_at"] else None,
            "published_at_precision": p.get("published_at_precision", "unknown"),
            "collection_source": p.get("collection_source"),
            "platform_post_id_known": p.get(
                "platform_post_id_known", bool(p.get("post_id"))
            ),
            "local_record_key": p.get("local_record_key", False),
            "item_url_known": evidence["item_url_known"],
            "url_kind": evidence["url_kind"],
            "source_rank": p.get("source_rank"),
            "metrics": {m: p[m] for m in METRIC_FIELDS},
            "relative_performance": rel,
            "view_based_engagement_rate": rnd(view_based_rate(p), 6),
            "follower_based_engagement_ratio": rnd(follower_based_ratio(p, followers), 6),
            # —— 以下为模型分类槽位(§5),本脚本仅准备结构 ——
            "topic": None,
            "format": None,
            "funnel_stage": None,
            "hook_type": None,
            "series_name": None,
            "is_original": None,
            "has_product_placement": None,
            "analysis_labels": [],
            "classification_confidence": None,
            "classification_version": None,
        })
    return recs


# ---------------------------------------------------------------------------
# §5 LLM 协同分类（确定性计算 + LLM 语义标注 标准接口）
# ---------------------------------------------------------------------------

_TAX_FORMAT = {"talking_head", "tutorial", "commentary", "interview", "vlog", "news",
               "review", "compilation", "image_text", "live_clip", "other"}
_TAX_FUNNEL = {"awareness", "education", "engagement", "conversion", "retention", "unknown"}
_TAX_HOOK = {"question", "contradiction", "result_first", "pain_point", "controversy",
             "list", "curiosity", "authority", "story", "none", "unknown"}
_CLASSIFICATION_REQUIRED_FIELDS = frozenset(
    {
        "post_id",
        "topic",
        "format",
        "funnel_stage",
        "hook_type",
        "series_name",
        "is_original",
        "has_product_placement",
        "analysis_labels",
        "classification_confidence",
    }
)
_CLASSIFICATION_OPTIONAL_FIELDS = frozenset({"classification_version"})


def classification_contract(
    post_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize taxonomy lifecycle without conflating state and version."""
    total_count = len(post_records)
    classified_count = sum(
        record.get("classification_version") == "llm-1"
        for record in post_records
    )
    pending_count = total_count - classified_count
    if classified_count == 0:
        status = "pending-model"
        version = None
    elif classified_count == total_count:
        status = "completed"
        version = "llm-1"
    else:
        status = "partial-model"
        version = "llm-1"
    return {
        "classification_status": status,
        "classification_version": version,
        "classification_coverage": {
            "total_count": total_count,
            "classified_count": classified_count,
            "pending_count": pending_count,
            "rate": (
                None
                if total_count == 0
                else rnd(classified_count / total_count, 4)
            ),
        },
    }


def build_taxonomy_prompt(valid: List[Dict[str, Any]], followers: Optional[int]) -> str:
    """生成供 LLM 填充分类槽位的 Prompt 模版。

    确定性指标（播放/互动率/中位数/高低表现）已由本脚本计算，此模版仅做语义标注，
    要求 LLM 输出每条内容的 topic/format/funnel_stage/hook_type 等分类，不修改任何数字。
    返回 markdown 字符串，调用方写入 taxonomy-prompt.md 并交给外部 LLM。
    """
    lines = [
        "# 公开社媒内容分类标注任务（LLM 语义标注）",
        "",
        "> 本任务**仅做语义分类标注**。所有确定性指标（播放/互动率/中位数/高低表现）已由分析脚本计算，",
        "> 请勿修改、也无需输出这些数字。仅按枚举为每条内容填充分类槽位。",
        "",
        "## 可取值枚举（verbatim，超出范围一律取 unknown/other/none）",
        "- topic: 2–10 个汉字的主题名；无法判断写 `unknown`；相似语义须复用同一主题名。",
        "- format: " + ", ".join(sorted(_TAX_FORMAT)),
        "- funnel_stage: " + ", ".join(sorted(_TAX_FUNNEL)),
        "- hook_type: " + ", ".join(sorted(_TAX_HOOK)),
        "- series_name: 栏目/合集名（可空）；is_original: true/false/null；",
        "  has_product_placement: true/false/null；analysis_labels: 字符串数组。",
        "",
        "## 输出格式（严格 JSON 数组）",
        "```json",
        '[{"post_id": "<id>", "topic": "...", "format": "...", "funnel_stage": "...",',
        '  "hook_type": "...", "series_name": null, "is_original": null,',
        '  "has_product_placement": null, "analysis_labels": [], "classification_confidence": 0.0}]',
        "```",
        "",
        f"> 账号粉丝数（仅参考，不作为分类依据）：{followers}",
        "",
        "## 待标注内容（仅提供标题/正文/标签，供语义判断）",
        "",
    ]
    for p in valid:
        title = p.get("title") or ""
        text = (p.get("text") or "")[:200]
        tags = p.get("hashtags") or []
        lines.append(f"- post_id={p.get('post_id')} | 标题：{title} | 标签：{', '.join(tags)}")
        if text:
            lines.append(f"  正文(截断)：{text}")
    return "\n".join(lines)


def apply_taxonomy(post_records: List[Dict[str, Any]], results) -> List[Dict[str, Any]]:
    """将 LLM 返回的分类结果回填进 post_records。

    results 可为 dict[post_id -> 字段] 或 list[dict]。枚举值越界时回退到
    unknown/other/none（§5 一致性，绝不臆造新枚举值）。
    """
    if isinstance(results, list):
        results = {r.get("post_id"): r for r in results if isinstance(r, dict)}
    by_id = {r.get("post_id"): r for r in post_records}
    for pid, r in results.items():
        rec = by_id.get(pid)
        if not rec or not isinstance(r, dict):
            continue
        rec["topic"] = r.get("topic") or None
        rec["format"] = r.get("format") if r.get("format") in _TAX_FORMAT else "other"
        rec["funnel_stage"] = r.get("funnel_stage") if r.get("funnel_stage") in _TAX_FUNNEL else "unknown"
        rec["hook_type"] = r.get("hook_type") if r.get("hook_type") in _TAX_HOOK else "unknown"
        for k in ("series_name", "is_original", "has_product_placement", "analysis_labels"):
            if k in r:
                rec[k] = r[k]
        if "classification_confidence" in r:
            rec["classification_confidence"] = r["classification_confidence"]
        rec["classification_version"] = r.get("classification_version") or "llm-1"
    return post_records


def validate_classification_results(
    post_records: List[Dict[str, Any]], results: Any
) -> List[Dict[str, Any]]:
    """Require one complete, typed taxonomy record per analyzed parent post."""
    if not isinstance(results, list):
        raise ValueError("classification results must be a JSON array")
    expected_ids = {
        record.get("post_id")
        for record in post_records
        if isinstance(record.get("post_id"), str) and record.get("post_id")
    }
    if len(expected_ids) != len(post_records):
        raise ValueError("classification parent post IDs are invalid")

    validated: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    allowed_fields = (
        _CLASSIFICATION_REQUIRED_FIELDS | _CLASSIFICATION_OPTIONAL_FIELDS
    )
    for index, result in enumerate(results):
        label = f"classification result {index + 1}"
        if not isinstance(result, dict):
            raise ValueError(f"{label} must be an object")
        missing = _CLASSIFICATION_REQUIRED_FIELDS - set(result)
        unknown = set(result) - allowed_fields
        if missing or unknown:
            raise ValueError(f"{label} has an invalid field inventory")

        post_id = result.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            raise ValueError(f"{label} has an invalid parent post_id")
        if post_id in seen_ids:
            raise ValueError("classification results contain duplicate post_id")
        if post_id not in expected_ids:
            raise ValueError(f"{label} does not reference an analyzed parent post")
        seen_ids.add(post_id)

        topic = result.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError(f"{label} has an invalid topic")
        if topic != "unknown" and not 2 <= len(topic) <= 10:
            raise ValueError(f"{label} has an invalid topic")
        if result.get("format") not in _TAX_FORMAT:
            raise ValueError(f"{label} has an invalid format")
        if result.get("funnel_stage") not in _TAX_FUNNEL:
            raise ValueError(f"{label} has an invalid funnel_stage")
        if result.get("hook_type") not in _TAX_HOOK:
            raise ValueError(f"{label} has an invalid hook_type")

        series_name = result.get("series_name")
        if series_name is not None and not isinstance(series_name, str):
            raise ValueError(f"{label} has an invalid series_name")
        for field in ("is_original", "has_product_placement"):
            value = result.get(field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{label} has an invalid {field}")
        labels = result.get("analysis_labels")
        if not isinstance(labels, list) or not all(
            isinstance(value, str) for value in labels
        ):
            raise ValueError(f"{label} has invalid analysis_labels")
        confidence = result.get("classification_confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"{label} has invalid classification_confidence")
        version = result.get("classification_version")
        if version is not None and version != "llm-1":
            raise ValueError(f"{label} has an invalid classification_version")
        validated.append(dict(result))

    if seen_ids != expected_ids:
        raise ValueError("classification results do not cover every parent post")
    return validated


# ---------------------------------------------------------------------------
# 任务参数发现
# ---------------------------------------------------------------------------

def load_task_params(task_dir: str, args: argparse.Namespace) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for name in ("task.json", "task-params.json", "source/task.json"):
        p = os.path.join(task_dir, name)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    params.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
            break
    # CLI 覆盖优先
    if args.analysis_goal is not None:
        params["analysis_goal"] = args.analysis_goal
    if args.requested_limit is not None:
        params["requested_limit"] = args.requested_limit
    if args.date_from is not None:
        params["date_from"] = args.date_from
    if args.date_to is not None:
        params["date_to"] = args.date_to
    if args.task_id is not None:
        params["task_id"] = args.task_id
    if args.platform is not None:
        params["platform"] = args.platform
    return params


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def generate_report(
    meta: Dict[str, Any],
    sample_boundary: Dict[str, Any],
    cadence: Dict[str, Any],
    metric_summary: Dict[str, Any],
    engagement: Dict[str, Any],
    high_performance: Any,
    low_performance: Any,
    main_metric: str,
    metric_note: Optional[str] = None,
) -> str:
    L: List[str] = []
    classification_status = meta.get("classification_status") or "pending-model"
    classification_version = meta.get("classification_version")
    classification_coverage = meta.get("classification_coverage") or {}
    classification_version_label = (
        "null" if classification_version is None else str(classification_version)
    )
    coverage_total = classification_coverage.get("total_count")
    coverage_classified = classification_coverage.get("classified_count")
    coverage_rate = classification_coverage.get("rate")
    coverage_rate_label = "null" if coverage_rate is None else str(coverage_rate)
    L.append("# 账号内容分析报告(公开页面快照)")
    L.append("")
    L.append("> 本报告基于无需登录即可查看的公开页面数据生成,代表公开页面快照,")
    L.append("> **不代表账号后台真实曝光、触达、完播或转化**。")
    L.append("> 分类字段(topic/format/funnel_stage/hook_type 等)由模型在运行时填充,")
    L.append(
        f"> 当前状态:{classification_status};"
        f"classification_version = {classification_version_label};"
        f"覆盖 {coverage_classified}/{coverage_total}(比例 {coverage_rate_label})。"
    )
    if meta.get("collection_source"):
        L.append(
            f"> 采集状态:{meta.get('task_status') or '未知'};停止原因:"
            f"{meta.get('stop_reason') or 'null'};来源:{meta.get('collection_source')}。"
        )
        L.append(
            "> 本批数据是非穷尽的公开索引快照，不是实时完整作品列表；"
            "搜索索引的 idx-* 为本地记录键。"
        )
    L.append("")
    L.append("## 样本边界(报告必填,见 §2)")
    L.append("")
    L.append(f"- 请求数量(requested):{sample_boundary['requested']}"
             + (" (由实际采集数量推导)" if sample_boundary.get("requested_is_derived") else ""))
    L.append(f"- 实际采集数量(collected):{sample_boundary['collected']}")
    L.append(f"- 有效数量(valid):{sample_boundary['valid']}")
    L.append(f"- 缺失内容数量(missing,FAILED/DELETED):{sample_boundary['missing']}")
    L.append(f"- 受限内容数量(restricted):{sample_boundary['restricted']}")
    L.append(f"- 被排除标记内容数量(excluded_flagged,置顶/转载/投放):{sample_boundary['excluded_flagged']}")
    tr = sample_boundary["time_range"]
    L.append(f"- 时间范围:任务 {tr['task_date_from']} ~ {tr['task_date_to']};"
             f" 有效内容 {tr['content_earliest']} ~ {tr['content_latest']}")
    L.append("")
    L.append("### 指标字段覆盖率(有效样本中非 null 比例)")
    L.append("")
    L.append("| 字段 | 覆盖率 |")
    L.append("|---|---|")
    for m, cov in sample_boundary["field_coverage"].items():
        L.append(f"| {m} | {cov if cov is not None else 'N/A'} |")
    L.append("")

    L.append("## 发布节奏(§3)")
    L.append("")
    L.append(f"- 总发布数量:{cadence['total_posts']}")
    L.append(f"- 覆盖天数:{cadence['coverage_days']}")
    L.append(f"- 覆盖周数:{cadence['coverage_weeks']}(不小于 1)")
    L.append(f"- 周均发布量:{cadence['weekly_avg']}")
    L.append(f"- 发布间隔中位数:{cadence['median_interval_hours']} 小时")
    L.append(f"- 最长断更时间:{cadence['longest_gap_hours']} 小时")
    wd = cadence["weekday_distribution"]
    L.append(f"- 星期分布:" + ", ".join(f"{WEEKDAY_NAMES[int(k)]}={v}" for k, v in wd.items()))
    wwe = cadence["weekday_weekend"]
    L.append(f"- 工作日/周末:工作日 {wwe['weekday_count']}({wwe['weekday_pct']}),"
             f" 周末 {wwe['weekend_count']}({wwe['weekend_pct']})")
    # 季节性/学期（§3 扩展）
    md_dist = cadence.get("monthly_distribution") or {}
    if md_dist:
        L.append("- 月度发布分布:" + ", ".join(f"{k}={v}" for k, v in md_dist.items()))
    si = cadence.get("seasonal_intensity")
    if si is not None:
        L.append(f"- 季节性强度(月变异系数):{si}")
        L.append(f"- 寒暑假月份(1/2/7/8)发布占比:{cadence.get('break_month_share')}")
        note = cadence.get("seasonal_note")
        if note:
            L.append(f"- 季节性提示:{note}")
    cadence_note = cadence.get("note")
    if cadence_note:
        L.append(f"- 节奏边界:{cadence_note}")
    L.append("")

    L.append("## 公开表现指标(§4)")
    L.append("")
    L.append("| 指标 | count | median | p25 | p75 | min | max | missing_rate | 可见 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for m, st in metric_summary.items():
        L.append(f"| {m} | {st['count']} | {st['median']} | {st['p25']} | {st['p75']} |"
                 f" {st['minimum']} | {st['maximum']} | {st['missing_rate']} | {st['visible']} |")
    L.append("")
    # IQR 散布比（§4 扩展，确定性启发式，用于高低表现置信度提示）
    L.append("**指标散布比（IQR / 中位数，越高越离散）**")
    L.append("")
    L.append("| 指标 | IQR | 散布比 |")
    L.append("|---|---|---|")
    for m, st in metric_summary.items():
        L.append(f"| {m} | {st.get('iqr')} | {st.get('dispersion_ratio')} |")
    L.append("")
    L.append("> 相对中位数表现(relative_performance = post_metric / metric_median)见 analysis.json 各 post 记录;"
             " metric_median 为 0/null 时该条该指标置 null。")
    L.append("")

    L.append("## 互动率(分母透明,§4)")
    L.append("")
    vb = engagement["view_based_engagement_rate"]
    fb = engagement["follower_based_engagement_ratio"]
    L.append("### 基于播放的互动率 (likes+comments+favorites+shares)/views")
    L.append(f"- count={vb['count']}, median={vb['median']}, p25={vb['p25']}, p75={vb['p75']},"
             f" min={vb['minimum']}, max={vb['maximum']}, missing_rate={vb['missing_rate']}")
    L.append("### 基于粉丝的互动比 (likes+comments+favorites+shares)/followers")
    L.append(f"- followers={engagement['followers']}")
    L.append(f"- count={fb['count']}, median={fb['median']}, p25={fb['p25']}, p75={fb['p75']},"
             f" min={fb['minimum']}, max={fb['maximum']}, missing_rate={fb['missing_rate']}")
    # 四分法扩展（§4）
    deep = engagement.get("deep_approval_rate") or {}
    disc = engagement.get("community_discussion_rate") or {}
    if deep:
        L.append("### 深度认可率 (coins+favorites)/views")
        L.append(f"- count={deep['count']}, median={deep['median']}, p25={deep['p25']}, p75={deep['p75']},"
                 f" min={deep['minimum']}, max={deep['maximum']}, missing_rate={deep['missing_rate']}")
    if disc:
        L.append("### 社群讨论率 (comments+danmaku)/views")
        L.append(f"- count={disc['count']}, median={disc['median']}, p25={disc['p25']}, p75={disc['p75']},"
                 f" min={disc['minimum']}, max={disc['maximum']}, missing_rate={disc['missing_rate']}")
    L.append("")

    L.append("## 高低表现内容(§6)")
    L.append("")
    L.append(f"- 主排序指标(main_sort_metric):{main_metric}")
    if metric_note:
        L.append(f"- 主指标说明(§6.1 安全约束):{metric_note}")
    if high_performance == "INSUFFICIENT_SAMPLE":
        L.append(f"- **INSUFFICIENT_SAMPLE**:有效样本不足 {MIN_SAMPLE_FOR_HIGH_LOW} 条,"
                 f"不输出高低表现组,不补造结论。")
    else:
        L.append(f"- 高表现组(每组 {len(high_performance)} 条):")
        for it in high_performance:
            target = it.get("post_url") or it.get("evidence_url") or "无单条作品链接"
            label = "作品链接" if it.get("item_url_known") else "证据锚点"
            L.append(f"  - #{it['rank']} {it['post_id']} — {it['reason']} ({label}: {target})")
        L.append(f"- 低表现组:")
        for it in low_performance:
            target = it.get("post_url") or it.get("evidence_url") or "无单条作品链接"
            label = "作品链接" if it.get("item_url_known") else "证据锚点"
            L.append(f"  - #{it['rank']} {it['post_id']} — {it['reason']} ({label}: {target})")
        L.append("> 高低表现仅描述样本中事实性差异,不宣称因果关系(§6.4)。")
    L.append("")

    L.append("## 模型分类状态(§5)")
    L.append("")
    L.append(f"- classification_status = {classification_status}")
    L.append(f"- classification_version = {classification_version_label}")
    L.append(
        f"- classification_coverage = {coverage_classified}/{coverage_total} "
        f"(rate={coverage_rate_label})"
    )
    if classification_status == "completed":
        L.append("- 所有有效内容已通过父作品、字段类型、枚举与覆盖校验。")
    elif classification_status == "partial-model":
        L.append("- 仅 classification_version = llm-1 的内容计为已分类;其余分类槽位保持 null,analysis_labels 保持 []。")
    else:
        L.append("- 每条有效内容的分类槽位保持 null,analysis_labels 保持 [],等待模型填充。")
    L.append("- 确定性指标不写入分类结构。")
    L.append("")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisResult:
    analysis: Dict[str, Any]
    taxonomy_prompt: Optional[str] = None


def analyze_in_memory(
    profile: Dict[str, Any],
    normalized_rows: List[Dict[str, Any]],
    task_params: Dict[str, Any],
    *,
    classification_results: Any = None,
    with_taxonomy_prompt: bool = False,
) -> AnalysisResult:
    """Build analysis from verified values without filesystem side effects."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    if not isinstance(normalized_rows, list) or not all(
        isinstance(row, dict) for row in normalized_rows
    ):
        raise ValueError("normalized rows must be a list of objects")
    if not isinstance(task_params, dict):
        raise ValueError("task parameters must be an object")

    params = dict(task_params)
    all_posts = build_posts(normalized_rows)
    collected = len(all_posts)
    _, valid, flagged, missing, restricted = split_samples(all_posts)
    valid_count = len(valid)

    cadence = compute_cadence(valid)
    if (
        params.get("collection_source")
        in ("douyin_jingxuan", "douyin_search_index")
        and params.get("evidence_is_exhaustive") is False
    ):
        cadence = restrict_nonexhaustive_index_cadence(cadence)
    metric_summary = compute_metric_summary(valid, profile)
    medians = compute_medians(valid)
    followers = parse_int(profile.get("followers"))
    engagement = compute_engagement(valid, profile)

    main_metric, metric_note = choose_main_metric(
        params.get("analysis_goal"), valid
    )

    measured_items = _measured_metric_items(valid, main_metric)
    measured_count = len(measured_items)
    main_metric_median = _main_metric_median(measured_items)
    hl = None if measured_count == 0 else compute_high_low(valid, main_metric)
    if hl is None:
        high_performance: Any = "INSUFFICIENT_SAMPLE"
        low_performance: Any = "INSUFFICIENT_SAMPLE"
        evidence_coverage = _empty_evidence_coverage()
        core_insights: List[Dict[str, Any]] = []
        if measured_count == 0:
            status_reason = (
                f"主排序指标 {main_metric} 全为 null,遵循 §6.1 安全约束跳过高低表现模块"
            )
        else:
            status_reason = (
                f"主指标实测样本 {measured_count} < {MIN_SAMPLE_FOR_HIGH_LOW}"
            )
        performance_meta = {
            "status": "INSUFFICIENT_SAMPLE",
            "main_metric": main_metric,
            "measured_count": measured_count,
            "main_metric_median": main_metric_median,
            "reason": status_reason,
            "metric_note": metric_note,
        }
    else:
        high_performance = hl["high"]
        low_performance = hl["low"]
        evidence_coverage = hl["evidence_coverage"]
        core_insights = hl["core_insights"]
        performance_meta = {
            "status": "ok",
            "main_metric": main_metric,
            "group_size": hl["group_size"],
            "measured_count": hl["measured_count"],
            "main_metric_median": hl["main_metric_median"],
            "note": hl["note"],
            "metric_note": metric_note,
        }
    performance_meta["evidence_coverage"] = copy.deepcopy(evidence_coverage)

    requested = params.get("requested_limit")
    requested_is_derived = False
    if requested is None:
        requested = collected
        requested_is_derived = True
    dated_posts = [post for post in valid if post["published_at"]]
    min_post = (
        min(dated_posts, key=lambda post: post["published_at"])
        if dated_posts
        else None
    )
    max_post = (
        max(dated_posts, key=lambda post: post["published_at"])
        if dated_posts
        else None
    )
    content_min = format_published_at_for_boundary(min_post) if min_post else None
    content_max = format_published_at_for_boundary(max_post) if max_post else None
    field_coverage = {}
    for metric in METRIC_FIELDS:
        nonnull = sum(1 for post in valid if post[metric] is not None)
        field_coverage[metric] = (
            rnd(nonnull / valid_count, 4) if valid_count else None
        )

    sample_boundary = {
        "requested": requested,
        "requested_is_derived": requested_is_derived,
        "collected": collected,
        "status_counts": collection_status_counts(all_posts),
        "valid": valid_count,
        "time_range": {
            "task_date_from": params.get("date_from"),
            "task_date_to": params.get("date_to"),
            "content_earliest": content_min,
            "content_latest": content_max,
        },
        "missing": len(missing),
        "restricted": len(restricted),
        "excluded_flagged": len(flagged),
        "excluded_flagged_post_ids": [post["post_id"] for post in flagged],
        "field_coverage": field_coverage,
    }

    post_records = build_post_records(valid, medians, followers)
    taxonomy_applied = classification_results is not None
    if taxonomy_applied:
        classification_results = validate_classification_results(
            post_records, classification_results
        )
        post_records = apply_taxonomy(post_records, classification_results)
    classification = classification_contract(post_records)
    taxonomy_prompt = (
        build_taxonomy_prompt(valid, followers) if with_taxonomy_prompt else None
    )
    classification_note = (
        "确定性指标由脚本计算;语义分类结果已完成严格父作品、字段类型、"
        "枚举与覆盖校验(classification_version='llm-1')。"
        if taxonomy_applied
        else (
            "确定性指标由脚本计算;topic/format/funnel_stage/hook_type/series_name/"
            "is_original/has_product_placement 等分类字段由模型在运行时填充"
            "(classification_status='pending-model', classification_version=null),"
            "本脚本仅准备结构。"
        )
    )

    meta = {
        "task_id": params.get("task_id"),
        "platform": profile.get("platform") or params.get("platform"),
        "profile_url": profile.get("profile_url"),
        "account_name": profile.get("account_name"),
        "requested_limit": params.get("requested_limit"),
        "date_from": params.get("date_from"),
        "date_to": params.get("date_to"),
        "analysis_goal": params.get("analysis_goal"),
        "include_comments": params.get("include_comments"),
        "task_status": params.get("task_status"),
        "stop_reason": params.get("stop_reason"),
        "diagnostic_code": params.get("diagnostic_code"),
        "collection_source": params.get("collection_source"),
        "source_kind": params.get("source_kind"),
        "source_url": params.get("source_url"),
        "snapshot_crawled_at": params.get("snapshot_crawled_at"),
        "snapshot_age_label": params.get("snapshot_age_label"),
        "evidence_is_exhaustive": params.get("evidence_is_exhaustive"),
        "main_sort_metric": main_metric,
        **copy.deepcopy(classification),
        "note": classification_note,
    }
    if with_taxonomy_prompt or taxonomy_applied:
        meta["llm_taxonomy"] = {
            "enabled": True,
            "prompt_file": "taxonomy-prompt.md" if with_taxonomy_prompt else None,
            "backfilled": taxonomy_applied,
        }

    analysis = {
        "meta": meta,
        "sample_boundary": sample_boundary,
        "publish_cadence": cadence,
        "metric_summary": metric_summary,
        "engagement": engagement,
        "high_performance": high_performance,
        "low_performance": low_performance,
        "performance_meta": performance_meta,
        "evidence_coverage": copy.deepcopy(evidence_coverage),
        "core_insights": core_insights,
        "posts": post_records,
        **copy.deepcopy(classification),
    }
    return AnalysisResult(analysis=analysis, taxonomy_prompt=taxonomy_prompt)

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="确定性账号内容分析 + 模型分类槽位准备")
    parser.add_argument("--input", required=True, help="任务目录(含 normalized-posts.csv 与 source/profile.json)")
    parser.add_argument("--analysis-goal", default=None, help="分析目的(用于 §6 主排序指标选择)")
    parser.add_argument("--requested-limit", type=int, default=None, help="请求采集数量上限")
    parser.add_argument("--date-from", default=None, help="采集起始时间 ISO 8601")
    parser.add_argument("--date-to", default=None, help="采集结束时间 ISO 8601")
    parser.add_argument("--task-id", default=None, help="任务 ID")
    parser.add_argument("--platform", default=None, help="平台标识")
    parser.add_argument("--with-llm-tax", action="store_true",
                        help="生成 LLM 分类标注 Prompt 模版(taxonomy-prompt.md)；仅做语义标注，不调用模型")
    parser.add_argument("--llm-tax-results", default=None,
                        help="LLM 返回的分类结果 JSON 路径，回填进分类槽位(classification_version=llm-1)")
    args = parser.parse_args(argv)

    task_dir = args.input
    if not os.path.isdir(task_dir):
        print(f"ERROR: 任务目录不存在: {task_dir}", file=sys.stderr)
        return 2
    try:
        reject_sealed_workspace(task_dir)
    except WorkspaceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    profile = load_profile(task_dir)
    normalized_rows = load_posts(task_dir)
    task_params = load_task_params(task_dir, args)
    classification_results: Any = None
    if args.llm_tax_results:
        try:
            with open(args.llm_tax_results, encoding="utf-8") as fh:
                classification_results = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: 分类结果读取失败: {e}", file=sys.stderr)
            return 2

    try:
        result = analyze_in_memory(
            profile,
            normalized_rows,
            task_params,
            classification_results=classification_results,
            with_taxonomy_prompt=args.with_llm_tax,
        )
    except (TypeError, ValueError) as e:
        print(f"ERROR: 分类结果校验失败: {e}", file=sys.stderr)
        return 2

    analysis = result.analysis
    meta = analysis["meta"]
    sample_boundary = analysis["sample_boundary"]
    cadence = analysis["publish_cadence"]
    metric_summary = analysis["metric_summary"]
    engagement = analysis["engagement"]
    high_performance = analysis["high_performance"]
    low_performance = analysis["low_performance"]
    main_metric = meta["main_sort_metric"]
    metric_note = (analysis.get("performance_meta") or {}).get("metric_note")

    if metric_note:
        print(f"NOTE: 主排序指标回退/跳过 -> {metric_note}", file=sys.stderr)
    if classification_results is not None:
        print(f"OK: 已回填 LLM 分类结果 -> {args.llm_tax_results}", file=sys.stderr)
    if result.taxonomy_prompt is not None:
        prompt_path = os.path.join(task_dir, "taxonomy-prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as fh:
            fh.write(result.taxonomy_prompt)
        print(f"OK: LLM 分类 Prompt 已生成 -> {prompt_path}", file=sys.stderr)

    out_json = os.path.join(task_dir, "analysis.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    report = generate_report(
        meta, sample_boundary, cadence, metric_summary,
        engagement, high_performance, low_performance, main_metric, metric_note,
    )
    out_md = os.path.join(task_dir, "account-analysis-report.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"OK: 分析完成 -> {out_json}")
    print(f"OK: 报告完成 -> {out_md}")
    print(
        f"     有效样本={sample_boundary['valid']}, 主排序指标={main_metric}, "
        f"高低表现={analysis['performance_meta']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
