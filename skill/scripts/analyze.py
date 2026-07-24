#!/usr/bin/env python3
# 分析:确定性指标计算 + 模型分类槽位准备
# 对应 references/analysis-rules.md §3 发布节奏 / §4 公开表现指标 / §5 模型分类 / §6 高低表现内容
# 纯 Python + 标准库实现,无模型、无网络、无 LLM。所有计算确定性、可复现。

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 统一指标字段(见 data-schema.md §6)
METRIC_FIELDS = ["views", "likes", "comments", "favorites", "shares", "coins", "danmaku"]
VALID_STATUS = {"SUCCESS", "PARTIAL"}  # 参与默认统计的采集状态(§1)
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


def parse_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f", ""):
        return False
    return default


def parse_hashtags(v: Any) -> List[str]:
    if v is None:
        return []
    s = str(v).strip()
    if s == "":
        return []
    if s.startswith("["):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x) for x in arr]
        except (json.JSONDecodeError, TypeError):
            pass
    parts = [p.strip().lstrip("#") for p in s.replace(";", ",").split(",") if p.strip()]
    return parts


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
            "collection_status": (row.get("collection_status") or "SUCCESS").strip().upper(),
            "collected_at": row.get("collected_at"),
            "source_url": row.get("source_url") or row.get("post_url"),
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
    ]
    missing = [p for p in all_posts if p["collection_status"] in ("FAILED", "DELETED")]
    restricted = [p for p in all_posts if p["collection_status"] == "RESTRICTED"]
    return all_posts, valid, flagged, missing, restricted


# ---------------------------------------------------------------------------
# §3 发布节奏
# ---------------------------------------------------------------------------

def compute_cadence(valid: List[Dict[str, Any]]) -> Dict[str, Any]:
    dates = [p["published_at"] for p in valid if p["published_at"] is not None]
    total = len(valid)

    if not dates:
        return {
            "total_posts": total,
            "coverage_days": 0,
            "coverage_weeks": 1,
            "weekly_avg": (rnd(float(total), 4) if total else None),
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
            "note": "有效内容均无 published_at,无法计算基于时间的节奏指标",
        }

    dts_utc = [d.astimezone(timezone.utc) for d in dates]
    min_d, max_d = min(dts_utc), max(dts_utc)
    span_days = (max_d - min_d).days
    coverage_weeks = max(math.ceil(span_days / 7), 1)  # 覆盖周数不小于 1
    coverage_days = len({(d.year, d.month, d.day) for d in dates})
    weekly_avg = total / coverage_weeks if coverage_weeks else None

    sorted_dates = sorted(dates)
    gaps: List[float] = []
    for i in range(1, len(sorted_dates)):
        gaps.append((sorted_dates[i] - sorted_dates[i - 1]).total_seconds() / 3600.0)
    median_gap = percentile(sorted(gaps), 0.5) if gaps else None
    longest_gap = max(gaps) if gaps else None

    # 星期 / 小时分布:使用帖子自身时区的墙上时间(无时区按 +08:00,见 parse_dt)
    wd = {str(i): 0 for i in range(7)}
    for d in dates:
        wd[str(d.weekday())] += 1
    hr = {str(i): 0 for i in range(24)}
    for d in dates:
        hr[str(d.hour)] += 1

    wd_count = sum(v for k, v in wd.items() if int(k) < 5)
    we_count = sum(v for k, v in wd.items() if int(k) >= 5)
    tot = wd_count + we_count

    # 月度分布与季节性/学期检测（§3 扩展，确定性启发式，非因果）
    monthly: Dict[str, int] = {}
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
    break_month_share = rnd(break_count / total, 4) if total else None
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
    }


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
        # visible:field_visibility 标注 visible/partial,或实际存在非 null 值
        st["visible"] = bool(fv.get(m) in ("visible", "partial") or len(vals) > 0)
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

def engagement_numerator(p: Dict[str, Any]) -> float:
    # 分子固定 = likes + comments + favorites + shares;
    # null 组件按 0 计入(§4:微博 favorites 为 null 时按 0)。
    return (p["likes"] or 0) + (p["comments"] or 0) + (p["favorites"] or 0) + (p["shares"] or 0)


def view_based_rate(p: Dict[str, Any]) -> Optional[float]:
    v = p["views"]
    if v is None or v == 0:
        return None
    return engagement_numerator(p) / v


def follower_based_ratio(p: Dict[str, Any], followers: Optional[int]) -> Optional[float]:
    if followers is None or followers == 0:
        return None
    return engagement_numerator(p) / followers


def deep_approval_rate(p: Dict[str, Any]) -> Optional[float]:
    """三分法·深度认可率 = (coins + favorites) / likes（§4 扩展）。

    分母 likes 为 null/0 时该条置 null（禁止用 0 做分母）。
    coins/favorites 为 null 时按 0 计入分子（单条互动指标，非统一互动率分子）。
    """
    likes = p["likes"]
    if likes is None or likes == 0:
        return None
    coins = p["coins"] or 0
    favorites = p["favorites"] or 0
    return (coins + favorites) / likes


def community_discussion_rate(p: Dict[str, Any]) -> Optional[float]:
    """三分法·社群讨论率 = (comments + danmaku) / views（§4 扩展）。

    分母 views 为 null/0 时该条置 null（分母透明）。
    comments/danmaku 为 null 时按 0 计入分子。
    """
    views = p["views"]
    if views is None or views == 0:
        return None
    comments = p["comments"] or 0
    danmaku = p["danmaku"] or 0
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
            "deep_approval_rate 以 likes 为分母=(coins+favorites)/likes;"
            "community_discussion_rate 以 views 为分母=(comments+danmaku)/views。"
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


def compute_high_low(valid: List[Dict[str, Any]], main_metric: str) -> Optional[Dict[str, Any]]:
    n = len(valid)
    if n < MIN_SAMPLE_FOR_HIGH_LOW:
        return None  # 标记 INSUFFICIENT_SAMPLE

    items = [(p, post_metric_value(p, main_metric)) for p in valid]

    def keyf(t: Tuple[Dict, Optional[float]]):
        v = t[1]
        return (v is not None, v if v is not None else 0.0)

    items_sorted = sorted(items, key=keyf, reverse=True)

    k = math.ceil(n * 0.2)
    if k < 3:
        k = 3  # 每组至少 3 条(§6.2)
    if k > n // 2:
        k = n // 2

    high = items_sorted[:k]
    low = items_sorted[-k:]

    def to_item(t: Tuple[Dict, Optional[float]], rank: int) -> Dict[str, Any]:
        p, v = t
        return {
            "post_id": p["post_id"],
            "post_url": p["post_url"],
            "value": rnd(v, 6) if v is not None else None,
            "rank": rank,
            "reason": f"主指标 {main_metric} = {rnd(v, 6) if v is not None else 'null'}",
        }

    high_items = [to_item(t, i + 1) for i, t in enumerate(high)]
    low_items = [to_item(t, n - k + i + 1) for i, t in enumerate(low)]
    return {
        "high": high_items,
        "low": low_items,
        "group_size": k,
        "main_metric": main_metric,
        "note": "高低表现仅描述样本中的相关特征,不构成因果结论(§6.4)",
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
        recs.append({
            "post_id": p["post_id"],
            "post_url": p["post_url"],
            "published_at": p["published_at"].isoformat() if p["published_at"] else None,
            "metrics": {m: p[m] for m in METRIC_FIELDS},
            "relative_performance": rel,
            "view_based_engagement_rate": rnd(view_based_rate(p), 6),
            "follower_based_engagement_ratio": rnd(follower_based_ratio(p, followers), 6),
            # —— 以下为模型分类槽位(§5),本脚本仅准备结构 ——
            "topic": None,
            "format": "unknown",
            "funnel_stage": "unknown",
            "hook_type": "unknown",
            "series_name": None,
            "is_original": None,
            "has_product_placement": None,
            "analysis_labels": [],
            "classification_confidence": None,
            "classification_version": "pending-model",
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
    L.append("# 账号内容分析报告(公开页面快照)")
    L.append("")
    L.append("> 本报告基于无需登录即可查看的公开页面数据生成,代表公开页面快照,")
    L.append("> **不代表账号后台真实曝光、触达、完播或转化**。")
    L.append("> 分类字段(topic/format/funnel_stage/hook_type 等)由模型在运行时填充,")
    L.append("> 当前状态:分类待模型填充(classification_version = pending-model)。")
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
    # 三分法扩展（§4）
    deep = engagement.get("deep_approval_rate") or {}
    disc = engagement.get("community_discussion_rate") or {}
    if deep:
        L.append("### 深度认可率 (coins+favorites)/likes")
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
            L.append(f"  - #{it['rank']} {it['post_id']} — {it['reason']} ({it['post_url']})")
        L.append(f"- 低表现组:")
        for it in low_performance:
            L.append(f"  - #{it['rank']} {it['post_id']} — {it['reason']} ({it['post_url']})")
        L.append("> 高低表现仅描述样本中事实性差异,不宣称因果关系(§6.4)。")
    L.append("")

    L.append("## 模型分类状态(§5)")
    L.append("")
    L.append("- classification_status = pending-model")
    L.append("- 每条有效内容已准备分类槽位(topic/format/funnel_stage/hook_type/series_name/"
             "is_original/has_product_placement),当前值为 null 或 `unknown` 占位符,")
    L.append("  由模型在运行时填充并写入 classification_version。确定性指标不写入分类结构。")
    L.append("")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
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
    args = parser.parse_args()

    task_dir = args.input
    if not os.path.isdir(task_dir):
        die(f"ERROR: 任务目录不存在: {task_dir}")

    profile = load_profile(task_dir)
    raw_rows = load_posts(task_dir)
    all_posts = build_posts(raw_rows)
    collected = len(all_posts)

    _, valid, flagged, missing, restricted = split_samples(all_posts)
    valid_count = len(valid)

    cadence = compute_cadence(valid)
    metric_summary = compute_metric_summary(valid, profile)
    medians = compute_medians(valid)
    followers = parse_int(profile.get("followers"))
    engagement = compute_engagement(valid, profile)

    # §6 主排序指标 + 高低表现
    task_params = load_task_params(task_dir, args)
    main_metric, metric_note = choose_main_metric(task_params.get("analysis_goal"), valid)
    if metric_note:
        print(f"NOTE: 主排序指标回退/跳过 -> {metric_note}", file=sys.stderr)

    def metric_usable(m: str) -> bool:
        return any(post_metric_value(p, m) is not None for p in valid)

    # §6.1 安全约束:主指标不可用(全 null)时跳过高低表现,不补造结论
    hl = None if not metric_usable(main_metric) else compute_high_low(valid, main_metric)
    if hl is None:
        high_performance: Any = "INSUFFICIENT_SAMPLE"
        low_performance: Any = "INSUFFICIENT_SAMPLE"
        if not metric_usable(main_metric):
            status_reason = (
                f"主排序指标 {main_metric} 全为 null,遵循 §6.1 安全约束跳过高低表现模块"
            )
        else:
            status_reason = f"有效样本 {valid_count} < {MIN_SAMPLE_FOR_HIGH_LOW}"
        performance_meta = {
            "status": "INSUFFICIENT_SAMPLE",
            "main_metric": main_metric,
            "reason": status_reason,
            "metric_note": metric_note,
        }
    else:
        high_performance = hl["high"]
        low_performance = hl["low"]
        performance_meta = {
            "status": "ok",
            "main_metric": main_metric,
            "group_size": hl["group_size"],
            "note": hl["note"],
            "metric_note": metric_note,
        }

    # 样本边界(§2)
    requested = task_params.get("requested_limit")
    requested_is_derived = False
    if requested is None:
        requested = collected
        requested_is_derived = True
    valid_dates = [p["published_at"] for p in valid if p["published_at"]]
    content_min = min(valid_dates).isoformat() if valid_dates else None
    content_max = max(valid_dates).isoformat() if valid_dates else None
    field_coverage = {}
    for m in METRIC_FIELDS:
        nn = sum(1 for p in valid if p[m] is not None)
        field_coverage[m] = rnd(nn / valid_count, 4) if valid_count else None

    sample_boundary = {
        "requested": requested,
        "requested_is_derived": requested_is_derived,
        "collected": collected,
        "valid": valid_count,
        "time_range": {
            "task_date_from": task_params.get("date_from"),
            "task_date_to": task_params.get("date_to"),
            "content_earliest": content_min,
            "content_latest": content_max,
        },
        "missing": len(missing),
        "restricted": len(restricted),
        "excluded_flagged": len(flagged),
        "excluded_flagged_post_ids": [p["post_id"] for p in flagged],
        "field_coverage": field_coverage,
    }

    # 模型分类槽位(§5)
    post_records = build_post_records(valid, medians, followers)

    # §5 LLM 协同分类（确定性 + 语义标注 标准接口）
    if args.llm_tax_results:
        try:
            with open(args.llm_tax_results, encoding="utf-8") as fh:
                tax_results = json.load(fh)
            post_records = apply_taxonomy(post_records, tax_results)
            print(f"OK: 已回填 LLM 分类结果 -> {args.llm_tax_results}", file=sys.stderr)
        except (OSError, json.JSONDecodeError) as e:
            print(f"WARN: 应用 LLM 分类结果失败({e})，保留 pending-model 占位", file=sys.stderr)
    if args.with_llm_tax:
        prompt = build_taxonomy_prompt(valid, followers)
        prompt_path = os.path.join(task_dir, "taxonomy-prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        print(f"OK: LLM 分类 Prompt 已生成 -> {prompt_path}", file=sys.stderr)

    meta = {
        "task_id": task_params.get("task_id"),
        "platform": profile.get("platform") or task_params.get("platform"),
        "profile_url": profile.get("profile_url"),
        "account_name": profile.get("account_name"),
        "requested_limit": task_params.get("requested_limit"),
        "date_from": task_params.get("date_from"),
        "date_to": task_params.get("date_to"),
        "analysis_goal": task_params.get("analysis_goal"),
        "include_comments": task_params.get("include_comments"),
        "main_sort_metric": main_metric,
        "classification_status": "pending-model",
        "note": (
            "确定性指标由脚本计算;topic/format/funnel_stage/hook_type/series_name/"
            "is_original/has_product_placement 等分类字段由模型在运行时填充"
            "(classification_version='pending-model'),本脚本仅准备结构。"
        ),
    }

    if args.with_llm_tax:
        meta["llm_taxonomy"] = {"enabled": True, "prompt_file": "taxonomy-prompt.md"}

    analysis = {
        "meta": meta,
        "sample_boundary": sample_boundary,
        "publish_cadence": cadence,
        "metric_summary": metric_summary,
        "engagement": engagement,
        "high_performance": high_performance,
        "low_performance": low_performance,
        "performance_meta": performance_meta,
        "posts": post_records,
        "classification_status": "pending-model",
    }

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
    print(f"     有效样本={valid_count}, 主排序指标={main_metric}, "
          f"高低表现={'INSUFFICIENT_SAMPLE' if hl is None else 'ok'}")


if __name__ == "__main__":
    main()
