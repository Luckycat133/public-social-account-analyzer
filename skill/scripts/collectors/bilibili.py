"""B站公开账号采集适配器（P0）业务层。

实现统一适配器接口：supports / check_access / collect_profile /
collect_post_list / collect_post_detail / collect_comments / collect_dynamics。

传输层（HTTP / WBI 签名 / Session / 异常）已拆分至 `_bilibili_transport`，
本模块通过 re-export 保持对外契约不变（测试与上层脚本可继续
`from collectors.bilibili import BilibiliError, Session, enc_wbi, ...`）。

合规边界（见 SKILL.md 与 references/platform-bilibili.md）：
- 不登录、不绕过验证码 / WBI / 频控；遇阻停止并抛 BilibiliError(stop_reason)。
- 字段不可见写 None（绝不用 0 代替未知）。
- 不分析、不存储，只返回结构化原始数据（由上层脚本落盘）。
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from .base import BaseCollector
from ._constants import (  # 共享常量（re-export：测试通过 from collectors.bilibili import STOP_* 仍可用）
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
    ts_to_iso as _to_iso,
    extract_hashtags as _extract_hashtags,
)
# 传输层：常量 / 异常 / WBI 签名 / curl Session / 动态卡解析（re-export 保持对外契约）
from ._bilibili_transport import (  # noqa: F401 (re-export)
    API,
    WEB,
    VIDEO,
    UA,
    MIXIN_KEY_ENC_TAB,
    TRANSIENT,
    WEB_LOCATION_SPACE,
    WEB_LOCATION_ARC,
    BilibiliError,
    _Retryable,
    Session,
    get_mixin_key,
    enc_wbi,
    _stop_reason_for_code,
    _backoff,
    _extract_dynamic_card,
)

# 分区静态映射（typeid -> 子分区）。来源：references/platform-bilibili.md §分区中文名缺口结论
# （第 2 层：独立浏览器工作流产出、高置信、待官方分区表核对；尤其 249/250 待核对）。
# 现实 API 的 tname/tname_v2 已实测为空，故分区只能靠此静态映射，并在输出标注来源。
TYPENAME_MAP = {
    17: "单机游戏", 21: "日常", 25: "MMD·3D", 28: "原创音乐", 31: "翻唱",
    65: "网络游戏", 95: "数码", 138: "搞笑", 171: "电子竞技", 172: "手机游戏",
    212: "美食侦探", 218: "喵星人", 249: "足球", 250: "出行",  # 249/250 待官方表核对
}


# --------------------------------------------------------------------------
# B站特有业务工具（_now_iso / _int / _to_iso / _extract_hashtags 已下沉至 _utils.py）
# --------------------------------------------------------------------------
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

    # -- 路由 --
    def supports(self, url: str) -> bool:
        # 仅接受账号主页：https://space.bilibili.com/<digits>
        # 允许 http/https、可选尾部斜杠、可选 ?query；拒绝子域名、裸域名与
        # 任何额外路径段（/dynamic、/video、/search 等）。
        if not isinstance(url, str):
            return False
        return bool(
            re.match(r"^https?://space\.bilibili\.com/\d+/?(/\?[^/]*)?$", url.strip())
        )

    # -- 访问检查（不绕过） --
    def check_access(self, url: str) -> dict:
        mid = _mid_from_url(url)
        s = Session()
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
        s = Session()
        s.ensure_buvid()

        # card(免wbi) 稳定保底；关注数优先 relation/stat，失败用 card.fans 兜底
        card = s.get_json("/x/web-interface/card", {"mid": mid})
        stat = None
        try:
            stat = s.get_json("/x/relation/stat", {"mid": mid}, retry=2)
            if stat.get("code") != 0:
                stat = None
        except BilibiliError:
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
        except BilibiliError:
            acc = None

        return self.normalize_profile(_build_profile_raw(mid, card, stat, acc))

    # -- 视频列表 --
    def collect_post_list(self, url: str, limit: int = 30, date_range=None) -> list:
        mid = _mid_from_url(url)
        s = Session()
        s.ensure_buvid()

        # 置顶视频检测（top/arc，免 wbi、稳定）——用于标记 is_pinned
        pinned_bvid = s.collect_pinned(mid)

        # 三级降级链：medialist(免wbi+完整指标) → arc/search(wbi) → search/type(BV列表)
        entries = None
        source = None

        # 首选：medialist/resource/list（免 wbi、返回完整 cnt_info、无 412 风控）
        try:
            entries = s.discover_medialist(mid, limit)
            source = "medialist"
        except BilibiliError:
            entries = None

        # 降级 A：arc/search（wbi + web_location=333.1387）
        if not entries:
            try:
                entries = s.discover_arc(mid, limit)
                source = "arc"
            except BilibiliError:
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
                except BilibiliError:
                    pass  # 保留 vlist 级数据（honest null）
            else:
                base = _empty_post(bvid)
                # search 降级仅有 BV，必须 view 补全
                try:
                    v = s.get_json("/x/web-interface/view", {"bvid": bvid})
                    if v.get("code") == 0:
                        base = _build_post_raw_from_view(v["data"], url)
                        any_view_ok = True
                except BilibiliError:
                    pass

            # 权威标签补全：tag API（/x/tag/archive/tags）更权威，合并进 base.hashtags。
            # 仅作增量增强，失败不影响主流程（collect_tags 内部已吞异常返回 []）。
            try:
                api_tags = s.collect_tags(bvid)
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
            if pinned_bvid and bvid == pinned_bvid:
                base["is_pinned"] = True

            posts.append(self.normalize_post(base))

        if not posts:
            raise BilibiliError(
                STOP_ACCESS_RESTRICTED,
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
                STOP_ACCESS_RESTRICTED,
                f"search 降级且全部 view 补全失败 (mid={mid})",
            )
        return posts

    # -- 单条详情 --
    def collect_post_detail(self, post_url: str) -> dict:
        m = re.search(r"BV[0-9A-Za-z]+", post_url)
        if not m:
            raise BilibiliError(STOP_UNSUPPORTED, f"无法解析 BV: {post_url}")
        bv = m.group(0)
        s = Session()
        s.ensure_buvid()
        data = s.get_json("/x/web-interface/view", {"bvid": bv})
        if data.get("code") != 0:
            raise BilibiliError(
                _stop_reason_for_code(data.get("code")),
                f"view 失败: {data.get('message')}",
                data,
            )
        view_data = data.get("data")
        if not view_data:
            raise BilibiliError(STOP_ACCESS_RESTRICTED, "view 响应数据为空")
        return self.normalize_post(_build_post_raw_from_view(view_data, post_url))

    # -- 评论采集（best-effort，urllib-only，免登录） --
    def collect_comments(self, post_url: str, limit: int = 20) -> list[dict]:
        """取公开评论（best-effort）。任何限制/错误/空结果一律返回 []。"""
        try:
            m = re.search(r"BV[0-9A-Za-z]+", post_url)
            if not m:
                return []
            bvid = m.group(0)
            aid = self._bv_to_aid_urllib(bvid)
            if aid is None:
                return []
            api = (
                "https://api.bilibili.com/x/v2/reply"
                f"?type=1&oid={aid}&mode=3&next=0"
            )
            req = urllib.request.Request(
                api,
                headers={"User-Agent": UA, "Referer": VIDEO},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") != 0:
                return []
            replies = (data.get("data") or {}).get("replies") or []
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
        except Exception:
            return []

    # -- 空间动态视频 feed（best-effort，合规同主路径） --
    def collect_dynamics(self, url: str, limit: int = 30) -> list[dict]:
        """采集空间动态中的视频类动态（content_type=dynamic）。

        走与主路径相同的 curl+wbi Session；动态 feed 端点为
        x/polymer/web-dynamic/v1/feed/space（web_location=333.1007，见 discover_dynamics）。
        受风控时 discover_dynamics 返回已采到的子集，此处原样透传；若全部失败
        （返回空），由上层判定 PARTIAL/停止，绝不伪装成功。
        """
        mid = _mid_from_url(url)
        s = Session()
        s.ensure_buvid()
        try:
            cards = s.discover_dynamics(mid, limit)
        except BilibiliError as e:
            raise e
        return [self.normalize_post(_build_dynamic_raw(c)) for c in cards]

    @staticmethod
    def _bv_to_aid_urllib(bvid: str) -> int | None:
        """用 view 接口（urllib）把 BV 号解析为 aid；失败返回 None。"""
        try:
            api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            req = urllib.request.Request(
                api,
                headers={"User-Agent": UA, "Referer": VIDEO},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") != 0:
                return None
            return data.get("data", {}).get("aid")
        except Exception:
            return None


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
        "is_pinned": False,  # 由 collect_post_list 根据 top/arc 结果回填
        "is_repost": copyright == 2,
        "is_promoted": False,
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
    copyright = _int(p.get("copyright"))
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
        "is_pinned": False,
        "is_repost": copyright == 2,
        "is_promoted": False,
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
        "is_pinned": False,
        "is_repost": copyright == 2,
        "is_promoted": False,
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
        "is_pinned": False,
        "is_repost": False,
        "is_promoted": False,
        "collection_status": "ok",
        "collected_at": _now_iso(),
        "source_url": f"{VIDEO}{bvid}",
        "platform_metrics": {},
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
        "is_pinned": False,
        "is_repost": card.get("is_forward"),
        "is_promoted": False,
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
