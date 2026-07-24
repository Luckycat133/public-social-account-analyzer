"""微博公开账号采集适配器（P1 / 可选平台）。

状态：默认 `ENABLED = False`（P1 扩展项，不阻塞 MVP 验收）。

设计要点：
- 仅用标准库（`urllib`）访问 `weibo.com` 公开账号页；绝不绕过登录 / 验证码 /
  滑块 / 频控（见 `references/exceptions.md` 第 2 节通用原则）。
- 当 `ENABLED = False` 时，所有采集方法都会抛出携带 `ADAPTER_UNAVAILABLE` 的
  `RuntimeError`，使编排器记入 `stop_reason = ADAPTER_UNAVAILABLE` 并**如实停止**，
  绝不假装已采集（见 `references/exceptions.md` §1「适配器未启用」决策表）。
- 当 `ENABLED = True`（未来启用）时，本实现以 urllib best-effort 版骨架占位，
  真实解析尚未落地，仍处于 `NotImplementedError` 的 `ADAPTER_UNAVAILABLE` 语义下；
  届时在此骨架内补齐字段映射即可（映射见 `references/platform-weibo.md`）。
- 字段不可见写 `None`（绝不用 `0` 代替未知）；`favorites` 对微博恒为 `None`。

不实现 Bilibili / Douyin（由各自适配器负责）。
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

from base import BaseCollector  # 适配 scripts/collectors 作为 sys.path 入口

# P1 可选平台：默认关闭，不阻塞 MVP。
ENABLED = False

PLATFORM = "weibo"

# 微博 stop_reason 取值严格对齐 references/exceptions.md §9.2 枚举（字符串值一致）
ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
LOGIN_REQUIRED = "LOGIN_REQUIRED"
VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
PARSER_FAILED = "PARSER_FAILED"
NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"
UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 北京时间为微博默认时区
_BEIJING = timezone(timedelta(hours=8))

# URL 路由正则
_RE_UID = re.compile(r"^https?://weibo\.com/u/\d+(?:[/?].*)?$", re.IGNORECASE)
_RE_NAME = re.compile(r"^https?://weibo\.com/([A-Za-z0-9_\-]+)", re.IGNORECASE)

# 非账号主页的保留一级路径（搜索 / 话题 / 登录等），不匹配为账号主页
_RESERVED_SEGMENTS = frozenset({
    "search", "explore", "hot", "topic", "pub", "home", "login", "signup",
    "help", "about", "m", "p", "s", "wbprofile", "compose", "api", "comments",
    "attitude", "i", "fav", "tv",
})


def _now_iso() -> str:
    return datetime.now(_BEIJING).isoformat()


class WeiboCollector(BaseCollector):
    platform = PLATFORM
    # 与模块级 ENABLED 对齐；默认 False（P1 可选，关闭）。
    ENABLED = ENABLED

    # ------------------------------------------------------------------
    # 启用守卫
    # ------------------------------------------------------------------
    def _require_enabled(self) -> None:
        """当适配器未启用时抛出携带 ADAPTER_UNAVAILABLE 的 RuntimeError。

        编排器捕获后会将任务 `stop_reason` 记 `ADAPTER_UNAVAILABLE`，并如实停止，
        绝不以空数据假装采集已完成。
        """
        if not ENABLED:
            raise RuntimeError(
                f"[{ADAPTER_UNAVAILABLE}] WeiboCollector 未启用（P1 可选平台，"
                "ENABLED=False），采集被拒绝；不得伪装为已采集。"
            )

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    def supports(self, url: str) -> bool:
        """返回 url 是否为微博账号主页（weibo.com/u/<uid> 或 weibo.com/<name>）。

        仅匹配账号主页，不匹配 weibo.com 裸域名、/u 占位、搜索 / 话题等子路径。
        """
        if not isinstance(url, str):
            return False
        u = url.strip()
        if _RE_UID.match(u):
            return True
        m = _RE_NAME.match(u)
        # 排除形如 weibo.com/u（无数字 uid）的占位路径，以及保留一级路径
        if m and m.group(1) != "u" and m.group(1) not in _RESERVED_SEGMENTS:
            return True
        return False

    # ------------------------------------------------------------------
    # 访问检查（不绕过登录 / 验证码）
    # ------------------------------------------------------------------
    def check_access(self, url: str) -> dict[str, Any]:
        """返回账号可访问状态。

        未启用时抛出 ADAPTER_UNAVAILABLE；启用后（TODO）用 urllib 取主页，
        遇登录墙 / 验证码立即停止并上抛对应 stop_reason，绝不绕过。
        """
        self._require_enabled()
        # TODO(enabled): 用 urllib 拉取 weibo.com/u/<uid> 或 weibo.com/<name>，
        # 检测登录墙 / 验证码 / 账号不存在，返回 {status, stop_reason}。
        raise NotImplementedError(
            f"[{ADAPTER_UNAVAILABLE}] WeiboCollector 已启用但 check_access 尚未实现；"
            "请勿在真实采集中使用，待补齐 urllib 解析骨架。"
        )

    # ------------------------------------------------------------------
    # 账号资料
    # ------------------------------------------------------------------
    def collect_profile(self, url: str) -> dict[str, Any]:
        """采集公开账号信息并归一化到统一 Profile schema。

        未启用 → RuntimeError(ADAPTER_UNAVAILABLE)。启用后（TODO）映射：
        account_id=UID, account_name=名称, bio=简介, verified=认证,
        followers=粉丝, post_count=微博数, platform_metrics.following=关注。
        """
        self._require_enabled()
        # TODO(enabled): urllib 拉取主页解析字段，调用 self.normalize_profile(raw)。
        raise NotImplementedError(
            f"[{ADAPTER_UNAVAILABLE}] WeiboCollector 已启用但 collect_profile 尚未实现；"
            "待补齐字段映射：account_id=UID, followers=粉丝, post_count=微博数,"
            "platform_metrics.following=关注。"
        )

    # ------------------------------------------------------------------
    # 内容列表
    # ------------------------------------------------------------------
    def collect_post_list(
        self,
        url: str,
        limit: int = 30,
        date_range: tuple[str | None, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        """采集博文摘要列表，并标记置顶 / 转发微博。

        未启用 → RuntimeError(ADAPTER_UNAVAILABLE)。启用后（TODO）映射：
        post_id=博文ID, title=正文首行, text=正文全文, hashtags=话题,
        content_type=text/image_text/video, is_pinned=置顶, is_repost=转发微博。
        """
        self._require_enabled()
        # TODO(enabled): urllib 拉取博文列表（含置顶 / 转发识别），逐条
        # self.normalize_post(raw)；按 date_range 过滤；limit 截断（默认 30，最大 100）。
        raise NotImplementedError(
            f"[{ADAPTER_UNAVAILABLE}] WeiboCollector 已启用但 collect_post_list 尚未实现；"
            "待补齐：post_id=博文ID, is_pinned=置顶, is_repost=转发微博。"
        )

    # ------------------------------------------------------------------
    # 单条详情
    # ------------------------------------------------------------------
    def collect_post_detail(self, post_url: str) -> dict[str, Any]:
        """采集单条博文详情与公开指标。

        未启用 → RuntimeError(ADAPTER_UNAVAILABLE)。启用后（TODO）映射指标：
        shares=转发, comments=评论, likes=点赞, favorites=null（微博无收藏）。
        """
        self._require_enabled()
        # TODO(enabled): urllib 拉取博文详情，调用 self.normalize_post(raw)；
        # 指标映射 shares=转发, comments=评论, likes=点赞, favorites=null。
        raise NotImplementedError(
            f"[{ADAPTER_UNAVAILABLE}] WeiboCollector 已启用但 collect_post_detail 尚未实现；"
            "待补齐指标映射：shares=转发, comments=评论, likes=点赞, favorites=null。"
        )

    # ------------------------------------------------------------------
    # 评论（best-effort）
    # ------------------------------------------------------------------
    def collect_comments(
        self,
        post_url: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """公开评论采样（best-effort）。

        未启用时直接返回 []（不抛错，符合「评论不可见不影响任务」语义）。
        启用后（TODO）也以 urllib 方式 best-effort 返回；任何限制 / 错误 / 空结果
        一律返回 []。
        """
        if not ENABLED:
            return []
        # TODO(enabled): 用 urllib best-effort 取公开评论；异常 / 受限 / 空 → []。
        return []
