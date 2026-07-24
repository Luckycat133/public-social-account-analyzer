"""抖音公开账号采集适配器（P0）。

仅用标准库 `urllib` 访问 douyin.com / iesdouyin.com / v.douyin.com 的**公开**
账号主页，把可解析到的字段映射到统一 `Profile` / `Post` 结构（见
`data-schema.md`），并如实上抛访问限制 `stop_reason`（见 `exceptions.md`）。

现实约束（务必遵守）：
- 抖音站点是重度 JS 渲染 + 风控（WAF / 滑块 / 签名）站点。标准库 `urllib` 直连
  通常只能拿到 JS 外壳或风控页，拿不到完整 SSR 数据。这是**预期且诚实**的结果：
  解析不到即 `PARSER_FAILED`，触发登录/验证/频控即对应 `stop_reason`。
- **绝不绕过**登录、验证码、滑块或频控；不伪造签名、不模拟浏览器、不重试破解。
- 字段不可见写 `None`（绝不以 `0` 代替未知，见 `data-schema.md` §7/§8）。
- 本适配器只采集、只映射，不分析、不存储（由上层脚本落盘）。

实现要点：
- `supports`：仅认可账号主页（含 `v.douyin.com` 短链 best-effort 解析），拒绝作品/
  搜索/话题页。
- `check_access`：返回 `{"accessible", "reason", "stop_reason"}`，不绕过。
- `collect_profile` / `collect_post_list` / `collect_post_detail`：best-effort 解析
  页面内嵌 `RENDER_DATA`（URL 编码 JSON）；解析失败或受限如实上抛。
- `collect_comments`：覆盖基类，best-effort，任何限制/错误一律返回 `[]`。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


from .base import BaseCollector
from ._constants import (  # 共享常量（re-export：测试通过 from collectors.douyin import STOP_* 仍可用）
    BEIJING_TZ as _BEIJING,
    STOP_LOGIN,
    STOP_VERIFICATION,
    STOP_ACCOUNT_UNAVAILABLE,
    STOP_ACCESS_RESTRICTED,
    STOP_PARSER_FAILED,
    STOP_NO_PUBLIC_CONTENT,
    STOP_UNSUPPORTED,
    STOP_INTERNAL,
)
from ._utils import (  # 共享工具函数（本地别名以最小化调用点改动）
    now_iso as _now_iso,
    parse_int as _int,
    ts_to_iso as _ts_to_iso,
    extract_hashtags,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_TIMEOUT = 12

# 访问限制识别：语句片段 → stop_reason（按优先级从上到下匹配）
_RESTRICTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"滑动验证|人机验证|安全验证|verify you are human|please verify", re.I),
     STOP_VERIFICATION),
    (re.compile(r"登录后查看|请先登录|登录抖音|需登录|登录后访问|扫码登录", re.I),
     STOP_LOGIN),
    (re.compile(r"访问过于频繁|操作过于频繁|请求频率过高|网络异常[，, ]?请稍后|频繁"),
     STOP_ACCESS_RESTRICTED),
    (re.compile(r"账号不存在|用户不存在|该账号已被封禁|账号已注销|帐号不存在", re.I),
     STOP_ACCOUNT_UNAVAILABLE),
]


class DouyinError(Exception):
    """采集错误，携带 stop_reason 供上层决策（不绕过、如实上抛）。"""

    def __init__(self, stop_reason: str, message: str, raw: Any = None):
        super().__init__(message)
        self.stop_reason = stop_reason
        self.message = message
        self.raw = raw


# --------------------------------------------------------------------------
# 工具函数（_now_iso / _ts_to_iso / _int 已下沉至 _utils.py，此处仅保留
# 抖音特有的 _extract_hashtags —— 它需从 text_extra 结构化字段提取，并复用
# 共享 extract_hashtags 处理 desc 文本部分）
# --------------------------------------------------------------------------
def _extract_hashtags(desc: Any, text_extra: Any) -> list[str]:
    """从文案与 text_extra 抽取话题标签，去重保序。"""
    tags: list[str] = []
    if isinstance(text_extra, list):
        for item in text_extra:
            name = (item or {}).get("hashtag_name") if isinstance(item, dict) else None
            if name and name not in tags:
                tags.append(name)
    if isinstance(desc, str):
        for m in extract_hashtags(desc):
            if m not in tags:
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

    # -- 路由 ---------------------------------------------------------------
    def supports(self, url: str) -> bool:
        """仅支持抖音账号主页（含短链 best-effort 解析）；拒绝作品/搜索/其他。"""
        if not isinstance(url, str) or not url.strip():
            return False
        u = url.strip()
        try:
            parsed = urllib.parse.urlparse(u)
        except ValueError:
            return False
        host = parsed.netloc.lower()
        path = parsed.path

        if host == "v.douyin.com":
            # 短链：best-effort 解析为长链后再判定；解析失败则按短链形式保守支持。
            final = self._resolve_final_url(u)
            if final:
                return self._is_user_url(final)
            # 解析失败：短链形式本身作为合法入口 best-effort 判为支持。
            return bool(
                re.match(r"^https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?(\?[^/]*)?$", u)
            )

        if host in ("www.douyin.com", "douyin.com", "iesdouyin.com"):
            # 明确拒绝作品/搜索/话题/直播/发现页。
            if any(
                seg in path
                for seg in ("/video/", "/note/", "/search", "/topic/", "/music/",
                            "/challenge/", "/live/", "/discover/")
            ):
                return False
            if "/user/" in path or "/share/user/" in path:
                return True
            return False

        return False

    @staticmethod
    def _is_user_url(url: str) -> bool:
        """判定解析后的长链是否为账号主页。"""
        try:
            p = urllib.parse.urlparse(url)
        except ValueError:
            return False
        path = p.path
        if any(
            seg in path
            for seg in ("/video/", "/note/", "/search", "/topic/", "/music/",
                        "/challenge/", "/live/", "/discover/")
        ):
            return False
        return "/user/" in path or "/share/user/" in path

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
        """urllib 取页面文本；如开启浏览器降级且 urllib 直连无可用 RENDER_DATA，则通过 BrowserSession 发起 CDP 页面导航渲染。"""
        import os

        html: str | None = None
        use_fallback = bool(
            os.environ.get("DOUYIN_BROWSER_FALLBACK") == "1"
            or os.environ.get("BILIBILI_BROWSER_FALLBACK") == "1"
            or os.environ.get("BROWSER_FALLBACK") == "1"
        )

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
                html = resp.read().decode(charset, errors="replace")
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
            if not use_fallback:
                raise DouyinError(
                    STOP_ACCESS_RESTRICTED, f"网络错误: {e.reason} ({url})"
                )

        # 直连页面已明确提示登录/验证/访问受限时，立即停止；浏览器降级不是
        # 绕过这些保护的路径。
        if html:
            restriction = _detect_restriction(html)
            if restriction:
                raise DouyinError(restriction, f"页面命中访问限制标记: {restriction}")

        # 尝试浏览器降级：仅在直连无明确限制、且没有可解析数据时进行。
        if use_fallback and (not html or _extract_render_data(html) is None):
            try:
                from .browser_backend import BrowserSession, find_browser

                if find_browser():
                    with BrowserSession() as b:
                        rendered_html = b.navigate_and_get_html(url, wait_seconds=3.5)
                        if rendered_html and _detect_restriction(rendered_html) is None:
                            return rendered_html
                        if rendered_html:
                            html = rendered_html
            except Exception:
                pass

        if html:
            return html
        raise DouyinError(STOP_ACCESS_RESTRICTED, f"页面抓取失败: {url}")


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
                    "collected_at": datetime.now(_BEIJING).isoformat(),
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
    def collect_post_list(
        self,
        url: str,
        limit: int = 30,
        date_range: tuple[str | None, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        """采集作品摘要列表（标记 is_pinned），归一化后返回。

        Best-effort：从 RENDER_DATA 抽取作品数组。尊重 limit 与 date_range。
        命中任务级限制抛 DouyinError；单条缺失不影响整体（保持 null，不臆造）。
        """
        if not self.supports(url):
            raise DouyinError(STOP_UNSUPPORTED, f"不支持的账号主页 URL: {url}")
        html = self._fetch(url)
        restriction = _detect_restriction(html)
        if restriction:
            raise DouyinError(restriction, f"采集列表时命中访问限制: {restriction}")

        data = _extract_render_data(html)
        if data is None:
            raise DouyinError(STOP_PARSER_FAILED, "账号主页可访问但无 RENDER_DATA，无法解析作品列表")

        aweme_list = self._find_aweme_list(data)
        if aweme_list is None:
            raise DouyinError(
                STOP_PARSER_FAILED, "RENDER_DATA 中未识别到作品列表结构"
            )

        posts: list[dict[str, Any]] = []
        for item in aweme_list:
            if not isinstance(item, dict):
                continue
            if len(posts) >= limit:
                break
            raw = self._build_post_raw(url, item, source="list")
            posts.append(self.normalize_post(raw))

        if not posts and len(aweme_list) == 0:
            # 账号存在但确无作品（且非受限）→ 如实返回空列表（上层可判 NO_PUBLIC_CONTENT）。
            return []

        if date_range:
            posts = self._filter_by_date(posts, date_range)
        return posts[:limit]

    # -- 单条详情 -----------------------------------------------------------
    def collect_post_detail(self, post_url: str) -> dict[str, Any]:
        """采集单条作品详情并归一化。播放数可能不公开 → views=None。"""
        if not isinstance(post_url, str) or not post_url.strip():
            raise DouyinError(STOP_UNSUPPORTED, "无效的作品 URL")
        html = self._fetch(post_url)
        restriction = _detect_restriction(html)
        if restriction:
            raise DouyinError(restriction, f"采集作品详情时命中访问限制: {restriction}")

        data = _extract_render_data(html)
        if data is None:
            raise DouyinError(STOP_PARSER_FAILED, "作品页可访问但无 RENDER_DATA，无法解析")
        aweme = self._find_aweme_detail(data)
        if not aweme:
            raise DouyinError(
                STOP_PARSER_FAILED, "RENDER_DATA 中未识别到单条作品结构"
            )
        raw = self._build_post_raw(post_url, aweme, source="detail")
        return self.normalize_post(raw)

    # -- 评论（覆盖基类，best-effort） -------------------------------------
    def collect_comments(
        self, post_url: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """公开评论采样（best-effort）。

        抖音评论走签名接口，urllib 直连不可达；任何限制/错误一律返回 []，不绕过、
        不报错。上层按 COMMENTS_UNAVAILABLE 行为处理（不影响任务状态）。
        """
        try:
            if not isinstance(post_url, str) or not post_url.strip():
                return []
            html = self._fetch(post_url)
            restriction = _detect_restriction(html)
            if restriction:
                return []
            data = _extract_render_data(html)
            if data is None:
                return []
            comments_raw = self._find_comments(data)
            out: list[dict[str, Any]] = []
            for c in (comments_raw or [])[:limit]:
                if not isinstance(c, dict):
                    continue
                out.append(
                    {
                        "comment_id": c.get("cid") or c.get("id"),
                        "post_url": post_url,
                        "author": (c.get("user") or {}).get("nickname"),
                        "text": c.get("text") or c.get("content"),
                        "likes": _int(c.get("digg_count")),
                        "published_at": _ts_to_iso(c.get("create_time")),
                        "collected_at": _now_iso(),
                    }
                )
            return out
        except Exception:
            # 任何异常（含限制）均降级为 []，不绕过、不向上抛。
            return []

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

    def _find_aweme_detail(self, data: dict) -> dict | None:
        """在 RENDER_DATA 中定位单条作品结构。"""
        candidates = [
            _dig(data, "aweme", "detail"),
            _dig(data, "video", "aweme"),
            _dig(data, "app", "aweme", "detail"),
        ]
        for c in candidates:
            if isinstance(c, dict) and c.get("aweme_id"):
                return c
        found = self._search_key(data, "aweme_id")
        if isinstance(found, dict) and found.get("aweme_id"):
            return found
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
        desc = aweme.get("desc") or ""
        text_extra = aweme.get("text_extra")
        statistics = aweme.get("statistics") or {}
        video = aweme.get("video") or {}
        is_top = bool(aweme.get("is_top") or aweme.get("is_top_aweme"))
        is_ad = bool(aweme.get("is_ad") or aweme.get("is_commerce"))
        # 图文/笔记 best-effort 判定。
        content_type = "video"
        if aweme.get("images") and not video:
            content_type = "image_text"
        collection = aweme.get("mix_info") or aweme.get("collection")
        collection_name = (collection or {}).get("mix_name") if isinstance(collection, dict) else None
        single_text = (desc or "").split("\n")[0] if isinstance(desc, str) else None
        # 抖音 duration 单位为毫秒，归一化为秒；_int 对非数字返回 None，需先判空避免 TypeError。
        duration_ms = _int(video.get("duration"))
        duration_seconds = (duration_ms // 1000) if duration_ms is not None else None
        return {
            "platform": "douyin",
            "post_id": str(aweme.get("aweme_id") or aweme.get("aweme_id_str")),
            "post_url": aweme.get("share_url") or url,
            "published_at": _ts_to_iso(aweme.get("create_time")),
            "content_type": content_type,
            "title": single_text,
            "text": desc,
            "duration_seconds": duration_seconds,
            "hashtags": _extract_hashtags(desc, text_extra),
            "is_pinned": is_top,
            "is_repost": False,
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
            "source_url": aweme.get("share_url") or url,
            "platform_metrics": {
                "collection_name": collection_name,
                "aweme_type": aweme.get("aweme_type"),
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
