"""B站传输层：常量 / 异常 / WBI 签名 / curl Session。

仅依赖标准库（subprocess 调 curl / json / hashlib），不依赖业务层。
本模块从原 bilibili.py 拆分而来，bilibili.py 通过 re-export 保持对外契约不变。

为什么用 curl 而非 urllib：B站 WAF 会直接拒绝 urllib 直连的 HTTP 层（返回
HTTP 412），而 curl 携带完整浏览器头（Origin / Sec-Fetch / --compressed）可正常
通过。以下实现路径由 T3 实跑验证（game 区个人 up 主 mid=411581408）：
  - buvid3/buvid4 前置（finger/spi，JSON 直接返回 b_3/b_4，无需解析 Set-Cookie）
  - 高风险层 space 接口必须走 wbi 签名，且签名字典**必须含 web_location**（注意：acc/info 用 333.1007，arc/search 用 333.1387，用错会导致签名被拒 -799）
  - 正确路径为 /x/space/wbi/acc/info 与 /x/space/wbi/arc/search
  - 风控为概率型（-799 限流 / -352 v_voucher / -401 验证码）：换全新 buvid cookie
    + 完整头 + 退避重试可偶发通过；穷尽重试仍失败才如实上抛 stop_reason

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
from functools import reduce
from typing import Any

from ._constants import (
    STOP_LOGIN,
    STOP_VERIFICATION,
    STOP_ACCESS_RESTRICTED,
    STOP_ACCOUNT_UNAVAILABLE,
    STOP_INTERNAL,
    STOP_UNSUPPORTED,
)
from ._utils import ts_to_iso as _to_iso
from .browser_backend import BrowserError

# 端点与 UA
API = "https://api.bilibili.com"
WEB = "https://space.bilibili.com"
VIDEO = "https://www.bilibili.com/video/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# WBI 置换表（bilibili-api-collect 项目权威值，长度 64，元素 0-63）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43,
    5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16,
    24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59,
    6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# 机会型瞬态码：可换 fresh buvid + 退避重试；穷尽后上抛 stop_reason。
# 仅含「概率型风控拦截」：-412/-799/-403（端点级/进阶风控）、-400（间歇型拒绝，重试常可恢复）。
# 注意：-401/-352 属验证码/滑块场景，按合规边界必须立即停止、绝不重试（见 _stop_reason_for_code 映射 VERIFICATION_REQUIRED）。
TRANSIENT = {-412, -799, -403, -400}
# space 类 wbi 接口的 web_location（签名字典必须包含，否则签名被拒 -412）
# 注意：不同 space 子接口要求不同 web_location：
#   - acc/info   → 333.1007
#   - arc/search → 333.1387（用错会导致 -799 签名被拒，退化到 search/type 仅得少量结果）
WEB_LOCATION_SPACE = "333.1007"
WEB_LOCATION_ARC = "333.1387"


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------
class BilibiliError(Exception):
    """采集错误，携带 stop_reason 供上层决策（不绕过、如实上抛）。"""

    def __init__(self, stop_reason: str, message: str, raw: Any = None):
        super().__init__(message)
        self.stop_reason = stop_reason
        self.message = message
        self.raw = raw


class _Retryable(BilibiliError):
    """HTTP 主路径下可退避重试的错误（瞬态风控码与非 JSON 拦截页）。

    区别于不可重试的 BilibiliError（如 -404 账号不存在、-101 需原样返回的登录墙）：
    本类仅用于「换 fresh buvid + 退避后有机会恢复」的场景，供 get_json 的循环识别并继续重试。
    其 stop_reason / message / raw 均忠实继承，最终上抛时信息不丢失。
    """


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
        -400: STOP_ACCESS_RESTRICTED,  # 间歇型风控拒绝，重试耗尽归访问受限而非账号不可用
        -101: STOP_ACCESS_RESTRICTED,
    }.get(code, STOP_ACCESS_RESTRICTED)


def _backoff(attempt: int) -> float:
    return min(30.0, 3.0 * (2 ** attempt))


# --------------------------------------------------------------------------
# HTTP 会话（curl 传输层 + B站投稿发现策略）
# --------------------------------------------------------------------------
class Session:
    def __init__(self, timeout: int = 10, min_interval: float = 1.2, browser_fallback: bool = False):
        self.cookies: dict[str, str] = {}
        self.timeout = timeout
        self.min_interval = min_interval
        self._last = 0.0
        self._wbi: tuple[str, str] | None = None
        # 浏览器降级（可选、默认关闭）：仅当 HTTP 主路径因出口 IP 被 WAF 封禁而全部重试失败时，
        # 改由运行环境的浏览器进程经真实网络出口再试一次。绝不用于绕过验证码/登录墙/频控。
        # 优先级：构造参数 > 环境变量 BILIBILI_BROWSER_FALLBACK=1。
        self._browser_fallback = bool(browser_fallback) or (
            os.environ.get("BILIBILI_BROWSER_FALLBACK") == "1"
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
            raise BilibiliError(STOP_ACCESS_RESTRICTED, f"curl 超时: {url}")
        if proc.returncode != 0:
            raise BilibiliError(
                STOP_ACCESS_RESTRICTED,
                f"curl 失败 rc={proc.returncode}: {proc.stderr[:200]}",
            )
        return proc.stdout

    def get_json(
        self,
        path: str,
        params=None,
        wbi: bool = False,
        referer: str = WEB,
        retry: int = 3,
        raise_on_error: bool = True,
    ) -> dict:
        """取 JSON。

        主路径：标准库 curl 直连，遇瞬态风控码(-412/-799/-403/-400)与非 JSON 拦截页
        退避重试。全部重试耗尽且命中 WAF 时，若启用浏览器降级（见 _browser_fallback），
        则改由运行环境的浏览器进程经真实网络出口再试一次（仅传输层降级，绝不绕过
        验证码/登录墙/频控）。nav 的 -101 需原样返回以取 wbi_img（raise_on_error=False）。
        """
        q = dict(params or {})
        if wbi:
            if self._wbi is None:
                self._refresh_wbi()
            q = enc_wbi(q, self._wbi[0], self._wbi[1])
        full = API + path + (("?" + urllib.parse.urlencode(q)) if q else "")
        last_exc: BilibiliError | None = None
        # --- 主路径：HTTP(curl) 退避重试 ---
        for attempt in range(retry):
            try:
                body = self._curl(full, referer)
            except BilibiliError as e:
                last_exc = e
                if attempt < retry - 1:
                    self.ensure_buvid(force=True)
                    time.sleep(_backoff(attempt))
                    continue
                break
            try:
                return self._parse_and_check(body, path, raise_on_error)
            except _Retryable as e:
                last_exc = e
                if attempt < retry - 1:
                    self.ensure_buvid(force=True)
                    time.sleep(_backoff(attempt))
                    continue
                break
            except BilibiliError as e:
                # 明确的登录/验证码限制不是瞬态 WAF，不能重试或改走浏览器。
                if e.stop_reason in (STOP_LOGIN, STOP_VERIFICATION):
                    raise
                last_exc = e
                break
        # --- 可选降级：浏览器（仅当主路径因 WAF 失败且显式启用）---
        if last_exc is not None and self._browser_fallback:
            try:
                body = self._fetch_via_browser(full, referer)
            except BrowserError as be:
                last_exc = BilibiliError(
                    STOP_ACCESS_RESTRICTED, f"浏览器降级也失败: {be}"
                )
            else:
                try:
                    return self._parse_and_check(body, path, raise_on_error)
                except BilibiliError as e:
                    last_exc = e
        raise last_exc or BilibiliError(STOP_INTERNAL, "unreachable")

    def _parse_and_check(
        self, body: str, path: str, raise_on_error: bool
    ) -> dict:
        """解析响应体并按业务码决策：成功返回 data；瞬态/非 JSON 抛 _Retryable（可重试）；
        其余非 0 码抛 BilibiliError（stop_reason）。"""
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            e = self._non_json_error(path, body)
            # 登录墙和验证码页是明确的合规停止条件；只有无法判定的非 JSON
            # 拦截响应才可作为短暂传输异常重试。
            if e.stop_reason in (STOP_LOGIN, STOP_VERIFICATION):
                raise e
            raise _Retryable(e.stop_reason, e.message, e.raw)
        code = data.get("code")
        if code == 0 or code is None:
            return data
        if not raise_on_error:
            return data
        if code in TRANSIENT:
            msg = f"{path} code={code} {data.get('message')}"
            if code == -403:
                # 诊断提示：持续 -403 通常意味着 WBI 签名实现问题，而非概率型风控。
                msg = (
                    f"疑似 WBI 签名错误(-403)：请核对 web_location 取值与签名实现 "
                    f"({path} {data.get('message')})"
                )
            raise _Retryable(STOP_ACCESS_RESTRICTED, msg, data)
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
        from .browser_backend import BrowserSession, find_browser

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
        """响应体非 JSON（大概率是验证码/拦截 HTML 页）。轻量检测关键字：
        命中 verify_captcha/验证码/滑块/geetest → VERIFICATION_REQUIRED；
        命中 login/登录 → LOGIN_REQUIRED；否则归 ACCESS_RESTRICTED。"""
        low = (body or "").lower()
        if any(k in low for k in ("verify_captcha", "验证码", "滑块", "geetest")):
            return BilibiliError(
                STOP_VERIFICATION, f"非 JSON 响应疑似验证码/滑块拦截页: {path}"
            )
        if "login" in low or "登录" in low:
            return BilibiliError(STOP_LOGIN, f"非 JSON 响应疑似登录墙: {path}")
        return BilibiliError(
            STOP_ACCESS_RESTRICTED, f"非 JSON 响应: {path}", (body or "")[:500]
        )

    def _refresh_wbi(self) -> None:
        data = self.get_json("/x/web-interface/nav", retry=2, raise_on_error=False)
        wbi = (data.get("data") or {}).get("wbi_img") or {}
        img = re.sub(r"\.png$", "", (wbi.get("img_url") or "").rsplit("/", 1)[-1])
        sub = re.sub(r"\.png$", "", (wbi.get("sub_url") or "").rsplit("/", 1)[-1])
        if not img or not sub:
            raise BilibiliError(STOP_ACCESS_RESTRICTED, "nav 未返回 wbi_img 密钥")
        self._wbi = (img, sub)

    def ensure_buvid(self, force: bool = False) -> None:
        if self.cookies.get("buvid3") and not force:
            return
        try:
            data = self.get_json("/x/frontend/finger/spi", retry=2)
            d = data.get("data") or {}
            if d.get("b_3"):
                self.cookies["buvid3"] = d["b_3"]
            if d.get("b_4"):
                self.cookies["buvid4"] = d["b_4"]
        except BilibiliError:
            pass

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
                raise BilibiliError(
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

    def collect_pinned(self, mid: str) -> str | None:
        """获取置顶视频 BV号。端点 /x/space/top/arc（免 wbi、稳定）。

        无置顶时返回 None。失败时返回 None（不阻塞主流程）。
        """
        try:
            data = self.get_json(
                "/x/space/top/arc",
                {"vmid": mid},
                wbi=False,
                retry=2,
            )
            if data.get("code") == 0 and data.get("data"):
                return data["data"].get("bvid")
        except BilibiliError:
            pass
        return None

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
        except BilibiliError:
            pass
        return []

    def discover_arc(self, mid: str, limit: int) -> list:
        """降级 A：wbi 签名的 space 投稿列表(自动翻页至 limit 或末页)。失败抛 BilibiliError 由上层降级。"""
        out: list = []
        ps = 50
        pn = 1
        while len(out) < limit:
            if pn > 1:
                # 翻页间隔：arc/search 对突发频控敏感(-412)，间隔 + 轮换 buvid 可显著降低被拦
                time.sleep(6)
                self.ensure_buvid(force=True)
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
                raise BilibiliError(
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
            raise BilibiliError(
                STOP_ACCESS_RESTRICTED, f"无法解析昵称进行 search 降级 (mid={mid})"
            )
        data = self.get_json(
            "/x/web-interface/search/type",
            {"search_type": "bili_user", "keyword": name, "page": 1},
        )
        if data.get("code") != 0:
            raise BilibiliError(STOP_ACCESS_RESTRICTED, "search/type 降级失败")
        res_data = data.get("data") or {}
        target = next(
            (r for r in res_data.get("result", [])
             if str(r.get("mid")) == str(mid)),
            None,
        )
        if not target:
            raise BilibiliError(STOP_ACCESS_RESTRICTED, "search/type 未匹配到该账号")
        return [it["bvid"] for it in target.get("res", []) if it.get("bvid")][:limit]

    def discover_dynamics(self, mid: str, limit: int) -> list:
        """空间动态 feed（视频类动态）。WBI 签名 + web_location=333.1007。

        分页用 offset + has_more；B站动态 feed 偶发返回空页（has_more 仍为 true），
        故用 empty_streak 守卫避免死循环。仅视频类动态（含 bvid）入列；转发卡
        (orig 非空) 也保留 bvid 但标记 is_forward。失败（风控）则已采到的先返回。
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
                break  # 风控/失败：返回已采到的
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
# 动态卡片解析（Session.discover_dynamics 用）
# --------------------------------------------------------------------------
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
        "is_forward": bool(it.get("orig")),
        "stat": {
            "play": astat.get("play"),
            "danmaku": astat.get("danmaku"),
            "like": (ms.get("like") or {}).get("count"),
            "comment": (ms.get("comment") or {}).get("count"),
            "forward": (ms.get("forward") or {}).get("count"),
        },
    }
