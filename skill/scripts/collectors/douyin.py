"""抖音公开账号采集适配器（标准库 HTTP + 可选系统浏览器 CDP）。

HTTP/SSR 是快速路径；SSR 缺失或作品结构无法识别时，可用项目自带的标准库
CDP 客户端驱动独立临时浏览器，观察页面公开响应并读取可见作品卡片。两条路径
都映射到统一 `Profile` / `Post` 结构，并如实上抛访问限制 `stop_reason`。

现实约束（务必遵守）：
- 抖音站点是重度 JS 渲染 + 风控（WAF / 滑块 / 签名）站点。标准库 `urllib` 直连
  通常只能拿到 JS 外壳或风控页，拿不到完整 SSR 数据。这是**预期且诚实**的结果：
  解析不到即 `PARSER_FAILED`，触发登录/验证/频控即对应 `stop_reason`。
- **绝不绕过**登录、验证码、滑块或频控；不伪造签名、不重试破解，也不复用
  用户日常浏览器登录态。
- 字段不可见写 `None`（绝不以 `0` 代替未知，见 `data-schema.md` §7/§8）。
- 本适配器只采集、只映射，不分析、不存储（由上层脚本落盘）。

实现要点：
- `supports`：仅认可账号主页（含 `v.douyin.com` 短链 best-effort 解析），拒绝作品/
  搜索/话题页。
- `check_access`：返回 `{"accessible", "reason", "stop_reason"}`，不绕过。
- `collect_profile` / `collect_post_list` / `collect_post_detail`：best-effort 解析
  页面内嵌 `RENDER_DATA`（URL 编码 JSON）；解析失败或受限如实上抛。
- `collect_comments`：覆盖基类；明确空列表返回 `[]`，不可用则上抛内容级原因。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any


from ._constants import (
    DOUYIN_PAGE_STATE_PATTERNS,
    PUBLIC_ALL_DEFAULT_MAX_ITEMS,
    PUBLIC_ALL_DEFAULT_MAX_SCROLLS,
    PUBLIC_ALL_DEFAULT_MAX_SECONDS,
    PUBLIC_ALL_HARD_MAX_ITEMS,
    PUBLIC_LIMIT_DEFAULT,
    STOP_ACCESS_RESTRICTED,
    STOP_ACCOUNT_UNAVAILABLE,
    STOP_INTERNAL,
    STOP_LOGIN,
    STOP_NO_PUBLIC_CONTENT,
    STOP_PARSER_FAILED,
    STOP_UNSUPPORTED,
    STOP_VERIFICATION,
    validate_public_all_budgets,
    validate_public_limit,
)
from .base import BaseCollector
from .url_policy import (
    canonical_item_url,
    canonical_profile_url,
    sanitize_routing_url,
)


# 抖音公开接口 / 主页均使用北京时间（+08:00）
_BEIJING = timezone(timedelta(hours=8))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_TIMEOUT = 12

# Shared with the browser transport so both paths use identical priority.
_RESTRICTION_PATTERNS = DOUYIN_PAGE_STATE_PATTERNS


class DouyinError(Exception):
    """采集错误，携带 stop_reason 和可安全保留的部分结果。"""

    def __init__(
        self,
        stop_reason: str,
        message: str,
        raw: Any = None,
        partial_posts: list[dict[str, Any]] | None = None,
        diagnostic_code: str | None = None,
    ):
        super().__init__(message)
        self.stop_reason = stop_reason
        self.message = message
        self.raw = raw
        self.partial_posts = list(partial_posts or [])
        self.diagnostic_code = diagnostic_code


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def _now_iso() -> str:
    """当前北京时间 ISO 8601。"""
    return datetime.now(_BEIJING).isoformat()


def _ts_to_iso(ts: Any) -> str | None:
    """Unix 秒 → 北京时间 ISO 8601；失败返回 None。"""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=_BEIJING).isoformat()
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def _int(v: Any) -> int | None:
    """宽松数字解析：支持 '1.2万' / '3.4亿' / 纯数字；失败返回 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return None
    mult = 1
    if "亿" in s:
        mult = 100_000_000
    if "万" in s:
        mult = 10_000
    s = s.replace("亿", "").replace("万", "").replace(",", "").replace("+", "").strip()
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _public_boolean(source: dict[str, Any], *keys: str) -> bool | None:
    """Preserve explicit public boolean evidence and leave absence unknown."""
    values = [source[key] for key in keys if isinstance(source.get(key), bool)]
    if True in values:
        return True
    if False in values:
        return False
    return None


def _extract_hashtags(desc: Any, text_extra: Any) -> list[str]:
    """从文案与 text_extra 抽取话题标签，去重保序。"""
    tags: list[str] = []
    if isinstance(text_extra, list):
        for item in text_extra:
            name = (item or {}).get("hashtag_name") if isinstance(item, dict) else None
            if name and name not in tags:
                tags.append(name)
    if isinstance(desc, str):
        for m in re.findall(r"#([^#\s]+)#?", desc):
            if m and m not in tags:
                tags.append(m)
    return tags


def _extract_render_data(html: str) -> dict | None:
    """从页面提取内嵌 RENDER_DATA（URL 编码 JSON）及多变体 SSR 数据。

    支持节点：<script id="RENDER_DATA">、_ROUTER_DATA、_SSR_DATA、__INIT_DATA、__INITIAL_STATE__。
    解析失败（无节点 / 需风控验证 / JS虚拟机渲染）返回 None，由调用方据实判定为 PARSER_FAILED。
    """
    if not html:
        return None

    # 1. 经典 RENDER_DATA 节点
    m = re.search(
        r'<script[^>]*id=["\'](?:RENDER_DATA|_SSR_DATA|__INIT_DATA)["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.I,
    )
    raw = m.group(1) if m else None
    if raw:
        try:
            decoded = urllib.parse.unquote(raw)
            return json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass

    # 2. window 全局变量挂载变体 (window._ROUTER_DATA / window.__INITIAL_STATE__)
    patterns = [
        r"window\._ROUTER_DATA\s*=\s*(\{.*?\});?\s*</script>",
        r"window\._SSR_DATA\s*=\s*(\{.*?\});?\s*</script>",
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*</script>",
    ]
    for p in patterns:
        m2 = re.search(p, html, re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group(1))
            except (json.JSONDecodeError, ValueError):
                continue

    return None


def _detect_restriction(html: str) -> str | None:
    """扫描页面文本，返回命中的 stop_reason；无限制返回 None。"""
    if not html:
        return None
    for pattern, reason in _RESTRICTION_PATTERNS:
        if pattern.search(html):
            return reason
    return None


def _dig(data: dict | None, *path: str) -> Any:
    """安全按路径取值，任一环节缺失/非 dict 即返回 None。"""
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# --------------------------------------------------------------------------
# 适配器
# --------------------------------------------------------------------------
class DouyinCollector(BaseCollector):
    platform = "douyin"

    def __init__(self, browser_fallback: bool = True, browser_collect=None):
        """Configure the optional, dependency-free browser collection fallback."""
        if browser_collect is None:
            from ._douyin_browser_transport import collect_account_page

            browser_collect = collect_account_page
        self.browser_fallback = bool(browser_fallback)
        self._browser_collect = browser_collect
        self._collection_coverage: dict[str, Any] = {}

    # -- 路由 ---------------------------------------------------------------
    def supports(self, url: str) -> bool:
        """仅支持抖音账号主页（含短链 best-effort 解析）；拒绝作品/搜索/其他。"""
        u = sanitize_routing_url(url)
        if u is None:
            return False
        try:
            parsed = urllib.parse.urlsplit(u)
        except ValueError:
            return False
        host = parsed.hostname
        path = parsed.path

        if host == "v.douyin.com":
            return re.fullmatch(r"/[A-Za-z0-9_-]+/?", path) is not None

        return canonical_profile_url("douyin", u) is not None

    def canonicalize_profile_url(self, url: str) -> str | None:
        """Resolve a sanitized short link once, then apply strict profile policy."""
        safe_url = sanitize_routing_url(url)
        if safe_url is None:
            return None
        direct = canonical_profile_url("douyin", safe_url)
        if direct is not None:
            return direct
        parsed = urllib.parse.urlsplit(safe_url)
        if (
            parsed.hostname != "v.douyin.com"
            or re.fullmatch(r"/[A-Za-z0-9_-]+/?", parsed.path) is None
        ):
            return None
        final_url = self._resolve_final_url(safe_url)
        return canonical_profile_url("douyin", final_url)

    @staticmethod
    def _is_user_url(url: str) -> bool:
        """判定解析后的长链是否为账号主页。"""
        return canonical_profile_url("douyin", url) is not None

    @staticmethod
    def _resolve_final_url(url: str) -> str | None:
        """跟随重定向取最终落点（用于短链判定），不绕过任何保护。"""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.geturl()
        except Exception:
            return None

    # -- 传输 ---------------------------------------------------------------
    def _fetch(self, url: str) -> str:
        """urllib 取页面文本；HTTP/网络错误如实上抛对应 stop_reason。"""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.douyin.com/",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise DouyinError(
                    STOP_ACCESS_RESTRICTED, f"HTTP {e.code} 访问受限: {url}"
                )
            if e.code in (404, 410):
                raise DouyinError(
                    STOP_ACCOUNT_UNAVAILABLE, f"HTTP {e.code} 账号/页面不存在: {url}"
                )
            raise DouyinError(STOP_ACCESS_RESTRICTED, f"HTTP {e.code}: {url}")
        except urllib.error.URLError as e:
            # 网络层错误（DNS/连接被拒等），按访问受限如实上抛，不重试绕过。
            raise DouyinError(
                STOP_ACCESS_RESTRICTED, f"网络错误: {e.reason} ({url})"
            )

    # -- 访问检查（不绕过） -------------------------------------------------
    def check_access(self, url: str) -> dict[str, Any]:
        """返回 {'accessible', 'reason', 'stop_reason'}，不绕过任何保护。

        - 先路由：非账号主页 → accessible=False, stop_reason=UNSUPPORTED_PLATFORM。
        - 再抓取：命中登录/验证/频控/账号不可用 → accessible=False + 对应 stop_reason。
        - 可访问但无可用结构 → accessible=True, stop_reason=None（解析成败由
          collect_* 阶段判定，不在此阻断）。
        """
        if not self.supports(url):
            return {
                "accessible": False,
                "reason": "URL 不属于支持的抖音账号主页（或为作品/搜索/短链指向作品）",
                "stop_reason": STOP_UNSUPPORTED,
            }
        try:
            html = self._fetch(url)
        except DouyinError as e:
            return {
                "accessible": False,
                "reason": e.message,
                "stop_reason": e.stop_reason,
            }
        reason = _detect_restriction(html)
        if reason:
            return {
                "accessible": False,
                "reason": f"页面命中访问限制标记: {reason}",
                "stop_reason": reason,
            }
        return {
            "accessible": True,
            "reason": "账号主页可访问（是否含可解析数据由采集阶段判定）",
            "stop_reason": None,
        }

    @staticmethod
    def _extract_sec_uid(url: str) -> str | None:
        m = re.search(r"/(?:user|share/user)/([A-Za-z0-9_\-]+)", url)
        return m.group(1) if m else None

    def _fetch_profile_via_iesdouyin_api(self, sec_uid: str, url: str) -> dict[str, Any] | None:
        """fallback 降级调用 iesdouyin 公开 API 提取公开资料。"""
        if not sec_uid:
            return None
        api_url = f"https://www.iesdouyin.com/web/api/v2/user/info/?sec_uid={sec_uid}"
        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                res_text = resp.read().decode("utf-8", errors="replace")
                data = json.loads(res_text)
                ui = data.get("user_info")
                if not ui:
                    return None
                raw = {
                    "platform": "douyin",
                    "account_id": ui.get("unique_id") or ui.get("short_id") or sec_uid,
                    "account_name": ui.get("nickname"),
                    "profile_url": url,
                    "bio": ui.get("signature") or None,
                    "verified": bool(ui.get("custom_verify") or ui.get("enterprise_verify_reason") or ui.get("verification_type")),
                    "followers": _int(ui.get("follower_count") or ui.get("mplatform_followers_count")),
                    "post_count": _int(ui.get("aweme_count")),
                    "platform_metrics": {
                        "total_likes": _int(ui.get("total_favorited")),
                        "sec_uid": sec_uid,
                        "unique_id": ui.get("unique_id"),
                        "enterprise_verify_reason": ui.get("enterprise_verify_reason"),
                    },
                    "collected_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                    "field_visibility": {
                        "account_name": "visible" if ui.get("nickname") else "hidden",
                        "bio": "visible" if ui.get("signature") else "hidden",
                        "followers": "visible" if (ui.get("follower_count") or ui.get("mplatform_followers_count")) is not None else "hidden",
                        "post_count": "visible" if ui.get("aweme_count") is not None else "hidden",
                    }
                }
                return self.normalize_profile(raw)
        except Exception:
            return None

    # -- 资料 ---------------------------------------------------------------
    def collect_profile(self, url: str) -> dict[str, Any]:
        """采集公开账号信息并归一化为统一 Profile。

        命中任务级限制时抛 DouyinError(stop_reason)；页面可访问但无法解析用户结构
        时自动触发 iesdouyin 公开 API 降级；全不可用时抛 PARSER_FAILED。
        """
        if not self.supports(url):
            raise DouyinError(STOP_UNSUPPORTED, f"不支持的账号主页 URL: {url}")
        html = self._fetch(url)
        # 先判定任务级限制（优先于解析失败）。
        restriction = _detect_restriction(html)
        if restriction:
            raise DouyinError(restriction, f"采集资料时命中访问限制: {restriction}")

        data = _extract_render_data(html)
        user = self._find_user(data) if data else None
        if not user:
            sec_uid = self._extract_sec_uid(url)
            if sec_uid:
                fallback = self._fetch_profile_via_iesdouyin_api(sec_uid, url)
                if fallback:
                    return fallback
            raise DouyinError(
                STOP_PARSER_FAILED, "RENDER_DATA 中未识别到用户结构（可能为 JS 外壳页）"
            )

        raw = self._build_profile_raw(url, user)
        return self.normalize_profile(raw)

    # -- 作品列表 -----------------------------------------------------------
    def _collect_posts_via_browser(
        self,
        url: str,
        limit: int,
        date_range: tuple[str | None, str | None] | None,
    ) -> list[dict[str, Any]]:
        """Run the optional browser path and preserve its status semantics."""
        if not self.browser_fallback:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "账号主页 SSR 缺失或作品列表结构无法识别，且浏览器降级已禁用",
            )
        try:
            result = self._browser_collect(
                url=url,
                limit=limit,
                date_range=date_range,
            )
        except Exception as exc:
            code = (
                "BROWSER_UNAVAILABLE"
                if "未找到可用的浏览器" in str(exc)
                else "BROWSER_TRANSPORT_FAILED"
            )
            raise DouyinError(
                STOP_PARSER_FAILED,
                f"抖音浏览器降级失败: {exc}",
                diagnostic_code=code,
            ) from exc

        valid_items = self._validated_aweme_items(result.aweme_items)
        posts = [
            self.normalize_post(
                self._build_post_raw(
                    url,
                    item,
                    source=str(
                        item.get("_collection_source") or result.source or "network"
                    ),
                )
            )
            for item in valid_items
        ]
        if date_range:
            posts = self._filter_by_date(posts, date_range)
        posts = posts[:limit]
        if result.restriction:
            raise DouyinError(
                result.restriction,
                f"浏览器采集中止: {result.restriction}",
                raw=result.diagnostics,
                partial_posts=posts,
                diagnostic_code=result.diagnostic_code,
            )
        if result.diagnostic_code:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "浏览器采集完成，但资源清理失败",
                raw=result.diagnostics,
                partial_posts=posts,
                diagnostic_code=result.diagnostic_code,
            )
        if result.aweme_items and not valid_items:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "浏览器作品载荷未包含有效的数字平台作品 ID",
                partial_posts=[],
                diagnostic_code="INVALID_PLATFORM_POST_ID",
            )
        if not posts:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "浏览器未识别到可验证的作品结构",
                raw=result.diagnostics,
            )
        return posts

    @staticmethod
    def _sanitize_collection_coverage(value: Any) -> dict[str, Any]:
        """Keep only the bounded coverage ledger; never retain transport secrets."""
        if not isinstance(value, dict):
            return {}
        count_fields = (
            "observed_page_count",
            "observed_post_count",
            "cursor_fingerprint_count",
            "repeated_cursor_count",
            "range_match_count",
        )
        allowed_stops = {
            "terminal_page",
            "idle",
            "timeout",
            "repeated_cursor",
            "max_items",
            "max_scrolls",
            "date_lower_bound",
            "limit",
        }
        clean: dict[str, Any] = {}
        requested_all = value.get("requested_all") is True
        terminal_observed = value.get("terminal_page_observed") is True
        clean["requested_all"] = requested_all
        clean["terminal_page_observed"] = terminal_observed
        for key in count_fields:
            field_value = value.get(key)
            if isinstance(field_value, int) and not isinstance(field_value, bool):
                clean[key] = max(0, field_value)
        max_items = value.get("max_items")
        if (
            isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and 1 <= max_items <= PUBLIC_ALL_HARD_MAX_ITEMS
        ):
            clean["max_items"] = max_items
        stop_condition = value.get("stop_condition")
        if isinstance(stop_condition, str) and stop_condition in allowed_stops:
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

    def get_collection_coverage(self) -> dict[str, Any]:
        """Return a detached copy of the current sanitized coverage ledger."""
        return dict(self._collection_coverage)

    def collect_all_post_list(
        self,
        url: str,
        date_range: tuple[str | None, str | None] | None = None,
        max_items: int = PUBLIC_ALL_DEFAULT_MAX_ITEMS,
        max_seconds: float = PUBLIC_ALL_DEFAULT_MAX_SECONDS,
        max_scrolls: int = PUBLIC_ALL_DEFAULT_MAX_SCROLLS,
    ) -> list[dict[str, Any]]:
        """Passively observe public post-list pages until a verified terminal page."""
        self._collection_coverage = {}
        if not self.supports(url):
            raise DouyinError(STOP_UNSUPPORTED, f"不支持的账号主页 URL: {url}")
        max_items, max_seconds, max_scrolls = validate_public_all_budgets(
            max_items, max_seconds, max_scrolls
        )
        self._collection_coverage = {
            "requested_all": True,
            "max_items": max_items,
        }
        if not self.browser_fallback:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "全量作品采集需要启用公开浏览器传输层",
                diagnostic_code="BROWSER_DISABLED",
            )
        try:
            result = self._browser_collect(
                url=url,
                limit=max_items,
                date_range=date_range,
                all_posts=True,
                max_seconds=max_seconds,
                max_scrolls=max_scrolls,
            )
        except Exception as exc:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "抖音全量浏览器采集失败",
                diagnostic_code="BROWSER_TRANSPORT_FAILED",
            ) from exc

        self._collection_coverage = self._sanitize_collection_coverage(
            getattr(result, "coverage", {})
        )
        self._collection_coverage["max_items"] = max_items
        valid_items = self._validated_aweme_items(result.aweme_items)
        posts = [
            self.normalize_post(
                self._build_post_raw(
                    url,
                    item,
                    source=str(
                        item.get("_collection_source") or result.source or "network"
                    ),
                )
            )
            for item in valid_items
        ]
        if date_range:
            posts = self._filter_by_date(posts, date_range)
        posts = posts[:max_items]
        self._collection_coverage["observed_post_count"] = len(valid_items)
        self._collection_coverage["range_filter_applied"] = date_range is not None
        self._collection_coverage["range_match_count"] = len(posts)
        self._collection_coverage["range_no_match"] = bool(
            date_range is not None and valid_items and not posts
        )

        if result.restriction:
            raise DouyinError(
                result.restriction,
                f"浏览器全量采集中止: {result.restriction}",
                partial_posts=posts,
                diagnostic_code=result.diagnostic_code,
            )
        if result.diagnostic_code:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "全量作品采集完成，但资源清理失败",
                partial_posts=posts,
                diagnostic_code=result.diagnostic_code,
            )
        if result.aweme_items and not valid_items:
            self._collection_coverage["terminal_page_observed"] = False
            self._collection_coverage["is_exhaustive"] = False
            raise DouyinError(
                STOP_PARSER_FAILED,
                "浏览器作品载荷未包含有效的数字平台作品 ID",
                partial_posts=[],
                diagnostic_code="INVALID_PLATFORM_POST_ID",
            )
        if not self._collection_coverage.get("is_exhaustive", False):
            raise DouyinError(
                STOP_PARSER_FAILED,
                "全量作品采集在安全边界停止，结果不具完备性",
                partial_posts=posts,
                diagnostic_code="ALL_POSTS_INCOMPLETE",
            )
        if not valid_items:
            raise DouyinError(
                STOP_NO_PUBLIC_CONTENT,
                "公开作品列表已到末页，账号没有可验证的公开作品",
                partial_posts=[],
            )
        return posts

    def collect_post_list(
        self,
        url: str,
        limit: int = PUBLIC_LIMIT_DEFAULT,
        date_range: tuple[str | None, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        """采集作品摘要列表（标记 is_pinned），归一化后返回。

        Best-effort：从 RENDER_DATA 抽取作品数组。尊重 limit 与 date_range。
        命中任务级限制抛 DouyinError；单条缺失不影响整体（保持 null，不臆造）。
        """
        self._collection_coverage = {}
        limit = validate_public_limit(limit)
        if not self.supports(url):
            raise DouyinError(STOP_UNSUPPORTED, f"不支持的账号主页 URL: {url}")
        html = self._fetch(url)
        restriction = _detect_restriction(html)
        if restriction:
            raise DouyinError(restriction, f"采集列表时命中访问限制: {restriction}")

        data = _extract_render_data(html)
        aweme_list = self._find_aweme_list(data) if data is not None else None
        if data is None or aweme_list is None:
            return self._collect_posts_via_browser(url, limit, date_range)

        if len(aweme_list) == 0:
            raise DouyinError(
                STOP_NO_PUBLIC_CONTENT,
                "账号主页明确显示没有公开作品",
            )

        valid_items = self._validated_aweme_items(aweme_list)
        if aweme_list and not valid_items:
            raise DouyinError(
                STOP_PARSER_FAILED,
                "SSR 作品载荷未包含有效的数字平台作品 ID",
                partial_posts=[],
                diagnostic_code="INVALID_PLATFORM_POST_ID",
            )
        posts: list[dict[str, Any]] = []
        for item in valid_items:
            if len(posts) >= limit:
                break
            raw = self._build_post_raw(url, item, source="list")
            posts.append(self.normalize_post(raw))

        if date_range:
            posts = self._filter_by_date(posts, date_range)
        return posts[:limit]

    @classmethod
    def _validated_aweme_items(cls, items: Any) -> list[dict[str, Any]]:
        """Keep numeric platform items and fill duplicate gaps without overwrites."""
        by_id: dict[str, dict[str, Any]] = {}
        if not isinstance(items, list):
            return []
        for item in items:
            if not isinstance(item, dict):
                continue
            post_id = str(item.get("aweme_id") or item.get("aweme_id_str") or "")
            if re.fullmatch(r"\d+", post_id) is None:
                continue
            if post_id not in by_id:
                by_id[post_id] = dict(item)
                continue
            cls._merge_missing_values(by_id[post_id], item)
        return list(by_id.values())

    @classmethod
    def _merge_missing_values(cls, target: dict[str, Any], incoming: dict[str, Any]) -> None:
        for key, value in incoming.items():
            current = target.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                cls._merge_missing_values(current, value)
            elif cls._missing_value(current) and not cls._missing_value(value):
                target[key] = value

    @staticmethod
    def _missing_value(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    # -- 单条详情 -----------------------------------------------------------
    def collect_post_detail(self, post_url: str) -> dict[str, Any]:
        """采集单条作品详情并归一化。播放数可能不公开 → views=None。"""
        canonical_url = canonical_item_url("douyin", post_url)
        if canonical_url is None:
            raise DouyinError(STOP_UNSUPPORTED, "无效的作品 URL")
        expected_post_id = canonical_url.rstrip("/").rsplit("/", 1)[-1]
        html = self._fetch(canonical_url)
        restriction = _detect_restriction(html)
        if restriction:
            raise DouyinError(restriction, f"采集作品详情时命中访问限制: {restriction}")

        data = _extract_render_data(html)
        if data is None:
            raise DouyinError(STOP_PARSER_FAILED, "作品页可访问但无 RENDER_DATA，无法解析")
        aweme = self._find_aweme_detail(data, expected_post_id)
        if not aweme:
            raise DouyinError(
                STOP_PARSER_FAILED, "RENDER_DATA 中未识别到单条作品结构"
            )
        raw = self._build_post_raw(canonical_url, aweme, source="detail")
        return self.normalize_post(raw)

    # -- 评论（覆盖基类，best-effort） -------------------------------------
    def collect_comments(
        self, post_url: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """公开评论采样；区分明确空结果与不可用，均不绕过保护。"""
        canonical_url = canonical_item_url("douyin", post_url)
        if canonical_url is None:
            raise DouyinError(STOP_UNSUPPORTED, "无效的作品 URL")
        html = self._fetch(canonical_url)
        restriction = _detect_restriction(html)
        if restriction:
            raise DouyinError(restriction, "公开评论采样命中访问限制")
        data = _extract_render_data(html)
        if data is None:
            raise DouyinError(STOP_PARSER_FAILED, "作品页无可解析公开数据")
        comments_raw = self._find_comments(data)
        if comments_raw is None:
            raise DouyinError("COMMENTS_UNAVAILABLE", "作品页未提供公开评论结构")
        for comment in comments_raw[:limit]:
            if not isinstance(comment, dict):
                raise DouyinError("COMMENTS_UNAVAILABLE", "公开评论结构无效")
            comment_id = comment.get("cid") or comment.get("id")
            user = comment.get("user")
            text = comment.get("text") or comment.get("content")
            if (
                isinstance(comment_id, bool)
                or not isinstance(comment_id, (str, int))
                or (user is not None and not isinstance(user, dict))
                or (text is not None and not isinstance(text, str))
            ):
                raise DouyinError("COMMENTS_UNAVAILABLE", "公开评论结构无效")
        out: list[dict[str, Any]] = []
        for c in comments_raw[:limit]:
            out.append(
                {
                    "comment_id": c.get("cid") or c.get("id"),
                    "post_url": canonical_url,
                    "author": (c.get("user") or {}).get("nickname"),
                    "text": c.get("text") or c.get("content"),
                    "likes": _int(c.get("digg_count")),
                    "published_at": _ts_to_iso(c.get("create_time")),
                    "collected_at": _now_iso(),
                }
            )
        return out

    # ----------------------------------------------------------------------
    # 内部解析（best-effort，安全取值）
    # ----------------------------------------------------------------------
    def _find_user(self, data: dict) -> dict | None:
        """在 RENDER_DATA 中定位用户结构（多种可能的嵌套位置）。"""
        candidates = [
            _dig(data, "user", "user"),
            _dig(data, "userInfo"),
            _dig(data, "app", "user", "user"),
            _dig(data, "8", "user", "user"),
        ]
        for c in candidates:
            if isinstance(c, dict) and (c.get("sec_uid") or c.get("unique_id")):
                return c
        # 兜底：全树浅搜含 sec_uid 的 dict。
        found = self._search_key(data, "sec_uid")
        if isinstance(found, dict):
            return found
        return None

    def _find_aweme_list(self, data: dict) -> list | None:
        """在 RENDER_DATA 中定位作品列表数组。"""
        candidates = [
            _dig(data, "user", "post", "data"),
            _dig(data, "user", "user", "awemeList"),
            _dig(data, "app", "user", "post", "data"),
            _dig(data, "8", "user", "post", "data"),
        ]
        for c in candidates:
            if isinstance(c, list):
                return c
        found = self._search_list_of_key(data, "aweme_id")
        return found

    def _find_aweme_detail(self, data: dict, expected_post_id: str) -> dict | None:
        """在 RENDER_DATA 中定位单条作品结构。"""
        candidates = [
            _dig(data, "aweme", "detail"),
            _dig(data, "video", "aweme"),
            _dig(data, "app", "aweme", "detail"),
            _dig(data, "aweme_detail"),
        ]
        for c in candidates:
            if isinstance(c, dict) and str(c.get("aweme_id") or "") == expected_post_id:
                return c
        return None

    def _find_comments(self, data: dict) -> list | None:
        """在 RENDER_DATA 中定位评论列表（存在时）。"""
        candidates = [
            _dig(data, "comment", "data", "comments"),
            _dig(data, "app", "comment", "data", "comments"),
        ]
        for c in candidates:
            if isinstance(c, list):
                return c
        return None

    @staticmethod
    def _search_key(node: Any, key: str, _depth: int = 0) -> Any:
        """整树浅搜首个含指定 key 的 dict 值（深度受限，避免爆栈）。"""
        if _depth > 6 or not isinstance(node, dict):
            return None
        if key in node:
            return node[key]
        for v in node.values():
            if isinstance(v, dict):
                r = DouyinCollector._search_key(v, key, _depth + 1)
                if r is not None:
                    return r
            elif isinstance(v, list) and _depth < 4:
                for item in v:
                    r = DouyinCollector._search_key(item, key, _depth + 1)
                    if r is not None:
                        return r
        return None

    @staticmethod
    def _search_list_of_key(node: Any, key: str, _depth: int = 0) -> list | None:
        """整树查找含指定 key 的 dict 元素组成的列表（best-effort）。"""
        if _depth > 6 or not isinstance(node, (dict, list)):
            return None
        if isinstance(node, list):
            items = [i for i in node if isinstance(i, dict) and key in i]
            if items:
                return items
            for i in node:
                r = DouyinCollector._search_list_of_key(i, key, _depth + 1)
                if r:
                    return r
            return None
        for v in node.values():
            r = DouyinCollector._search_list_of_key(v, key, _depth + 1)
            if r:
                return r
        return None

    # ----------------------------------------------------------------------
    # 统一字段构建（供 base.normalize_* 使用）
    # ----------------------------------------------------------------------
    @staticmethod
    def _build_profile_raw(url: str, user: dict) -> dict:
        sec_uid = user.get("sec_uid")
        unique_id = user.get("unique_id")  # 抖音号（用户自定义，可能为空）
        account_id = unique_id or sec_uid  # 优先抖音号，回退 sec_uid
        verified = DouyinCollector._extract_verified(user)
        followers = _int(user.get("follower_count") or user.get("followers"))
        post_count = _int(user.get("aweme_count") or user.get("aweme_counts"))
        total_likes = _int(user.get("total_favorited"))
        return {
            "platform": "douyin",
            "account_id": account_id,
            "account_name": user.get("nickname"),
            "profile_url": url,
            "bio": user.get("signature"),
            "verified": verified,
            "followers": followers,
            "post_count": post_count,
            "platform_metrics": {
                "total_likes": total_likes,
                "sec_uid": sec_uid,
                "unique_id": unique_id,
                "uid": user.get("uid"),
            },
            "collected_at": _now_iso(),
            "field_visibility": {
                "followers": "visible" if followers is not None else "hidden",
                "post_count": "visible" if post_count is not None else "hidden",
            },
        }

    @staticmethod
    def _extract_verified(user: dict) -> bool | str:
        """认证信息：有企业/个人认证文案 → 返回文案；否则布尔。"""
        enterprise = user.get("enterprise_verify_reason")
        custom = user.get("custom_verify")
        if enterprise:
            return enterprise
        if custom:
            return custom
        v = user.get("verification") or user.get("verify_info")
        if isinstance(v, dict):
            vtype = v.get("type")
            if vtype not in (None, 0, -1):
                return True
        return False

    @staticmethod
    def _build_post_raw(url: str, aweme: dict, source: str) -> dict:
        from ._douyin_browser_transport import canonical_post_url_for_item

        desc = aweme.get("desc") or ""
        text_extra = aweme.get("text_extra")
        statistics = aweme.get("statistics") or {}
        video = aweme.get("video") or {}
        is_top = _public_boolean(aweme, "is_top", "is_top_aweme")
        is_repost = _public_boolean(aweme, "is_repost", "is_forward")
        is_ad = _public_boolean(aweme, "is_ad", "is_commerce")
        # 图文/笔记 best-effort 判定。
        content_type = "video"
        if aweme.get("images") and not video:
            content_type = "image_text"
        collection = aweme.get("mix_info") or aweme.get("collection")
        collection_name = (collection or {}).get("mix_name") if isinstance(collection, dict) else None
        single_text = (desc or "").split("\n")[0] if isinstance(desc, str) else None
        post_id = str(aweme.get("aweme_id") or aweme.get("aweme_id_str") or "")
        post_url = canonical_post_url_for_item(aweme, post_id)
        collection_source = str(
            aweme.get("_collection_source") or source or "unknown"
        )
        return {
            "platform": "douyin",
            "post_id": post_id,
            "post_url": post_url,
            "published_at": _ts_to_iso(aweme.get("create_time")),
            "content_type": content_type,
            "title": single_text,
            "text": desc,
            "duration_seconds": (_int(video.get("duration")) // 1000) if video.get("duration") is not None else None,
            "hashtags": _extract_hashtags(desc, text_extra),
            "is_pinned": is_top,
            "is_repost": is_repost,
            "is_promoted": is_ad,
            # 播放可能不公开 → None（绝不以互动数反推）。
            "views": _int(statistics.get("play_count")),
            "likes": _int(statistics.get("digg_count")),
            "comments": _int(statistics.get("comment_count")),
            "favorites": _int(statistics.get("collect_count")),
            "shares": _int(statistics.get("share_count")),
            "coins": None,
            "danmaku": None,
            "collection_status": "SUCCESS",
            "collected_at": _now_iso(),
            "source_url": post_url,
            "platform_metrics": {
                "collection_name": collection_name,
                "aweme_type": aweme.get("aweme_type"),
                "collection_source": collection_source,
                "visible_is_pinned": (
                    True
                    if collection_source == "dom" and aweme.get("is_top") is True
                    else None
                    if collection_source == "dom"
                    else is_top
                ),
            },
        }

    @staticmethod
    def _filter_by_date(
        posts: list[dict[str, Any]],
        date_range: tuple[str | None, str | None],
    ) -> list[dict[str, Any]]:
        """按 published_at（ISO 8601，+08:00）做 best-effort 过滤。"""
        df, dt = date_range

        def parse(iso: str | None) -> datetime | None:
            if not iso:
                return None
            try:
                return datetime.fromisoformat(iso)
            except (ValueError, TypeError):
                return None

        lo = parse(df)
        hi = parse(dt)
        out: list[dict[str, Any]] = []
        for p in posts:
            pa = parse(p.get("published_at"))
            if pa is None:
                # 无法判定时间的保留（不臆造排除）。
                out.append(p)
                continue
            if lo is not None and pa < lo:
                continue
            if hi is not None and pa > hi:
                continue
            out.append(p)
        return out
