"""B站公开账号采集适配器（P0）。

仅用标准库（subprocess 调 curl / json / hashlib）访问 *.bilibili.com 公开接口。
实现统一适配器接口：supports / check_access / collect_profile /
collect_post_list / collect_post_detail / collect_comments。

为什么用 curl 而非 urllib：B站 WAF 会直接拒绝 urllib 直连的 HTTP 层（返回
HTTP 412），而 curl 携带完整浏览器头（Origin / Sec-Fetch / --compressed）可正常
通过。以下实现路径由 T3 实跑验证（game 区个人 up 主 mid=411581408）：
  - buvid3/buvid4 前置（finger/spi，JSON 直接返回 b_3/b_4，无需解析 Set-Cookie）
  - 高风险层 space 接口必须走 wbi 签名，且签名字典**必须含 web_location**（注意：acc/info 用 333.1007，arc/search 用 333.1387，用错会导致签名被拒 -799）
  - 正确路径为 /x/space/wbi/acc/info 与 /x/space/wbi/arc/search
  - 平台一旦返回限流、验证码或登录墙，当前任务立即停止；不会轮换身份、切换端点
    或改走浏览器。仅没有收到平台响应的本地传输失败可用同一身份重试一次。

合规边界（见 SKILL.md 与 references/platform-bilibili.md）：
- 不登录、不绕过验证码 / WBI / 频控；遇阻停止并抛 BilibiliError(stop_reason)。
- 字段不可见写 None（绝不用 0 代替未知）。
- 不分析、不存储，只返回结构化原始数据（由上层脚本落盘）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from functools import reduce
from typing import Any

from ._constants import PUBLIC_LIMIT_DEFAULT, validate_public_limit
from .base import BaseCollector
from .url_policy import canonical_item_url

API = "https://api.bilibili.com"
WEB = "https://space.bilibili.com"
VIDEO = "https://www.bilibili.com/video/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# stop_reason 取值严格对齐 SKILL.md 枚举（字符串值必须完全一致）
STOP_LOGIN = "LOGIN_REQUIRED"
STOP_VERIFICATION = "VERIFICATION_REQUIRED"
STOP_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
STOP_ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
# 本地结构缺失使用 PARSER_FAILED；端点均明确返回空列表使用 NO_PUBLIC_CONTENT。
STOP_PARSER_FAILED = "PARSER_FAILED"
STOP_NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"
STOP_UNSUPPORTED = "UNSUPPORTED_PLATFORM"
STOP_INTERNAL = "INTERNAL_ERROR"
STOP_COMMENTS_UNAVAILABLE = "COMMENTS_UNAVAILABLE"

# WBI 置换表（bilibili-api-collect 项目权威值，长度 64，元素 0-63）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43,
    5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16,
    24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59,
    6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# 这些业务码都是平台已明确返回的保护响应，绝不是传输层瞬态失败。
# 一旦命中便打开会话断路器，当前任务不再发送任何 B 站请求。
PLATFORM_PROTECTION_CODES = {-412, -799, -403, -400, -401, -352, -101}
PLATFORM_PROTECTION_REASONS = {
    STOP_LOGIN,
    STOP_VERIFICATION,
    STOP_ACCESS_RESTRICTED,
}
# space 类 wbi 接口的 web_location（签名字典必须包含，否则签名被拒 -412）
# 注意：不同 space 子接口要求不同 web_location：
#   - acc/info   → 333.1007
#   - arc/search → 333.1387（用错会导致 -799 签名被拒，退化到 search/type 仅得少量结果）
WEB_LOCATION_SPACE = "333.1007"
WEB_LOCATION_ARC = "333.1387"

# 分区静态映射（typeid -> 子分区）。来源：references/platform-bilibili.md §分区中文名缺口结论
# （第 2 层：独立浏览器工作流产出、高置信、待官方分区表核对；尤其 249/250 待核对）。
# 现实 API 的 tname/tname_v2 已实测为空，故分区只能靠此静态映射，并在输出标注来源。
TYPENAME_MAP = {
    17: "单机游戏", 21: "日常", 25: "MMD·3D", 28: "原创音乐", 31: "翻唱",
    65: "网络游戏", 95: "数码", 138: "搞笑", 171: "电子竞技", 172: "手机游戏",
    212: "美食侦探", 218: "喵星人", 249: "足球", 250: "出行",  # 249/250 待官方表核对
}


class BilibiliError(Exception):
    """采集错误，携带 stop_reason 供上层决策（不绕过、如实上抛）。"""

    def __init__(self, stop_reason: str, message: str, raw: Any = None):
        super().__init__(message)
        self.stop_reason = stop_reason
        self.message = message
        self.raw = raw


class _TransportError(BilibiliError):
    """没有收到平台响应的本地传输失败；最多以同一身份重试一次。"""


# --------------------------------------------------------------------------
# WBI 签名
# --------------------------------------------------------------------------
def get_mixin_key(orig: str) -> str:
    """对 img_key+sub_key(64字符) 按置换表重排并截断为 32 字符。"""
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """为请求参数生成 w_rid / wts（WBI 签名）。

    调用方需把 web_location 等「参与签名的业务参数」先放进 params，本函数会对
    全部 params（含 web_location）统一排序、过滤、MD5 生成 w_rid。
    """
    mixin_key = get_mixin_key(img_key + sub_key)
    params = dict(params)
    params["wts"] = str(round(time.time()))
    params = dict(sorted(params.items()))  # 按 key 升序
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)  # 大写 hex、空格 %20
    params["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return params


def _stop_reason_for_code(code: Any) -> str:
    return {
        -412: STOP_ACCESS_RESTRICTED,
        -799: STOP_ACCESS_RESTRICTED,
        -401: STOP_VERIFICATION,
        -352: STOP_VERIFICATION,
        -403: STOP_ACCESS_RESTRICTED,
        -404: STOP_ACCOUNT_UNAVAILABLE,
        -400: STOP_ACCESS_RESTRICTED,
        -101: STOP_ACCESS_RESTRICTED,
    }.get(code, STOP_ACCESS_RESTRICTED)


def _backoff(attempt: int) -> float:
    return min(30.0, 3.0 * (2 ** attempt))


def _is_platform_protection(error: BilibiliError) -> bool:
    return error.stop_reason in PLATFORM_PROTECTION_REASONS


# --------------------------------------------------------------------------
# HTTP 会话（curl 传输层）
# --------------------------------------------------------------------------
class Session:
    def __init__(
        self,
        timeout: int = 10,
        min_interval: float = 1.2,
        browser_fallback: bool | None = None,
    ):
        self.cookies: dict[str, str] = {}
        self.timeout = timeout
        self.min_interval = min_interval
        self._last = 0.0
        self._wbi: tuple[str, str] | None = None
        self._blocked_reason: str | None = None
        self._buvid_initialized = False
        # 保留配置字段以兼容调用方和显式浏览器工具，但平台保护响应绝不会触发浏览器降级。
        self._browser_fallback = (
            os.environ.get("BILIBILI_BROWSER_FALLBACK") == "1"
            if browser_fallback is None
            else bool(browser_fallback)
        )

    def _throttle(self) -> None:
        gap = self.min_interval - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.time()

    def _curl(self, url: str, referer: str) -> str:
        """用 curl 取响应体（argv 列表，无 shell 插值，避免注入）。"""
        self._throttle()
        cookie = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        cmd = [
            "curl", "-sS", "--compressed",
            "--max-time", str(self.timeout),
            "-A", UA,
            "-H", f"Referer: {referer}",
            "-H", "Accept: application/json, text/plain, */*",
            "-H", "Accept-Language: zh-CN,zh;q=0.9",
            "-H", "Origin: https://space.bilibili.com",
            "-H", "Sec-Fetch-Dest: empty",
            "-H", "Sec-Fetch-Mode: cors",
            "-H", "Sec-Fetch-Site: cross-site",
        ]
        if cookie:
            cmd += ["-b", cookie]
        cmd.append(url)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout + 10
            )
        except subprocess.TimeoutExpired:
            raise _TransportError(STOP_INTERNAL, "B站请求传输超时")
        if proc.returncode != 0:
            raise _TransportError(STOP_INTERNAL, "B站请求传输失败")
        return proc.stdout

    def _raise_if_blocked(self) -> None:
        if self._blocked_reason is not None:
            raise BilibiliError(
                self._blocked_reason,
                "B站会话已因平台保护响应停止",
            )

    def _trip_circuit(self, error: BilibiliError) -> None:
        if error.stop_reason in PLATFORM_PROTECTION_REASONS:
            self._blocked_reason = error.stop_reason

    def raise_for_task(
        self,
        stop_reason: str,
        message: str,
        raw: Any = None,
    ) -> None:
        """Raise a task error and trip the circuit for protection reasons."""
        error = BilibiliError(stop_reason, message, raw)
        self._trip_circuit(error)
        raise error

    def get_json(
        self,
        path: str,
        params=None,
        wbi: bool = False,
        referer: str = WEB,
        retry: int = 3,
        raise_on_error: bool = True,
    ) -> dict:
        """取 JSON；平台保护响应立即停，纯传输失败同身份最多重试一次。"""
        self._raise_if_blocked()
        q = dict(params or {})
        if wbi:
            if self._wbi is None:
                self._refresh_wbi()
            q = enc_wbi(q, self._wbi[0], self._wbi[1])
        full = API + path + (("?" + urllib.parse.urlencode(q)) if q else "")
        attempts = 1 if retry <= 1 else 2
        for attempt in range(attempts):
            try:
                body = self._curl(full, referer)
            except _TransportError:
                if attempt + 1 < attempts:
                    time.sleep(_backoff(attempt))
                    continue
                raise
            except BilibiliError as error:
                self._trip_circuit(error)
                raise
            try:
                return self._parse_and_check(body, path, raise_on_error)
            except BilibiliError as error:
                self._trip_circuit(error)
                raise
        raise BilibiliError(STOP_INTERNAL, "B站请求未完成")

    def _parse_and_check(
        self, body: str, path: str, raise_on_error: bool
    ) -> dict:
        """解析响应体；任何平台保护码或保护页都立即上抛。"""
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise self._non_json_error(path, body)
        code = data.get("code")
        if code == 0 or code is None:
            return data
        if code in PLATFORM_PROTECTION_CODES:
            raise BilibiliError(
                _stop_reason_for_code(code),
                f"{path} 被平台拒绝 (code={code})",
            )
        if not raise_on_error:
            return data
        raise BilibiliError(
            _stop_reason_for_code(code),
            f"{path} code={code} {data.get('message')}",
            data,
        )

    def _fetch_via_browser(self, full: str, referer: str) -> str:
        """浏览器降级：经运行环境的浏览器进程 fetch（请求走真实网络出口）。

        仅作传输层替代；不绕过验证码/滑块/登录墙/频控。复用会话已获得的 buvid cookie。
        跨平台：浏览器二进制由 browser_backend.find_browser 自动探测，或由
        BROWSER_BIN / CHROME_BIN 环境变量覆盖，绝不硬编码本机路径。
        """
        from .browser_backend import BrowserSession, BrowserError, find_browser

        bin_path = find_browser()
        if not bin_path:
            raise BrowserError("未找到浏览器二进制，无法启用浏览器降级")
        headers = {
            "Referer": referer,
            "Origin": "https://space.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        with BrowserSession(browser_bin=bin_path) as b:
            if self.cookies:
                b.set_cookies(self.cookies, domain=".bilibili.com")
            return b.fetch_text(full, headers)

    def _non_json_error(self, path: str, body: str) -> BilibiliError:
        """Classify non-JSON only when the body contains explicit evidence."""
        low = (body or "").lower()
        if any(
            marker in low
            for marker in (
                "verify_captcha",
                "captcha required",
                "verification required",
                "验证码",
                "滑块",
                "geetest",
            )
        ):
            return BilibiliError(
                STOP_VERIFICATION, f"非 JSON 响应疑似验证码/滑块拦截页: {path}"
            )
        if "login" in low or "登录" in low:
            return BilibiliError(STOP_LOGIN, f"非 JSON 响应疑似登录墙: {path}")
        if any(
            marker in low
            for marker in (
                "waf",
                "request was banned",
                "access denied",
                "forbidden",
                "too many requests",
                "rate limit",
                "rate-limit",
                "ratelimit",
                "precondition failed",
                "请求过于频繁",
                "访问受限",
                "拒绝访问",
                "请求被拦截",
                "频控",
                "限流",
            )
        ):
            return BilibiliError(
                STOP_ACCESS_RESTRICTED,
                f"非 JSON 响应含平台访问限制证据: {path}",
            )
        return BilibiliError(
            STOP_PARSER_FAILED,
            f"非 JSON 响应无法解析: {path}",
        )

    def _refresh_wbi(self) -> None:
        data = self.get_json("/x/web-interface/nav", retry=2, raise_on_error=False)
        wbi = (data.get("data") or {}).get("wbi_img") or {}
        img = re.sub(r"\.png$", "", (wbi.get("img_url") or "").rsplit("/", 1)[-1])
        sub = re.sub(r"\.png$", "", (wbi.get("sub_url") or "").rsplit("/", 1)[-1])
        if not img or not sub:
            self.raise_for_task(STOP_PARSER_FAILED, "nav 未返回 wbi_img 密钥")
        self._wbi = (img, sub)

    def ensure_buvid(self, force: bool = False) -> None:
        del force  # 兼容旧调用签名；当前任务绝不轮换已经建立的公开身份。
        if self.cookies.get("buvid3"):
            self._buvid_initialized = True
            return
        if self._buvid_initialized:
            return
        self._buvid_initialized = True
        try:
            data = self.get_json("/x/frontend/finger/spi", retry=2)
            d = data.get("data") or {}
            if d.get("b_3"):
                self.cookies["buvid3"] = d["b_3"]
            if d.get("b_4"):
                self.cookies["buvid4"] = d["b_4"]
        except BilibiliError:
            return

    # -- 投稿发现 --
    def discover_medialist(self, mid: str, limit: int) -> list:
        """首选：medialist/resource/list 游标分页（免 wbi、免频控、返回完整 cnt_info）。

        相比 arc/search 的优势（T6 实测，2026-07-23）：
        - 免 wbi 签名，数据中心 IP 稳定 code:0，无 -412/-799 风控
        - 单次调用即返回完整 cnt_info（play/thumb_up/coin/collect/reply/danmaku/share），
          无需逐条 view 补全，大幅减少请求数与 IP 信誉消耗
        - 游标分页用 oid=上一页最后一条的 id，has_more 控制翻页

        字段映射（media_list 条目 → 统一字段）：
          bv_id → bvid, title, pubtime → published_at, duration(秒),
          tid → typeid, cnt_info.{play,thumb_up,coin,collect,reply,danmaku,share}
          copy_right: 1=原创, 2=转载
        """
        out: list = []
        oid = "0"
        size = 20
        for _ in range(20):  # 上限保护
            data = self.get_json(
                "/x/v2/medialist/resource/list",
                {
                    "mobi_app": "web",
                    "type": "1",
                    "biz_id": mid,
                    "oid": oid,
                    "size": size,
                },
                wbi=False,
                retry=3,
            )
            if data.get("code") != 0:
                self.raise_for_task(
                    _stop_reason_for_code(data.get("code")),
                    f"medialist 失败: {data.get('message')}",
                )
            d = data.get("data") or {}
            media_list = d.get("media_list") or []
            if not media_list:
                break
            out.extend(media_list)
            if len(out) >= limit:
                return out[:limit]
            if not d.get("has_more"):
                break
            # 游标更新为当前页最后一条的 id
            last = media_list[-1]
            new_oid = str(last.get("id") or "")
            if not new_oid or new_oid == oid:
                break
            oid = new_oid
            time.sleep(1.0)  # 翻页间隔，降低风控概率
        return out[:limit]

    def collect_pinned(self, mid: str) -> tuple[bool, str | None]:
        """获取置顶视频证据，区分“无置顶”与“未观测成功”。

        返回 ``(observed, bvid)``：端点成功响应时 ``observed=True``，
        其中 ``bvid=None`` 表示明确无置顶；普通失败返回
        ``(False, None)``，不得推断为非置顶。
        """
        try:
            data = self.get_json(
                "/x/space/top/arc",
                {"vmid": mid},
                wbi=False,
                retry=2,
            )
            if data.get("code") == 0:
                payload = data.get("data")
                if payload is None:
                    return True, None
                if not isinstance(payload, dict):
                    return False, None
                bvid = payload.get("bvid")
                if isinstance(bvid, str) and bvid.strip():
                    return True, bvid.strip()
                return False, None
        except BilibiliError as error:
            if _is_platform_protection(error):
                raise
        return False, None

    def collect_tags(self, bvid: str) -> list[str]:
        """获取视频标签。端点 /x/tag/archive/tags（免 wbi、稳定）。

        返回 tag_name 列表；失败返回 []（不阻塞主流程）。
        """
        try:
            data = self.get_json(
                "/x/tag/archive/tags",
                {"bvid": bvid},
                wbi=False,
                retry=2,
            )
            if data.get("code") == 0:
                tags = data.get("data") or []
                return [t.get("tag_name") for t in tags if t.get("tag_name")]
        except BilibiliError as error:
            if _is_platform_protection(error):
                raise
        return []

    def discover_arc(self, mid: str, limit: int) -> list:
        """降级 A：wbi 签名的 space 投稿列表(自动翻页至 limit 或末页)。失败抛 BilibiliError 由上层降级。"""
        out: list = []
        ps = 50
        pn = 1
        while len(out) < limit:
            if pn > 1:
                # 翻页时仅节流，始终复用任务创建时的公开身份。
                time.sleep(6)
            data = self.get_json(
                "/x/space/wbi/arc/search",
                {
                    "mid": mid,
                    "ps": ps,
                    "pn": pn,
                    "order": "pubdate",
                    "web_location": WEB_LOCATION_ARC,
                },
                wbi=True,
                retry=3,
            )
            if data.get("code") != 0:
                self.raise_for_task(
                    _stop_reason_for_code(data.get("code")), "arc/search 失败"
                )
            vlist = (data.get("data") or {}).get("list", {}).get("vlist", [])
            if not vlist:
                break
            out.extend(vlist)
            if len(vlist) < ps:
                break  # 已到末页
            pn += 1
        return out[:limit]

    def discover_search(self, mid: str, url: str, limit: int) -> list:
        """降级 B：用昵称搜 bili_user，取其 res[] 中的 BV 列表。"""
        card = self.get_json("/x/web-interface/card", {"mid": mid})
        name = (card.get("data") or {}).get("card", {}).get("name", "")
        if not name:
            self.raise_for_task(
                STOP_PARSER_FAILED, f"无法解析昵称进行 search 降级 (mid={mid})"
            )
        data = self.get_json(
            "/x/web-interface/search/type",
            {"search_type": "bili_user", "keyword": name, "page": 1},
        )
        if data.get("code") != 0:
            self.raise_for_task(
                _stop_reason_for_code(data.get("code")),
                "search/type 降级失败",
            )
        res_data = data.get("data") or {}
        target = next(
            (r for r in res_data.get("result", [])
             if str(r.get("mid")) == str(mid)),
            None,
        )
        if not target:
            self.raise_for_task(STOP_PARSER_FAILED, "search/type 未匹配到该账号")
        return [it["bvid"] for it in target.get("res", []) if it.get("bvid")][:limit]

    def discover_dynamics(self, mid: str, limit: int) -> list:
        """空间动态 feed（视频类动态）。WBI 签名 + web_location=333.1007。

        分页用 offset + has_more；B站动态 feed 偶发返回空页（has_more 仍为 true），
        故用 empty_streak 守卫避免死循环。仅视频类动态（含 bvid）入列；转发卡
        (orig 非空) 也保留 bvid 但标记 is_forward。平台保护响应立即上抛并打开断路器。
        """
        out: list = []
        offset = ""
        empty_streak = 0
        for _ in range(20):
            if out and offset:
                time.sleep(1.0)  # 分页间隔，降低被风控概率
            data = self.get_json(
                "/x/polymer/web-dynamic/v1/feed/space",
                {
                    "host_mid": mid,
                    "offset": offset,
                    "timeline_ad": "true",
                    "web_location": WEB_LOCATION_SPACE,
                },
                wbi=True,
                retry=3,
            )
            if data.get("code") != 0:
                self.raise_for_task(
                    _stop_reason_for_code(data.get("code")),
                    "动态 feed 请求失败",
                )
            d = data.get("data") or {}
            items = d.get("items") or []
            for it in items:
                card = _extract_dynamic_card(it)
                if card:
                    out.append(card)
                    if len(out) >= limit:
                        return out[:limit]
            if not items:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
            if not d.get("has_more"):
                break
            new_offset = d.get("offset") or ""
            if new_offset == offset and empty_streak >= 2:
                break
            offset = new_offset
        return out[:limit]


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
# B站公开时间戳均为北京时间 (UTC+8)
_BEIJING = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(_BEIJING).isoformat()


def _int(v: Any) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    mult = 1
    if "亿" in s:
        mult = 100_000_000
    if "万" in s:
        mult = 10_000
    s = s.replace("亿", "").replace("万", "").replace(",", "")
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _to_iso(ts: Any) -> str | None:
    if not ts:
        return None
    try:
        val = int(ts)
        if val > 10000000000:
            val //= 1000
        return datetime.fromtimestamp(val, tz=_BEIJING).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _extract_hashtags(*texts: Any) -> list[str]:
    """从文本中按 #标签# 形式提取话题标签。"""
    tags: list[str] = []
    for t in texts:
        if not t or not isinstance(t, str):
            continue
        for m in re.findall(r"#([^#\s]+)#?", t):
            if m and m not in tags:
                tags.append(m)
    return tags


def _parse_duration(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if ":" in s:  # mm:ss 或 hh:mm:ss
        parts = [int(p) for p in s.split(":")]
        sec = 0
        for p in parts:
            sec = sec * 60 + p
        return sec
    return _int(s)


def _mid_from_url(url: str) -> str:
    m = re.search(r"bilibili\.com/(?:space/)?(\d+)", url)
    if not m:
        raise BilibiliError(STOP_UNSUPPORTED, f"无法从 URL 解析 UID: {url}")
    return m.group(1)


# --------------------------------------------------------------------------
# 适配器
# --------------------------------------------------------------------------
class BilibiliCollector(BaseCollector):
    platform = "bilibili"

    def __init__(self, browser_fallback: bool | None = None):
        self.browser_fallback = browser_fallback
        self._task_session: Session | None = None

    def _new_session(self) -> Session:
        """Return the collector task's single shared session."""
        if self._task_session is None:
            self._task_session = Session(browser_fallback=self.browser_fallback)
        return self._task_session

    # -- 路由 --
    def supports(self, url: str) -> bool:
        # 仅接受账号主页：https://space.bilibili.com/<digits>
        # 允许 http/https、可选尾部斜杠、可选 ?query；拒绝子域名、裸域名与
        # 任何额外路径段（/dynamic、/video、/search 等）。
        if not isinstance(url, str):
            return False
        return bool(re.fullmatch(
            r"https?://space\.bilibili\.com/\d+/?(?:\?[^#/]*)?(?:#[^/]*)?",
            url.strip(),
        ))

    # -- 访问检查（不绕过） --
    def check_access(self, url: str) -> dict:
        mid = _mid_from_url(url)
        s = self._new_session()
        s.ensure_buvid()
        # 免 wbi 端点优先：card 稳定，relation/stat 偶发被风控(-400/-412)。
        # 任一成功即视为可访问；仅两端点都失败才报受限。
        last: BilibiliError | None = None
        for path, params in (
            ("/x/web-interface/card", {"mid": mid}),
            ("/x/relation/stat", {"mid": mid}),
        ):
            try:
                data = s.get_json(path, params, retry=2)
            except BilibiliError as e:
                last = e
                if _is_platform_protection(e):
                    break
                continue
            code = data.get("code")
            if code == 0:
                return {"accessible": True, "status": "normal", "stop_reason": None}
            if code == -404:
                return {"accessible": False, "status": "account_not_exist", "stop_reason": STOP_ACCOUNT_UNAVAILABLE}
            last = BilibiliError(_stop_reason_for_code(code), f"{path} code={code}")
        return {
            "accessible": False,
            "status": "restricted",
            "stop_reason": (last.stop_reason if last else STOP_ACCESS_RESTRICTED),
        }

    # -- 资料 --
    def collect_profile(self, url: str) -> dict:
        mid = _mid_from_url(url)
        s = self._new_session()
        s.ensure_buvid()

        # card(免wbi) 稳定保底；关注数优先 relation/stat，失败用 card.fans 兜底
        card = s.get_json("/x/web-interface/card", {"mid": mid})
        stat = None
        try:
            stat = s.get_json("/x/relation/stat", {"mid": mid}, retry=2)
            if stat.get("code") != 0:
                stat = None
        except BilibiliError as error:
            if _is_platform_protection(error):
                raise
            stat = None

        # acc/info(wbi + web_location) 作富字段增强，失败不影响主路径
        acc = None
        try:
            acc_raw = s.get_json(
                "/x/space/wbi/acc/info",
                {"mid": mid, "web_location": WEB_LOCATION_SPACE},
                wbi=True,
            )
            if acc_raw.get("code") == 0:
                acc = acc_raw.get("data")
        except BilibiliError as error:
            if _is_platform_protection(error):
                raise
            acc = None

        return self.normalize_profile(_build_profile_raw(mid, card, stat, acc))

    # -- 视频列表 --
    def collect_post_list(
        self,
        url: str,
        limit: int = PUBLIC_LIMIT_DEFAULT,
        date_range=None,
    ) -> list:
        limit = validate_public_limit(limit)
        mid = _mid_from_url(url)
        s = self._new_session()
        s.ensure_buvid()

        # 置顶视频检测（top/arc，免 wbi、稳定）——用于标记 is_pinned
        pinned_result = s.collect_pinned(mid)
        if (
            isinstance(pinned_result, tuple)
            and len(pinned_result) == 2
            and isinstance(pinned_result[0], bool)
        ):
            pinned_observed, pinned_bvid = pinned_result
        elif isinstance(pinned_result, str) and pinned_result.strip():
            # 旧 Session/测试双直接返回 BV 号，它仍是明确的置顶证据。
            pinned_observed, pinned_bvid = True, pinned_result.strip()
        else:
            # 向下兼容旧测试双/外部适配；无证据必须保持未知。
            pinned_observed, pinned_bvid = False, None

        # 三级降级链：medialist(免wbi+完整指标) → arc/search(wbi) → search/type(BV列表)
        entries = None
        source = None

        # 首选：medialist/resource/list（免 wbi、返回完整 cnt_info、无 412 风控）
        try:
            entries = s.discover_medialist(mid, limit)
            source = "medialist"
        except BilibiliError as error:
            if _is_platform_protection(error):
                raise
            entries = None

        # 降级 A：arc/search（wbi + web_location=333.1387）
        if not entries:
            try:
                entries = s.discover_arc(mid, limit)
                source = "arc"
            except BilibiliError as error:
                if _is_platform_protection(error):
                    raise
                entries = None

        # 降级 B：search/type（仅 BV 列表，需逐条 view 补全）
        if not entries:
            try:
                bvids = s.discover_search(mid, url, limit)
                entries = [{"bvid": b} for b in bvids]
                source = "search"
            except BilibiliError as e:
                raise e

        posts = []
        any_view_ok = False
        for e in entries[:limit]:
            bvid = e.get("bvid") or e.get("bv_id") or str(e.get("aid") or "")
            if not bvid or bvid == "None":
                continue

            # 根据 entries 来源构建 base post
            if source == "medialist":
                base = _build_post_raw_from_medialist(e, url)
                # medialist 已含完整 cnt_info，通常无需 view 补全；
                # 但 hashtags 仅从 intro 提取，可选补 tag API
            elif "title" in e or "play" in e:
                base = _build_post_raw_from_vlist(e, url)
                # arc/search vlist 缺 like/coin/favorite/share，用 view 补全
                try:
                    v = s.get_json("/x/web-interface/view", {"bvid": bvid})
                    if v.get("code") == 0:
                        base = _build_post_raw_from_view(v["data"], url)
                        any_view_ok = True
                except BilibiliError as error:
                    if _is_platform_protection(error):
                        raise
                    pass  # 保留 vlist 级数据（honest null）
            else:
                base = _empty_post(bvid)
                # search 降级仅有 BV，必须 view 补全
                try:
                    v = s.get_json("/x/web-interface/view", {"bvid": bvid})
                    if v.get("code") == 0:
                        base = _build_post_raw_from_view(v["data"], url)
                        any_view_ok = True
                except BilibiliError as error:
                    if _is_platform_protection(error):
                        raise
                    pass

            # 权威标签补全：普通不可用不影响主流程；平台保护响应必须立即停止。
            try:
                api_tags = s.collect_tags(bvid)
            except BilibiliError as error:
                if _is_platform_protection(error):
                    raise
                api_tags = []
            except Exception:
                api_tags = []
            if api_tags:
                base_tags = base.get("hashtags") or []
                if isinstance(base_tags, str):
                    base_tags = [t for t in base_tags.replace("|", ",").split(",") if t.strip()]
                merged = list(base_tags)
                for t in api_tags:
                    if t and t not in merged:
                        merged.append(t)
                base["hashtags"] = merged

            # 置顶标记
            if pinned_observed:
                base["is_pinned"] = bool(
                    pinned_bvid is not None and bvid == pinned_bvid
                )

            posts.append(self.normalize_post(base))

        if not posts:
            raise BilibiliError(
                STOP_NO_PUBLIC_CONTENT,
                f"三级降级链均无可用投稿 (mid={mid})",
            )

        # 日期范围过滤（Best-effort）
        if date_range and posts:
            df, dt = date_range
            filtered = []
            for p in posts:
                pa = p.get("published_at")
                if df and pa and pa < df:
                    continue
                if dt and pa and pa > dt:
                    continue
                filtered.append(p)
            posts = filtered

        # search 降级且全部 view 补全失败 → 空骨架无指标，如实上抛
        if source == "search" and not any_view_ok and posts:
            raise BilibiliError(
                STOP_PARSER_FAILED,
                f"search 降级且全部 view 补全失败 (mid={mid})",
            )
        return posts

    # -- 单条详情 --
    def collect_post_detail(self, post_url: str) -> dict:
        canonical_url = canonical_item_url("bilibili", post_url)
        if canonical_url is None:
            raise BilibiliError(STOP_UNSUPPORTED, "无法解析公开 BV URL")
        bv = canonical_url.rsplit("/", 1)[-1]
        s = self._new_session()
        s.ensure_buvid()
        data = s.get_json("/x/web-interface/view", {"bvid": bv})
        if data.get("code") != 0:
            s.raise_for_task(
                _stop_reason_for_code(data.get("code")),
                f"view 失败: {data.get('message')}",
                data,
            )
        view_data = data.get("data")
        if not view_data:
            raise BilibiliError(STOP_PARSER_FAILED, "view 响应数据为空")
        return self.normalize_post(_build_post_raw_from_view(view_data, canonical_url))

    # -- 评论采集（best-effort，与任务共享 curl Session，免登录） --
    def collect_comments(self, post_url: str, limit: int = 20) -> list[dict]:
        """取公开评论；仅明确成功的空 replies 可返回空列表。"""
        canonical_url = canonical_item_url("bilibili", post_url)
        if canonical_url is None:
            raise BilibiliError(
                STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
            )
        bvid = canonical_url.rsplit("/", 1)[-1]
        session = self._new_session()
        try:
            session._raise_if_blocked()
            session.ensure_buvid()
            view = session.get_json(
                "/x/web-interface/view",
                {"bvid": bvid},
                retry=2,
            )
            view_data = view.get("data")
            aid = view_data.get("aid") if isinstance(view_data, dict) else None
            if isinstance(aid, bool) or not isinstance(aid, int) or aid <= 0:
                raise BilibiliError(
                    STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
                )
            data = session.get_json(
                "/x/v2/reply",
                {"type": 1, "oid": aid, "mode": 3, "next": 0},
                referer=canonical_url,
                retry=2,
            )
            if not isinstance(data, dict) or data.get("code") != 0:
                if isinstance(data, dict) and data.get("code") is not None:
                    session.raise_for_task(
                        _stop_reason_for_code(data.get("code")),
                        "公开评论请求被平台拒绝",
                    )
                raise BilibiliError(
                    STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
                )
            payload = data.get("data")
            if not isinstance(payload, dict) or "replies" not in payload:
                raise BilibiliError(
                    STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
                )
            replies = payload.get("replies")
            if not isinstance(replies, list):
                raise BilibiliError(
                    STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
                )
            out: list[dict] = []
            for r in replies[:limit]:
                member = r.get("member") or {}
                content = r.get("content") or {}
                out.append(
                    {
                        "comment_id": r.get("rpid"),
                        "post_id": bvid,
                        "author": member.get("uname"),
                        "text": content.get("message"),
                        "likes": r.get("like"),
                        "published_at": _to_iso(r.get("ctime")),
                        "collected_at": _now_iso(),
                    }
                )
            return out
        except BilibiliError as error:
            if _is_platform_protection(error):
                raise
            raise BilibiliError(
                STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
            ) from None
        except Exception:
            raise BilibiliError(
                STOP_COMMENTS_UNAVAILABLE, "公开评论采样不可用"
            ) from None

    # -- 空间动态视频 feed（best-effort，合规同主路径） --
    def collect_dynamics(self, url: str, limit: int = 30) -> list[dict]:
        """采集空间动态中的视频类动态（content_type=dynamic）。

        走与主路径相同的 curl+wbi Session；动态 feed 端点为
        x/polymer/web-dynamic/v1/feed/space（web_location=333.1007，见 discover_dynamics）。
        平台保护响应立即停止；普通空结果由上层按真实覆盖情况判定，绝不伪装成功。
        """
        mid = _mid_from_url(url)
        s = self._new_session()
        s.ensure_buvid()
        try:
            cards = s.discover_dynamics(mid, limit)
        except BilibiliError as e:
            raise e
        return [self.normalize_post(_build_dynamic_raw(c)) for c in cards]

# --------------------------------------------------------------------------
# 内部构建（统一字段名，供 base.normalize_* 使用）
# --------------------------------------------------------------------------
def _build_profile_raw(mid, card, stat, acc) -> dict:
    card_d = (card.get("data") or {}).get("card") or {}
    stat_d = (stat or {}).get("data") or {}
    acc_d = acc or {}
    official = card_d.get("official") or card_d.get("official_verify") or {}
    verified = official.get("type") not in (None, -1, 0, 127)
    name = card_d.get("name") or acc_d.get("name")
    bio = card_d.get("sign") or acc_d.get("sign")
    # 等级：优先 acc/info 顶层 level（card.level_info 在 acc 响应中不存在，仅作兜底）
    level = (acc_d.get("level") if acc else None) or (card_d.get("level_info") or {}).get("current_level")
    # 关注数：relation/stat 权威；缺失时用 card.fans 兜底（二者均为公开值）
    followers = stat_d.get("follower")
    if followers is None:
        followers = card_d.get("fans")
    # 投稿数：优先 acc/info，其次 card
    post_count = (acc_d.get("archive_count") if acc else None) or card_d.get("archive_count")
    return {
        "platform": "bilibili",
        "account_id": str(mid),
        "account_name": name,
        "profile_url": f"https://space.bilibili.com/{mid}",
        "bio": bio or None,
        "verified": bool(verified),
        "followers": followers,
        "post_count": post_count,
        "level": level,
        # B站账号层 platform_metrics 应为 {}（获赞总量非统一字段，不进入 Profile）
        "platform_metrics": {},
        "collected_at": _now_iso(),
        "field_visibility": {
            "followers": "visible" if followers is not None else "hidden",
            "post_count": "visible" if post_count is not None else "hidden",
        },
    }


def _copyright_repost(value: Any) -> bool | None:
    """仅当 B 站返回明确 copyright 枚举时标记原创/转载。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        copyright_value = value
    elif isinstance(value, str):
        canonical = value.strip()
        if canonical not in {"1", "2"}:
            return None
        copyright_value = int(canonical)
    else:
        return None
    if copyright_value == 1:
        return False
    if copyright_value == 2:
        return True
    return None


def _build_post_raw_from_medialist(p: dict, url: str) -> dict:
    """medialist/resource/list 条目 → 统一原始字典。

    medialist 端点返回完整 cnt_info（play/thumb_up/coin/collect/reply/danmaku/share），
    无需逐条 view 补全。字段映射（T6 实测）：
      bv_id → bvid, pubtime → published_at, duration(秒),
      tid → typeid, copy_right: 1=原创/2=转载,
      cnt_info.{play,thumb_up,coin,collect,reply,danmaku,share}
      upper.{mid,name} → owner 信息
    """
    bvid = p.get("bv_id") or p.get("bvid")
    if not bvid:
        return _empty_post("")
    cnt = p.get("cnt_info") or {}
    copyright = p.get("copy_right")
    tid = p.get("tid")
    upper = p.get("upper") or {}
    intro = p.get("intro") or ""
    # 合并 tag API 与文本提取的 hashtags（tag API 更权威，在 collect_post_list 中补充）
    hashtags = _extract_hashtags(p.get("title"), intro)
    return {
        "platform": "bilibili",
        "post_id": bvid,
        "post_url": f"{VIDEO}{bvid}",
        "published_at": _to_iso(p.get("pubtime")),
        "content_type": "video",
        "title": p.get("title"),
        "text": intro or None,
        "duration_seconds": _parse_duration(p.get("duration")),
        "hashtags": hashtags,
        "is_pinned": None,  # 由 collect_post_list 根据明确 top/arc 结果回填
        "is_repost": _copyright_repost(copyright),
        "is_promoted": None,
        "views": _int(cnt.get("play")),
        "likes": _int(cnt.get("thumb_up")),
        "comments": _int(cnt.get("reply")),
        "favorites": _int(cnt.get("collect")),
        "shares": _int(cnt.get("share")),
        "coins": _int(cnt.get("coin")),
        "danmaku": _int(cnt.get("danmaku")),
        "collection_status": "ok",
        "collected_at": _now_iso(),
        "source_url": f"{VIDEO}{bvid}",
        "platform_metrics": {
            "typeid": tid,
            "partition": TYPENAME_MAP.get(tid),
            "partition_source": "reference" if tid in TYPENAME_MAP else None,
            "partition_needs_verification": True if tid in TYPENAME_MAP else None,
            "owner_mid": upper.get("mid"),
            "owner_name": upper.get("name"),
        },
    }


def _build_post_raw_from_vlist(p: dict, url: str) -> dict:
    """arc/search vlist 条目 → 统一原始字典。

    注意：vlist **不含** like/favorites/coin/share，仅含 play/comment/
    video_review。这些缺失字段保持 None（honest null），由 view 补全。
    """
    bvid = p.get("bvid") or str(p.get("aid"))
    copyright = p.get("copyright")
    return {
        "platform": "bilibili",
        "post_id": bvid,
        "post_url": f"{VIDEO}{bvid}",
        "published_at": _to_iso(p.get("created") or p.get("pubdate")),
        "content_type": "video",
        "title": p.get("title"),
        "text": p.get("description") or p.get("desc"),
        "duration_seconds": _parse_duration(p.get("length") or p.get("duration")),
        "hashtags": _extract_hashtags(p.get("title"), p.get("description") or p.get("desc")),
        "is_pinned": None,
        "is_repost": _copyright_repost(copyright),
        "is_promoted": None,
        "views": _int(p.get("play")),
        "likes": None,
        "comments": _int(p.get("comment") or p.get("reply")),
        "favorites": None,
        "shares": None,
        "coins": None,
        "danmaku": _int(p.get("video_review")),
        "collection_status": "ok",
        "collected_at": _now_iso(),
        "source_url": f"{VIDEO}{bvid}",
        "platform_metrics": {
            "typeid": p.get("typeid"),
            "typename": p.get("typename"),
            "partition": TYPENAME_MAP.get(p.get("typeid")),
            "partition_source": "reference" if p.get("typeid") in TYPENAME_MAP else None,
            "partition_needs_verification": True if p.get("typeid") in TYPENAME_MAP else None,
        },
    }


def _build_post_raw_from_view(d: dict, url: str) -> dict:
    """web-interface/view 完整响应 → 统一原始字典（含完整 stat）。"""
    bvid = d.get("bvid") or str(d.get("aid"))
    stat = d.get("stat") or {}
    owner = d.get("owner") or {}
    copyright = d.get("copyright")
    tid = d.get("tid")
    partition = TYPENAME_MAP.get(tid, d.get("tname"))
    return {
        "platform": "bilibili",
        "post_id": bvid,
        "post_url": f"{VIDEO}{bvid}",
        "published_at": _to_iso(d.get("pubdate") or d.get("ctime")),
        "content_type": "video",
        "title": d.get("title"),
        "text": d.get("desc"),
        "duration_seconds": _parse_duration(d.get("duration")),
        "hashtags": _extract_hashtags(d.get("title"), d.get("desc")),
        "is_pinned": None,
        "is_repost": _copyright_repost(copyright),
        "is_promoted": None,
        "views": _int(stat.get("view")),
        "likes": _int(stat.get("like")),
        "comments": _int(stat.get("reply")),
        "favorites": _int(stat.get("favorite")),
        "shares": _int(stat.get("share")),
        "coins": _int(stat.get("coin")),
        "danmaku": _int(stat.get("danmaku")),
        "collection_status": "ok",
        "collected_at": _now_iso(),
        "source_url": url,
        "platform_metrics": {
            "partition": partition,
            # 来源标注：静态映射=reference（待官方表核对）；否则回退 API tname=api
            "partition_source": "reference" if (tid in TYPENAME_MAP) else ("api" if d.get("tname") else None),
            "partition_needs_verification": True if (tid in TYPENAME_MAP) else None,
            "owner_mid": owner.get("mid"),
            "owner_name": owner.get("name"),
        },
    }


def _empty_post(bvid: str) -> dict:
    return {
        "platform": "bilibili",
        "post_id": bvid,
        "post_url": f"{VIDEO}{bvid}",
        "content_type": "video",
        "hashtags": [],
        "is_pinned": None,
        "is_repost": None,
        "is_promoted": None,
        "collection_status": "ok",
        "collected_at": _now_iso(),
        "source_url": f"{VIDEO}{bvid}",
        "platform_metrics": {},
    }


def _extract_dynamic_card(it: dict) -> dict | None:
    """从动态 feed item 提取视频类动态卡片；非视频类（无 bvid）返回 None。

    字段路径（来自隔离浏览器工作流 bili_fill2.py 实跑验证）：
      modules.module_author.pub_ts / pub_time
      modules.module_dynamic.major.archive(.bvid/title/stat) 或 major.ugc_season.archive
      modules.module_dynamic.desc.text
      modules.module_stat.{like,comment,forward}.count
      it.orig 非空 → 转发卡
    """
    mods = it.get("modules") or {}
    author = mods.get("module_author") or {}
    md = mods.get("module_dynamic") or {}
    major = md.get("major") or {}
    arch = major.get("archive") or major.get("ugc_season") or {}
    bv = arch.get("bvid")
    if not bv:
        return None
    desc = (md.get("desc") or {}).get("text")
    ms = mods.get("module_stat") or {}
    astat = arch.get("stat") or {}
    pts = author.get("pub_ts")
    try:
        pts = int(pts) if pts is not None else None
    except (TypeError, ValueError):
        pts = None
    return {
        "bvid": bv,
        "title": arch.get("title"),
        "desc": desc,
        "pub_ts": pts,
        "pub_time": author.get("pub_time"),
        "is_forward": bool(it.get("orig")) if "orig" in it else None,
        "stat": {
            "play": astat.get("play"),
            "danmaku": astat.get("danmaku"),
            "like": (ms.get("like") or {}).get("count"),
            "comment": (ms.get("comment") or {}).get("count"),
            "forward": (ms.get("forward") or {}).get("count"),
        },
    }


def _build_dynamic_raw(card: dict) -> dict:
    """动态卡片 → 统一原始字典（content_type=dynamic）。"""
    bv = card.get("bvid")
    st = card.get("stat") or {}
    return {
        "platform": "bilibili",
        "post_id": bv,
        "post_url": f"{VIDEO}{bv}",
        "published_at": _to_iso(card.get("pub_ts")),
        "content_type": "dynamic",
        "title": card.get("title"),
        "text": card.get("desc"),
        "is_pinned": None,
        "is_repost": card.get("is_forward"),
        "is_promoted": None,
        "collection_status": "ok",
        "collected_at": _now_iso(),
        "source_url": f"{VIDEO}{bv}",
        "platform_metrics": {
            "dynamic": {
                "is_dynamic": True,
                "pub_ts": card.get("pub_ts"),
                "play": _int(st.get("play")),
                "danmaku": _int(st.get("danmaku")),
                "like": _int(st.get("like")),
                "comment": _int(st.get("comment")),
                "forward": _int(st.get("forward")),
            },
        },
    }
