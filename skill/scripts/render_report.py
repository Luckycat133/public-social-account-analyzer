#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_report.py —— 公开社媒账号分析 · 报告渲染器

读取任务目录下三份产物：
  - source/profile.json       账号公开快照
  - normalized-posts.csv      归一化内容表
  - analysis.json             结构化分析结果

生成：
  - account-analysis-report.md  12 节 Markdown 报告
  - dashboard.html              填充模板占位符的 HTML 报告

设计约束（见 references/data-schema.md、references/analysis-rules.md、
assets/report-template.html）：
  - 仅使用 Python 标准库（csv / json / argparse / re / pathlib / datetime）。
  - 确定性、无网络、无 LLM。
  - 12 个占位符逐一替换；无法填充时回退为「暂无数据」。
  - 坏链检查：报告引用的 post_url 不在 normalized-posts.csv 集合内 → 告警。
  - 空图检查：替换后若残留 <img src="http..."> → 告警。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 指标字段顺序与中文标签（见 data-schema §6）
METRIC_FIELDS = ["views", "likes", "comments", "favorites", "shares", "coins", "danmaku"]
METRIC_LABELS = {
    "views": "播放 / 浏览",
    "likes": "点赞",
    "comments": "评论",
    "favorites": "收藏",
    "shares": "分享 / 转发",
    "coins": "投币",
    "danmaku": "弹幕",
}

# 12 个占位符 -> 报告节标题（顺序固定，对应模板 SECTION 标记）
SECTION_DEFS = [
    ("task_info", "报告标题与任务信息"),
    ("quality_summary", "数据质量摘要"),
    ("account_card", "账号定位卡"),
    ("content_structure", "内容结构"),
    ("publish_cadence", "发布节奏"),
    ("metrics_dashboard", "公开指标看板"),
    ("high_performance", "高表现内容"),
    ("low_performance", "低表现内容"),
    ("content_patterns", "内容模式"),
    ("strategy", "策略建议"),
    ("sample_limits", "样本与限制"),
    ("sources", "来源链接"),
]
PLACEHOLDERS = [name for name, _ in SECTION_DEFS]

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DISCLAIMER = "本报告基于公开页面快照，不代表账号后台真实曝光、触达、完播或转化数据。"
EMPTY_MD = "暂无数据"
EMPTY_HTML = '<p class="empty">暂无数据</p>'

# 全局告警与引用收集（供坏链/空图检查使用）
WARNINGS: list[str] = []
KNOWN_POST_URLS: set[str] = set()
REFERENCED_POST_URLS: set[str] = set()


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"[WARN] {msg}", file=sys.stderr)


def h_esc(s) -> str:
    """HTML 转义（仅用标准库，不引入 html 模块）。"""
    s = "" if s is None else str(s)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


class Raw:
    """包装已在调用处拼好的 HTML 片段，html_table 不再二次转义。"""

    def __init__(self, s: str):
        self.s = s

    def __str__(self) -> str:
        return self.s


# 数值格式化 ----------------------------------------------------------------

def fmt_int(v) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"{int(v):,}"
    except (ValueError, TypeError):
        return str(v)


def fmt_float(v, nd: int = 2) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"{float(v):.{nd}f}"
    except (ValueError, TypeError):
        return str(v)


def fmt_pct(v, nd: int = 1) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"{float(v) * 100:.{nd}f}%"
    except (ValueError, TypeError):
        return str(v)


def fmt_metric(v) -> str:
    """指标值：整数加千分位，小数保留 2 位。"""
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return "—"
        if f == int(f):
            return f"{int(f):,}"
        return f"{f:,.2f}"
    except (ValueError, TypeError, OverflowError):
        return str(v)


# 链接 ---------------------------------------------------------------------

def link_md(url: str, text: str) -> str:
    return f"[{text}]({url})"


def link_html(url: str, text: str) -> Raw:
    return Raw(f'<a href="{h_esc(url)}">{h_esc(text)}</a>')


def ref_post(url) -> None:
    """登记被报告引用的内容 URL，供坏链检查。"""
    if url:
        REFERENCED_POST_URLS.add(str(url))


# 表格 ---------------------------------------------------------------------

def html_table(headers, rows) -> str:
    th = "".join(f"<th>{h_esc(h)}</th>" for h in headers)
    trs = []
    for r in rows:
        cells = []
        for c in r:
            if isinstance(c, Raw):
                cells.append(f"<td>{c.s}</td>")
            else:
                cells.append(f"<td>{h_esc(c)}</td>")
        trs.append(f"<tr>{''.join(cells)}</tr>")
    if not trs:
        return EMPTY_HTML
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def md_table(headers, rows) -> str:
    if not rows:
        return EMPTY_MD
    lines = ["| " + " | ".join(str(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        cells = [("—" if c is None or c == "" else str(c)) for c in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 内联 SVG 图表（零依赖；确定性、无网络）
# ---------------------------------------------------------------------------

def svg_timeline_scatter(posts: list, width: int = 600, height: int = 240) -> str:
    """时间轴散点图：published_at(x) × views(y)。仅含可见两项的数据点。"""
    pts: list = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        pa = p.get("published_at")
        v = (p.get("metrics") or {}).get("views")
        if not pa or v is None:
            continue
        try:
            s_pa = str(pa)
            if s_pa.endswith("Z"):
                s_pa = s_pa[:-1] + "+00:00"
            dt = datetime.fromisoformat(s_pa)
        except (ValueError, TypeError):
            continue
        pts.append((dt, float(v), p.get("post_id") or "?"))
    if len(pts) < 2:
        return ""
    ts = [t for t, _, _ in pts]
    tmin, tmax = min(ts), max(ts)
    vs = [v for _, v, _ in pts]
    vmax = max(vs) or 1
    pad = 38
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad
    spans = (tmax - tmin).total_seconds() or 1

    def x_of(t):
        return pad + ((t - tmin).total_seconds() / spans) * plot_w

    def y_of(v):
        return height - pad - (v / vmax) * plot_h

    circles = []
    for t, v, pid in pts:
        cx, cy = x_of(t), y_of(v)
        circles.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="#3b82f6" fill-opacity="0.7">'
            f'<title>{h_esc(pid)}: views={int(v):,}</title></circle>'
        )
    axes = (
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#cbd5e1"/>'
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#cbd5e1"/>'
    )
    labels = (
        f'<text x="{pad}" y="{height - 12}" font-size="10" fill="#64748b">{tmin.date()}</text>'
        f'<text x="{width - pad - 70}" y="{height - 12}" font-size="10" fill="#64748b">{tmax.date()}</text>'
        f'<text x="6" y="{pad + 4}" font-size="10" fill="#64748b">views≤{int(vmax):,}</text>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="发布时间-播放量散点图">'
        f'{axes}{"".join(circles)}{labels}</svg>'
    )


def svg_post_hour_distribution(hour_distribution: dict, width: int = 600, height: int = 200) -> str:
    """发布时段分布（24 小时柱状图）。hour_distribution: {str(hour): count}。

    仅含任意计数的小时；零依赖内联 SVG。
    """
    hours = []
    for h in range(24):
        try:
            hours.append(int(hour_distribution.get(str(h), 0)))
        except (TypeError, ValueError):
            hours.append(0)
    total = sum(hours)
    if total == 0:
        return ""
    maxv = max(hours) or 1
    pad_l, pad_r, pad_top, pad_bottom = 28, 10, 10, 22
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_top - pad_bottom
    slot = plot_w / 24
    bar_gap = 2
    bar_w = slot - bar_gap
    bars = []
    for h in range(24):
        c = hours[h]
        bh = (c / maxv) * plot_h if maxv else 0
        x = pad_l + h * slot + bar_gap / 2
        y = pad_top + (plot_h - bh)
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
            f'rx="1" fill="#3b82f6" fill-opacity="0.85">'
            f'<title>{h:02d}:00 — {c} 条</title></rect>'
        )
    axis = (f'<line x1="{pad_l}" y1="{pad_top + plot_h}" x2="{width - pad_r}" '
            f'y2="{pad_top + plot_h}" stroke="#cbd5e1"/>')
    ticks = []
    for h in range(0, 25, 3):
        x = pad_l + h * slot
        ticks.append(f'<text x="{x:.1f}" y="{height - 8}" font-size="9" fill="#64748b" '
                     f'text-anchor="middle">{h}</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="发布时段分布（24 小时柱状图，共 {total} 条）">'
        f'{axis}{"".join(bars)}{"".join(ticks)}</svg>'
    )


def svg_high_low_radar(high, low, metrics: list, width: int = 340, height: int = 300) -> str:
    """高低表现雷达图：高/低组在各指标上的中位数对比（按列最大值归一化）。"""
    def _collect(group):
        if not isinstance(group, list):
            return None
        vals = []
        for m in metrics:
            col = [((p.get("metrics") or {}).get(m) or 0) for p in group if isinstance(p, dict)]
            vals.append((sum(col) / len(col)) if col else 0.0)
        return vals

    series = []
    hv, lv = _collect(high), _collect(low)
    if hv:
        series.append(("高表现", hv, "#3b82f6"))
    if lv:
        series.append(("低表现", lv, "#f59e0b"))
    if not series:
        return ""
    maxima = []
    for i in range(len(metrics)):
        col = [s[1][i] for s in series]
        maxima.append(max(col) or 1)
    cx, cy = width / 2, height / 2 + 8
    R = min(width, height) / 2 - 40
    n = len(metrics)

    def _coord(i, val):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        r = (val / maxima[i]) * R if maxima[i] else 0
        return cx + r * math.cos(ang), cy + r * math.sin(ang)

    grid = []
    for ri in (0.25, 0.5, 0.75, 1.0):
        gp = " ".join(
            f"{cx + R * ri * math.cos(-math.pi / 2 + 2 * math.pi * i / n):.1f},"
            f"{cy + R * ri * math.sin(-math.pi / 2 + 2 * math.pi * i / n):.1f}"
            for i in range(n)
        )
        grid.append(f'<polygon points="{gp}" fill="none" stroke="#e2e8f0"/>')
    spokes = []
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        ex, ey = cx + R * math.cos(ang), cy + R * math.sin(ang)
        spokes.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#e2e8f0"/>')
        lx, ly = cx + (R + 14) * math.cos(ang), cy + (R + 14) * math.sin(ang)
        spokes.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="9" fill="#64748b" text-anchor="middle">'
            f'{h_esc(METRIC_LABELS.get(metrics[i], metrics[i]))}</text>'
        )
    polys = []
    for label, vals, color in series:
        pp = " ".join(f"{_coord(i, vals[i])[0]:.1f},{_coord(i, vals[i])[1]:.1f}" for i in range(n))
        polys.append(
            f'<polygon points="{pp}" fill="{color}" fill-opacity="0.22" stroke="{color}" '
            f'stroke-width="1.5"><title>{h_esc(label)}</title></polygon>'
        )
    legend = " ".join(
        f'<span style="display:inline-block;margin-right:12px;font-size:11px;color:#475569;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
        f'background:{color};margin-right:4px;"></span>{h_esc(label)}</span>'
        for _, _, color in series
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="高低表现雷达图">{"" .join(grid)}{"".join(spokes)}{"".join(polys)}</svg>'
        f'<div style="margin-top:4px;">{legend}</div>'
    )


def svg_coverage_badges(coverage: dict) -> str:
    """字段覆盖率徽章（内联 HTML，按阈值变色）。"""
    if not coverage:
        return ""
    badges = []
    for k, v in coverage.items():
        pctv = v if isinstance(v, (int, float)) else 0
        color = "#16a34a" if pctv >= 0.8 else ("#d97706" if pctv >= 0.5 else "#dc2626")
        badges.append(
            f'<span style="display:inline-block;padding:2px 8px;margin:2px;border-radius:10px;'
            f'background:{color}1a;color:{color};border:1px solid {color}55;font-size:12px;">'
            f'{h_esc(METRIC_LABELS.get(k, k))} {fmt_pct(v)}</span>'
        )
    return '<p class="note">字段覆盖率徽章</p>' + "".join(badges)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_json(path: Path):
    if not path.exists():
        warn(f"缺少文件: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        warn(f"解析 JSON 失败 {path}: {exc}")
        return None


def load_posts_csv(path: Path) -> list[dict]:
    if not path.exists():
        warn(f"缺少文件: {path}")
        return []
    rows = []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(row)
                url = (row.get("post_url") or "").strip()
                if url:
                    KNOWN_POST_URLS.add(url)
    except Exception as exc:  # noqa: BLE001
        warn(f"读取 CSV 失败 {path}: {exc}")
    return rows


# ---------------------------------------------------------------------------
# 各节渲染：每个函数返回 (md, html) 元组
# ---------------------------------------------------------------------------

def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is None:
            return default
    return cur


def build_task_info(analysis, profile, posts_csv) -> tuple[str, str]:
    meta = analysis.get("meta", {}) if isinstance(analysis, dict) else {}
    account_name = meta.get("account_name") or (profile or {}).get("account_name") or "未知账号"
    platform = meta.get("platform") or (profile or {}).get("platform") or "—"
    profile_url = meta.get("profile_url") or (profile or {}).get("profile_url") or "—"
    title = f"{account_name}（{platform}）公开账号分析报告"

    rows = [
        ["报告标题", title],
        ["任务 ID", meta.get("task_id") or "—"],
        ["平台", platform],
        ["账号名称", account_name],
        ["账号主页", link_md(profile_url, profile_url) if profile_url != "—" else "—"],
        ["请求采集数量", fmt_int(meta.get("requested_limit"))],
        ["采集时间范围", f"{meta.get('date_from') or '—'} ~ {meta.get('date_to') or '—'}"],
        ["分析目的", meta.get("analysis_goal") or "—"],
        ["主排序指标", meta.get("main_sort_metric") or "—"],
        ["分类状态", meta.get("classification_status") or "—"],
    ]
    md = md_table(["字段", "值"], rows)

    # 账号主页行需要渲染为链接
    html_rows = []
    for k, v in rows:
        if k == "账号主页" and profile_url != "—":
            html_rows.append([Raw(h_esc(k)), link_html(profile_url, profile_url)])
        else:
            html_rows.append([Raw(h_esc(k)), Raw(h_esc(v))])
    html = html_table(["字段", "值"], html_rows)
    return md, html


def build_quality_summary(analysis) -> tuple[str, str]:
    sb = _safe_get(analysis, "sample_boundary", default={}) or {}
    if not sb:
        return EMPTY_MD, EMPTY_HTML

    tr = sb.get("time_range", {}) or {}
    time_range = f"{tr.get('content_earliest') or '—'} ~ {tr.get('content_latest') or '—'}"

    rows = [
        ["请求数量 (requested)", fmt_int(sb.get("requested"))],
        ["实际采集数量 (collected)", fmt_int(sb.get("collected"))],
        ["有效数量 (valid)", fmt_int(sb.get("valid"))],
        ["缺失内容 (missing)", fmt_int(sb.get("missing"))],
        ["受限内容 (restricted)", fmt_int(sb.get("restricted"))],
        ["被排除标记内容 (excluded_flagged)", fmt_int(sb.get("excluded_flagged"))],
        ["有效内容时间范围", time_range],
    ]
    md = md_table(["样本边界指标", "数值"], rows)

    # 字段覆盖率子表
    fc = sb.get("field_coverage", {}) or {}
    if fc:
        fc_rows = [[METRIC_LABELS.get(k, k), fmt_pct(v)] for k, v in fc.items()]
        md += "\n\n**指标字段覆盖率**\n\n" + md_table(["指标", "覆盖率"], fc_rows)
        fc_html = [[Raw(h_esc(METRIC_LABELS.get(k, k))), Raw(h_esc(fmt_pct(v)))]
                   for k, v in fc.items()]
        cov_html = '<p class="note">指标字段覆盖率</p>' + html_table(["指标", "覆盖率"], fc_html)
        # 字段覆盖率徽章（阈值着色，零依赖）
        cov_html += svg_coverage_badges(fc)
    else:
        cov_html = ""

    html = html_table(["样本边界指标", "数值"],
                      [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in rows]) + cov_html
    return md, html


def build_account_card(profile) -> tuple[str, str]:
    if not profile:
        return EMPTY_MD, EMPTY_HTML
    rows = [
        ["平台", profile.get("platform") or "—"],
        ["账号 ID", profile.get("account_id") or "—"],
        ["账号名称", profile.get("account_name") or "—"],
        ["认证信息", profile.get("verified") or "—"],
        ["粉丝数", fmt_int(profile.get("followers"))],
        ["作品数", fmt_int(profile.get("post_count"))],
        ["简介", (profile.get("bio") or "—")],
        ["主页", link_md(profile.get("profile_url") or "", profile.get("profile_url") or "—")
         if profile.get("profile_url") else "—"],
    ]
    md = md_table(["字段", "值"], rows)

    html_rows = []
    for k, v in rows:
        if k == "主页" and profile.get("profile_url"):
            html_rows.append([Raw(h_esc(k)), link_html(profile["profile_url"], profile["profile_url"])])
        else:
            html_rows.append([Raw(h_esc(k)), Raw(h_esc(v))])
    html = html_table(["字段", "值"], html_rows)
    return md, html


def build_content_structure(analysis, posts_csv) -> tuple[str, str]:
    if not posts_csv and not analysis:
        return EMPTY_MD, EMPTY_HTML

    # 内容形态分布（来自 CSV）
    ct_counter = Counter(r.get("content_type") or "unknown" for r in posts_csv)
    ct_rows = [[k, fmt_int(v)] for k, v in ct_counter.most_common()]

    # 标记内容计数（置顶 / 转载 / 投放）
    def _b(v):
        return str(v).strip().lower() in ("true", "1", "yes")
    flag_rows = [
        ["置顶 (is_pinned)", fmt_int(sum(1 for r in posts_csv if _b(r.get("is_pinned"))))],
        ["转载 (is_repost)", fmt_int(sum(1 for r in posts_csv if _b(r.get("is_repost"))))],
        ["投放 (is_promoted)", fmt_int(sum(1 for r in posts_csv if _b(r.get("is_promoted"))))],
    ]

    md = "**内容形态分布**\n\n" + md_table(["内容形态", "数量"], ct_rows) + \
         "\n\n**特殊标记内容**\n\n" + md_table(["标记类型", "数量"], flag_rows)

    html = '<p class="note">内容形态分布</p>' + \
        html_table(["内容形态", "数量"], [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in ct_rows]) + \
        '<p class="note">特殊标记内容</p>' + \
        html_table(["标记类型", "数量"], [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in flag_rows])
    return md, html


def build_publish_cadence(analysis) -> tuple[str, str]:
    cad = _safe_get(analysis, "publish_cadence", default={}) or {}
    if not cad:
        return EMPTY_MD, EMPTY_HTML

    unit = cad.get("interval_unit", "hours")
    rows = [
        ["总发布数量", fmt_int(cad.get("total_posts"))],
        ["覆盖天数", fmt_int(cad.get("coverage_days"))],
        ["覆盖周数", fmt_int(cad.get("coverage_weeks"))],
        ["周均发布量", fmt_float(cad.get("weekly_avg"))],
        ["发布间隔中位数", f"{fmt_float(cad.get('median_interval_hours'))} {unit}"],
        ["最长断更时间", f"{fmt_float(cad.get('longest_gap_hours'))} {unit}"],
    ]
    md = md_table(["节奏指标", "数值"], rows)

    ww = cad.get("weekday_weekend", {}) or {}
    if ww:
        md += "\n\n**工作日 / 周末分布**\n\n" + md_table(
            ["类别", "数量", "占比"],
            [["工作日", fmt_int(ww.get("weekday_count")), fmt_pct(ww.get("weekday_pct"))],
             ["周末", fmt_int(ww.get("weekend_count")), fmt_pct(ww.get("weekend_pct"))]],
        )

    html = html_table(["节奏指标", "数值"],
                      [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in rows])
    if ww:
        html += '<p class="note">工作日 / 周末分布</p>' + html_table(
            ["类别", "数量", "占比"],
            [[Raw("工作日"), Raw(h_esc(fmt_int(ww.get("weekday_count")))), Raw(h_esc(fmt_pct(ww.get("weekday_pct"))))],
             [Raw("周末"), Raw(h_esc(fmt_int(ww.get("weekend_count")))), Raw(h_esc(fmt_pct(ww.get("weekend_pct"))))]],
        )

    # 星期分布（横向条）
    wd = cad.get("weekday_distribution", {}) or {}
    if wd:
        maxv = max((int(v) for v in wd.values()), default=1) or 1
        bars = []
        for i in range(7):
            cnt = int(wd.get(str(i), 0))
            pct = (cnt / maxv * 100) if maxv else 0
            bars.append(f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;">'
                        f'<span style="width:32px;color:var(--text-soft);">{WEEKDAY_NAMES[i]}</span>'
                        f'<span style="flex:1;background:var(--accent-soft);border-radius:4px;height:14px;position:relative;">'
                        f'<span style="position:absolute;left:0;top:0;height:14px;width:{pct:.1f}%;'
                        f'background:var(--accent);border-radius:4px;"></span></span>'
                        f'<span style="width:28px;text-align:right;">{cnt}</span></div>')
        html += '<p class="note">星期分布</p>' + "".join(bars)

    # 发布时段分布（24 小时柱状图，内联 SVG，零依赖）
    hr = cad.get("hour_distribution", {}) or {}
    if hr:
        hour_svg = svg_post_hour_distribution(hr)
        if hour_svg:
            html += '<p class="note">发布时段分布（24 小时）</p>' + hour_svg
        total_hr = sum(int(v) for v in hr.values())
        if total_hr:
            ranked = sorted(((int(k), int(v)) for k, v in hr.items()), key=lambda x: -x[1])
            top = ranked[:3]
            # 白天(6-22) / 深夜(22-6) 占比，作为可解释提示
            daytime = sum(int(v) for k, v in hr.items() if 6 <= int(k) < 22)
            nighttime = total_hr - daytime
            md += "\n\n**发布时段分布（24 小时）**\n\n" + \
                  "峰值时段：" + "、".join(f"{h:02d}:00（{c} 条）" for h, c in top) + "\n\n" + \
                  f"- 白天(06:00–22:00)占比：{fmt_pct(daytime / total_hr)}，" + \
                  f"深夜(22:00–06:00)占比：{fmt_pct(nighttime / total_hr)}"

    # 时间轴散点图（内联 SVG，零依赖）
    scatter = svg_timeline_scatter(analysis.get("posts") or [])
    if scatter:
        html += '<p class="note">发布时间-播放量散点图</p>' + scatter
    return md, html


def build_metrics_dashboard(analysis) -> tuple[str, str]:
    ms = _safe_get(analysis, "metric_summary", default={}) or {}
    eng = _safe_get(analysis, "engagement", default={}) or {}
    if not ms and not eng:
        return EMPTY_MD, EMPTY_HTML

    headers = ["指标", "count", "median", "p25", "p75", "min", "max", "缺失率"]
    rows = []
    for f in METRIC_FIELDS:
        d = ms.get(f)
        if not isinstance(d, dict):
            continue
        rows.append([
            METRIC_LABELS.get(f, f),
            fmt_int(d.get("count")),
            fmt_metric(d.get("median")),
            fmt_metric(d.get("p25")),
            fmt_metric(d.get("p75")),
            fmt_metric(d.get("minimum")),
            fmt_metric(d.get("maximum")),
            fmt_pct(d.get("missing_rate")),
        ])
    md = md_table(headers, rows) if rows else EMPTY_MD
    html = html_table(headers, [[Raw(h_esc(c)) if i == 0 else Raw(h_esc(c))
                                 for i, c in enumerate(r)] for r in rows]) if rows else EMPTY_HTML

    # 互动率（分母透明，四分法分列呈现）
    er_defs = [
        ("view_based_engagement_rate", "基于播放的互动率 (view_based)"),
        ("follower_based_engagement_ratio", "基于粉丝的互动比 (follower_based)"),
        ("deep_approval_rate", "深度认可率 (coins+favorites)/views"),
        ("community_discussion_rate", "社群讨论率 (comments+danmaku)/views"),
    ]
    er_rows, er_html = [], []
    for key, label in er_defs:
        d = eng.get(key, {}) or {}
        if not isinstance(d, dict) or not d.get("count"):
            continue
        er_rows.append([label, fmt_int(d.get("count")), fmt_pct(d.get("median")),
                        fmt_pct(d.get("p25")), fmt_pct(d.get("p75")),
                        fmt_pct(d.get("minimum")), fmt_pct(d.get("maximum")),
                        fmt_pct(d.get("missing_rate"))])
        er_html.append([Raw(h_esc(label)), Raw(h_esc(fmt_int(d.get("count")))),
                        Raw(h_esc(fmt_pct(d.get("median")))), Raw(h_esc(fmt_pct(d.get("p25")))),
                        Raw(h_esc(fmt_pct(d.get("p75")))), Raw(h_esc(fmt_pct(d.get("minimum")))),
                        Raw(h_esc(fmt_pct(d.get("maximum")))), Raw(h_esc(fmt_pct(d.get("missing_rate"))))])
    if er_rows:
        md += "\n\n**互动率（分母透明，四分法分列呈现）**\n\n" + md_table(
            ["互动指标", "count", "median", "p25", "p75", "min", "max", "缺失率"], er_rows)
        note = eng.get("denominator_note")
        if note:
            md += f"\n\n> 说明：{note}"

        html += '<p class="note">互动率（分母透明，四分法分列呈现）</p>' + html_table(
            ["互动指标", "count", "median", "p25", "p75", "min", "max", "缺失率"], er_html)
        if note:
            html += f'<p class="note">{h_esc(note)}</p>'
    return md, html


def _render_perf_group(group, main_metric: str | None = None) -> tuple[str, str]:
    if not isinstance(group, list) or not group:
        return EMPTY_MD, EMPTY_HTML

    headers = ["内容", "发布时间", "主指标值", "相对中位表现", "播放互动率"]
    rows_md, rows_html = [], []
    for p in group:
        if not isinstance(p, dict):
            continue
        pid = p.get("post_id") or "—"
        url = p.get("post_url") or ""
        pub = p.get("published_at") or "—"
        metrics = p.get("metrics", {}) or {}
        rp = p.get("relative_performance", {}) or {}
        # 主指标：优先使用调用方给定的 main_metric
        mm = _PERF_MAIN_METRIC
        mm_label = METRIC_LABELS.get(mm, mm) if mm else "—"
        mm_val = fmt_metric(metrics.get(mm)) if mm else "—"
        rp_val = fmt_float(rp.get(mm)) if (mm and mm in rp and rp.get(mm) is not None) else "—"
        vber = fmt_pct(p.get("view_based_engagement_rate"))
        if url:
            ref_post(url)
            md_link = link_md(url, pid)
            html_link = link_html(url, pid)
        else:
            md_link, html_link = pid, Raw(h_esc(pid))
        rows_md.append([md_link, pub, f"{mm_label}: {mm_val}", rp_val, vber])
        rows_html.append([html_link, Raw(h_esc(pub)),
                          Raw(h_esc(f"{mm_label}: {mm_val}")), Raw(h_esc(rp_val)), Raw(h_esc(vber))])
    if not rows_md:
        return EMPTY_MD, EMPTY_HTML
    return md_table(headers, rows_md), html_table(headers, rows_html)


_PERF_MAIN_METRIC = None  # 由 build_high/low 设置


def build_high_performance(analysis) -> tuple[str, str]:
    global _PERF_MAIN_METRIC
    _PERF_MAIN_METRIC = (analysis.get("meta", {}) or {}).get("main_sort_metric")
    high = analysis.get("high_performance")
    low = analysis.get("low_performance")
    md, html = _render_perf_group(high)
    # 高低表现雷达图：对比两组在各指标上的均值形态（仅作形态对比，不构成因果）
    radar = svg_high_low_radar(high, low, METRIC_FIELDS)
    if radar:
        md += ("\n\n**高低表现指标对比（雷达图）**\n\n"
               "> 说明：以各组在各指标上的均值按列最大值归一化，仅作形态对比，不构成因果结论。")
        html += '<p class="note">高低表现指标对比（雷达图）</p>' + radar
    return md, html


def build_low_performance(analysis) -> tuple[str, str]:
    global _PERF_MAIN_METRIC
    _PERF_MAIN_METRIC = (analysis.get("meta", {}) or {}).get("main_sort_metric")
    group = analysis.get("low_performance")
    return _render_perf_group(group)


def _dist_table(posts, key, label) -> tuple[str, str]:
    counter = Counter()
    for p in posts:
        v = p.get(key)
        if v in (None, "", "unknown"):
            counter["未分类/unknown"] += 1
        else:
            counter[str(v)] += 1
    if not counter:
        return "", ""
    rows = [[k, fmt_int(v)] for k, v in counter.most_common(10)]
    md = f"**{label} 分布**\n\n" + md_table([label, "数量"], rows)
    html = f'<p class="note">{h_esc(label)} 分布</p>' + html_table(
        [label, "数量"], [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in rows])
    return md, html


def build_content_patterns(analysis) -> tuple[str, str]:
    posts = analysis.get("posts", []) if isinstance(analysis, dict) else []
    if not posts:
        return EMPTY_MD, EMPTY_HTML
    blocks = []
    for key, label in [("topic", "主题"), ("format", "内容形式"),
                       ("funnel_stage", "漏斗阶段"), ("hook_type", "开头钩子")]:
        md, html = _dist_table(posts, key, label)
        if md:
            blocks.append((md, html))
    # 栏目 / 合集
    series = Counter()
    for p in posts:
        s = p.get("series_name")
        if s:
            series[str(s)] += 1
    if series:
        rows = [[k, fmt_int(v)] for k, v in series.most_common(10)]
        md = "**栏目 / 合集 分布**\n\n" + md_table(["栏目", "数量"], rows)
        html = '<p class="note">栏目 / 合集 分布</p>' + html_table(
            ["栏目", "数量"], [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in rows])
        blocks.append((md, html))

    if not blocks:
        return EMPTY_MD, EMPTY_HTML
    md = "\n\n".join(b[0] for b in blocks)
    html = "".join(b[1] for b in blocks)
    return md, html


def build_strategy(analysis, profile) -> tuple[str, str]:
    """确定性、基于已计算数据的策略建议（非 LLM、非因果断言）。"""
    tips = []

    cad = _safe_get(analysis, "publish_cadence", default={}) or {}
    ww = cad.get("weekday_weekend", {}) or {}
    if ww:
        wc, ec = int(ww.get("weekday_count") or 0), int(ww.get("weekend_count") or 0)
        if ec and wc:
            dom = "周末" if ec > wc else "工作日"
            tips.append(f"有效样本中 {dom}发布占比更高（周末 {fmt_pct(ww.get('weekend_pct'))} / "
                        f"工作日 {fmt_pct(ww.get('weekday_pct'))}），可在该时段优先排播，但需注意样本量是否足以支撑结论。")
    wd = cad.get("weekday_distribution", {}) or {}
    if wd:
        top_day = max(((int(wd.get(str(i), 0)), i) for i in range(7)), default=(0, 0))
        if top_day[0] > 0:
            tips.append(f"发布最密集的星期为 {WEEKDAY_NAMES[top_day[1]]}（{top_day[0]} 条），"
                        f"可作为稳定更新锚点，但仍应结合表现数据验证。")

    eng = _safe_get(analysis, "engagement", default={}) or {}
    vber = eng.get("view_based_engagement_rate", {}) or {}
    if vber:
        med = vber.get("median")
        if med is not None:
            tips.append(f"基于播放的互动率中位数为 {fmt_pct(med)}（分子=点赞+评论+收藏+分享，"
                        f"分母=播放）。该指标仅反映相对自身水平，不构成因果结论。")
    fber = eng.get("follower_based_engagement_ratio", {}) or {}
    if fber:
        med = fber.get("median")
        fol = eng.get("followers")
        if med is not None and fol:
            tips.append(f"基于粉丝的互动比中位数为 {fmt_pct(med)}（分母=粉丝数 {fmt_int(fol)}），"
                        f"与播放互动率分开解读，避免混用。")

    # 内容形式提示（基于分布，非因果）
    posts = analysis.get("posts", []) if isinstance(analysis, dict) else []
    fmt_counter = Counter()
    for p in posts:
        f = p.get("format")
        if f and f != "unknown":
            fmt_counter[f] += 1
    if fmt_counter:
        top_fmt = fmt_counter.most_common(1)[0][0]
        tips.append(f"已分类内容中最常见的内容形式为「{top_fmt}」，可作为账号内容结构基线；"
                    f"因样本分类状态可能为 pending-model，结论仅供参考。")

    sb = _safe_get(analysis, "sample_boundary", default={}) or {}
    valid = sb.get("valid")
    if isinstance(valid, int) and valid < 15:
        tips.append(f"当前有效样本仅 {valid} 条（<15），高低表现对比与模式结论置信度有限，"
                    f"建议扩大采集周期或数量后再下结论。")

    if not tips:
        return EMPTY_MD, EMPTY_HTML

    md = "\n".join(f"{i}. {t}" for i, t in enumerate(tips, 1))
    html = "<ul class='tight'>" + "".join(f"<li>{h_esc(t)}</li>" for t in tips) + "</ul>"
    return md, html


def build_sample_limits(analysis, profile) -> tuple[str, str]:
    sb = _safe_get(analysis, "sample_boundary", default={}) or {}
    if not sb and not profile:
        return EMPTY_MD, EMPTY_HTML

    rows = [
        ["请求数量", fmt_int(sb.get("requested"))],
        ["实际采集", fmt_int(sb.get("collected"))],
        ["有效数量", fmt_int(sb.get("valid"))],
        ["缺失内容", fmt_int(sb.get("missing"))],
        ["受限内容", fmt_int(sb.get("restricted"))],
        ["被排除标记内容", fmt_int(sb.get("excluded_flagged"))],
    ]
    # 字段可见性（来自 profile）
    fv = (profile or {}).get("field_visibility", {}) or {}
    hidden = [k for k, v in fv.items() if v in ("hidden", "partial")]

    md = md_table(["样本边界", "数值"], rows)
    md += "\n\n> " + DISCLAIMER
    if hidden:
        md += f"\n\n> 受限/不可见字段：{', '.join(hidden)}（相关指标覆盖率相应下调）。"
    md += ("\n\n> 默认排除置顶/转载/投放内容；统计仅基于有效样本，"
           "确定性数字由脚本计算，分类字段由模型填充（可能为 pending-model）。")

    html = html_table(["样本边界", "数值"],
                      [[Raw(h_esc(k)), Raw(h_esc(v))] for k, v in rows])
    notes = [DISCLAIMER]
    if hidden:
        notes.append("受限/不可见字段：" + ", ".join(hidden) + "（相关指标覆盖率相应下调）。")
    notes.append("默认排除置顶/转载/投放内容；统计仅基于有效样本，确定性数字由脚本计算，"
                 "分类字段由模型填充（可能为 pending-model）。")
    html += "".join(f'<p class="note">{h_esc(n)}</p>' for n in notes)
    return md, html


def build_sources(analysis, profile) -> tuple[str, str]:
    urls = []
    prof_url = (profile or {}).get("profile_url")
    if prof_url:
        urls.append(("账号主页", prof_url))
    posts = analysis.get("posts", []) if isinstance(analysis, dict) else []
    for p in posts:
        if isinstance(p, dict) and p.get("post_url"):
            ref_post(p["post_url"])
            urls.append((p.get("post_id") or p["post_url"], p["post_url"]))

    if not urls:
        return EMPTY_MD, EMPTY_HTML
    md = "\n".join(f"- {link_md(u, t)}" for t, u in urls)
    html = "<ul class='tight'>" + "".join(
        f"<li>{link_html(u, t).s}</li>" for t, u in urls) + "</ul>"
    return md, html


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def render_dashboard(template: str, sections_html: dict[str, str]) -> str:
    out = template
    for name in PLACEHOLDERS:
        content = sections_html.get(name) or EMPTY_HTML
        out = out.replace("{{" + name + "}}", content)
    # 兜底：任何残留占位符
    out = re.sub(r"\{\{[^}]*\}\}", '<span class="empty">暂无数据</span>', out)
    return out


def post_render_checks(html: str) -> None:
    # 坏链检查：被引用的内容 URL 不在 known 集合中
    for url in REFERENCED_POST_URLS:
        if url not in KNOWN_POST_URLS:
            warn(f"bad_link: 报告引用了不在 normalized-posts.csv 中的 post_url: {url}")
    # 空图检查：残留外部图片
    for m in re.finditer(r'<img[^>]+src=["\']http', html, re.IGNORECASE):
        warn(f"empty_image: 发现未替换的外部图片标签: {m.group(0)[:80]}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="渲染公开社媒账号分析报告的 Markdown 与 HTML。")
    parser.add_argument("--input", required=True,
                        help="任务目录（含 source/profile.json, normalized-posts.csv, analysis.json）")
    parser.add_argument("--output", default=None,
                        help="输出目录（默认与 --input 相同）")
    parser.add_argument("--template", default=None,
                        help="HTML 模板路径（默认 <skill根>/assets/report-template.html）")
    args = parser.parse_args(argv)

    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve() if args.output else input_dir

    # 模板：默认取脚本所在目录的上级 assets
    if args.template:
        template_path = Path(args.template).resolve()
    else:
        template_path = Path(__file__).resolve().parent.parent / "assets" / "report-template.html"

    if not template_path.exists():
        warn(f"模板不存在: {template_path}；将输出未填充的占位符。")
        template_text = ""
    else:
        template_text = template_path.read_text(encoding="utf-8")

    # 加载数据
    profile = load_json(input_dir / "source" / "profile.json") or {}
    posts_csv = load_posts_csv(input_dir / "normalized-posts.csv")
    analysis = load_json(input_dir / "analysis.json") or {}

    # 构建各节
    builders = {
        "task_info": lambda: build_task_info(analysis, profile, posts_csv),
        "quality_summary": lambda: build_quality_summary(analysis),
        "account_card": lambda: build_account_card(profile),
        "content_structure": lambda: build_content_structure(analysis, posts_csv),
        "publish_cadence": lambda: build_publish_cadence(analysis),
        "metrics_dashboard": lambda: build_metrics_dashboard(analysis),
        "high_performance": lambda: build_high_performance(analysis),
        "low_performance": lambda: build_low_performance(analysis),
        "content_patterns": lambda: build_content_patterns(analysis),
        "strategy": lambda: build_strategy(analysis, profile),
        "sample_limits": lambda: build_sample_limits(analysis, profile),
        "sources": lambda: build_sources(analysis, profile),
    }

    sections_md: dict[str, str] = {}
    sections_html: dict[str, str] = {}
    for name, fn in builders.items():
        try:
            md, html = fn()
        except Exception as exc:  # noqa: BLE001
            warn(f"渲染节 {name} 失败: {exc}")
            md, html = EMPTY_MD, EMPTY_HTML
        sections_md[name] = md or EMPTY_MD
        sections_html[name] = html or EMPTY_HTML

    # 组装 Markdown
    account_name = ((analysis.get("meta", {}) or {}).get("account_name")
                    or (profile or {}).get("account_name") or "未知账号")
    platform = ((analysis.get("meta", {}) or {}).get("platform")
                or (profile or {}).get("platform") or "")
    title = f"公开社媒账号分析报告：{account_name}（{platform}）" if platform else \
        f"公开社媒账号分析报告：{account_name}"
    md_parts = [f"# {title}", "", DISCLAIMER, ""]
    for idx, (name, sec_title) in enumerate(SECTION_DEFS, 1):
        md_parts.append(f"## {idx}. {sec_title}")
        md_parts.append("")
        md_parts.append(sections_md[name])
        md_parts.append("")
    md_text = "\n".join(md_parts).rstrip() + "\n"

    # 组装 HTML
    html_text = render_dashboard(template_text, sections_html)

    # 输出
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "account-analysis-report.md"
    html_path = output_dir / "dashboard.html"
    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")

    # 后置检查
    post_render_checks(html_text)

    print(f"已生成: {md_path}")
    print(f"已生成: {html_path}")
    if WARNINGS:
        print(f"完成，含 {len(WARNINGS)} 条告警。", file=sys.stderr)
    else:
        print("完成，无告警。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
