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
import os
import re
import sys
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


def _load_adapters() -> list[BaseCollector]:
    """加载已实现(非桩)的采集器,返回实例列表。"""
    adapters: list[BaseCollector] = []
    # B站(P0):平级导入
    try:
        from collectors.bilibili import BilibiliCollector

        adapters.append(BilibiliCollector())
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
    # field_visibility 取值严格为 visible/hidden/partial(见 data-schema.md §8)
    return sum(1 for v in vis.values() if v == "visible")


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


def _write_task_json(
    ws: str,
    *,
    platform: str,
    profile_url: str,
    requested_limit: int,
    date_from: str | None,
    date_to: str | None,
    include_comments: bool,
    task_status: str,
    stop_reason: str | None,
    collected_count: int,
    collected_at: str,
) -> None:
    """落盘 task.json(任务状态与停止原因,见 SKILL.md「任务状态与停止原因」)。"""
    payload = {
        "platform": platform,
        "profile_url": profile_url,
        "requested_limit": requested_limit,
        "date_from": date_from,
        "date_to": date_to,
        "include_comments": include_comments,
        "task_status": task_status,
        "stop_reason": stop_reason,
        "collected_count": collected_count,
        "collected_at": collected_at,
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
        "",
    ]
    if posts:
        for fld in ("views", "likes", "comments", "favorites", "shares", "coins", "danmaku"):
            visible = sum(1 for p in posts if p.get(fld) is not None)
            lines.append(f"- 指标 {fld}: {visible}/{len(posts)} 可见")
    if error_log:
        lines.append("")
        lines.append("## 错误日志")
        lines.append("")
        for e in error_log:
            lines.append(
                f"- stage={e.get('stage')} error_code={e.get('error_code')} "
                f"url={e.get('url')} message={e.get('message')} occurred_at={e.get('occurred_at')}"
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
) -> int:
    adapters = _load_adapters()
    if not adapters:
        print("[FAILED] 没有可用适配器(采集器均未实现)", file=sys.stderr)
        return 2
    adapter = _pick(adapters, url)
    if adapter is None:
        # URL 不属于任何已加载平台 → UNSUPPORTED_PLATFORM(见 exceptions.md §1)
        print(f"[FAILED] 无支持的适配器: {url} (stop_reason={SR_UNSUPPORTED})", file=sys.stderr)
        return 2

    platform = adapter.platform
    # 规范化日期范围(中国平台默认 +08:00)
    date_from_iso = _parse_date(date_from)
    date_to_iso = _default_date_to(date_to)
    date_range = None
    if date_from_iso or date_to_iso:
        date_range = (date_from_iso, date_to_iso)

    m = re.search(r"(\d+)", url)
    account = m.group(1) if m else "account"
    date = datetime.now(_BEIJING).strftime("%Y%m%d")
    ws = out_dir or os.path.join(
        os.path.dirname(_HERE), "workspace", f"{platform}-{account}-{date}"
    )
    src = os.path.join(ws, "source")
    os.makedirs(src, exist_ok=True)

    # 执行前回显:平台、采集范围、最大数量、评论开关(见 SKILL.md §1「任务创建」)
    echo_parts = [
        f"platform={platform}",
        f"limit={limit}",
        f"date_range={date_range if date_range else 'unset'}",
        f"include_comments={include_comments}",
    ]
    print(f"[echo] " + " ".join(echo_parts))

    collected_at = datetime.now(_BEIJING).isoformat()
    task_status = "COLLECTING"
    stop_reason: str | None = None
    error_log: list[dict] = []
    posts: list = []
    profile: dict = {}

    # 1) check_access:不绕过任何保护(见 base.py / exceptions.md §2)
    try:
        access = adapter.check_access(url)
        if not access.get("accessible"):
            stop_reason = access.get("stop_reason") or SR_INTERNAL
            # check_access 阶段尚无已采数据,所有受阻场景统一 FAILED(见 exceptions.md §1)
            task_status = "FAILED"
            _write_task_json(
                ws, platform=platform, profile_url=url, requested_limit=limit,
                date_from=date_from_iso, date_to=date_to_iso,
                include_comments=include_comments, task_status=task_status,
                stop_reason=stop_reason, collected_count=0, collected_at=collected_at,
            )
            _write_report(
                adapter, url, profile or {}, posts, ws,
                task_status=task_status, stop_reason=stop_reason,
                error_log=[{
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
            ws, platform=platform, profile_url=url, requested_limit=limit,
            date_from=date_from_iso, date_to=date_to_iso,
            include_comments=include_comments, task_status=task_status,
            stop_reason=stop_reason, collected_count=0, collected_at=collected_at,
        )
        _write_report(
            adapter, url, profile, posts, ws,
            task_status=task_status, stop_reason=stop_reason,
            error_log=[{
                "url": url, "stage": "check_access",
                "error_code": stop_reason, "message": str(e),
                "occurred_at": collected_at, "retryable": False,
            }],
        )
        print(f"[STOP] task_status={task_status} stop_reason={stop_reason} message={e}")
        return 3

    # 2) 内容列表(先于资料,便于回填;失败不阻断资料写入)
    try:
        posts = adapter.collect_post_list(url, limit=limit, date_range=date_range)
    except Exception as e:
        stop_reason = _stop_reason_from_exc(e)
        # 登录/验证/频控/解析失败 → PARTIAL(已有数据保留)或 FAILED(无已采数据)
        task_status = "PARTIAL" if posts else "FAILED"
        error_log.append({
            "url": url, "stage": "collect_post_list",
            "error_code": stop_reason, "message": str(e),
            "occurred_at": collected_at, "retryable": False,
        })
        print(f"[warn] 内容列表采集异常 stop_reason={stop_reason}: {e}", file=sys.stderr)

    # limit 与 date_range 的交集:适配器可能仅应用其一,此处再做一次本地交集过滤
    # (见 SKILL.md §1「采集数量和日期范围同时存在时,取两者共同限定的结果」)
    if posts and (date_from_iso or date_to_iso):
        posts = _filter_by_date(posts, date_from_iso, date_to_iso)
    if posts:
        posts = posts[:limit]

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

    # 4) 落盘原始数据与归一化 CSV(已采集数据必须保留,见 exceptions.md §2 规则 3)
    with open(os.path.join(src, "profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    with open(os.path.join(src, "posts.jsonl"), "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    _write_csv(posts, os.path.join(ws, "normalized-posts.csv"))

    # 5) 评论(可选;失败不阻塞主任务,见 exceptions.md §1.1)
    if include_comments and posts:
        try:
            for p in posts[:limit]:
                adapter.collect_comments(p.get("post_url", ""), limit=20)
            print(f"[OK] 评论采样:已对 {min(limit, len(posts))} 条触发(可选)")
        except Exception as e:
            print(f"[warn] 评论采样异常(不阻塞主任务): {e}", file=sys.stderr)

    # 6) 最终任务状态:无 stop_reason → COMPLETED;有 stop_reason 但有数据 → PARTIAL
    if stop_reason is None:
        task_status = "COMPLETED" if posts else "FAILED"
        if not posts and not profile:
            stop_reason = SR_NO_PUBLIC_CONTENT
            task_status = "FAILED"
    else:
        task_status = "PARTIAL" if posts else "FAILED"

    _write_task_json(
        ws, platform=platform, profile_url=url, requested_limit=limit,
        date_from=date_from_iso, date_to=date_to_iso,
        include_comments=include_comments, task_status=task_status,
        stop_reason=stop_reason, collected_count=len(posts), collected_at=collected_at,
    )
    _write_report(
        adapter, url, profile, posts, ws,
        task_status=task_status, stop_reason=stop_reason, error_log=error_log,
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
    ap.add_argument(
        "--out", default=None, help="输出目录(默认 workspace/<platform>-<account>-<date>/)"
    )
    ap.add_argument("--comments", action="store_true", help="开启评论采样(默认关)")
    ap.add_argument("--date-from", default=None, help="起始日期 YYYY-MM-DD 或 ISO 8601(北京时间)")
    ap.add_argument("--date-to", default=None, help="结束日期 YYYY-MM-DD 或 ISO 8601(北京时间)")
    ap.add_argument(
        "--browser-fallback", action="store_true",
        help="当主路径(直连)因出口 IP 被平台 WAF 封禁而失败时，启用浏览器降级"
             "(经运行环境的真实网络出口再试一次)。需本机/运行环境装有 Chrome/Chromium/Edge。"
             "等价环境变量: BILIBILI_BROWSER_FALLBACK=1。仅作传输层降级，不绕过验证/登录墙/频控。",
    )
    args = ap.parse_args()
    if args.browser_fallback:
        # 透传给采集适配器(Session 构造时读取此环境变量)
        os.environ["BILIBILI_BROWSER_FALLBACK"] = "1"
    limit = max(1, min(args.limit, 100))
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
    ))


if __name__ == "__main__":
    main()
