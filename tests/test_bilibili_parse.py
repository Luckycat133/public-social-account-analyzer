"""离线解析测试：用 T3 实跑的真实原始 JSON 验证字段映射与签名。

不依赖网络。运行：
  python tests/test_bilibili_parse.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from collectors.bilibili import (  # noqa: E402
    BilibiliCollector,
    _build_post_raw_from_vlist,
    _build_post_raw_from_view,
    enc_wbi,
    get_mixin_key,
    MIXIN_KEY_ENC_TAB,
)
from collectors.base import BaseCollector  # noqa: E402

# ---- T3 真实原始片段（精简保留关键字段）----
RELATION_STAT = {"code": 0, "data": {"mid": 411581408, "follower": 481139}}
CARD = {
    "code": 0,
    "data": {
        "card": {
            "mid": 411581408,
            "name": "这名玩家",
            "sign": "这名玩家就是我，我就是这名玩家。",
            "level_info": {"current_level": 6},
            "archive_count": 507,
            "fans": 481139,
            "official": {"type": -1, "desc": ""},
            "like_num": 0,
        }
    },
}
ACC = {
    "code": 0,
    "data": {
        "mid": 411581408,
        "name": "这名玩家",
        "sign": "这名玩家就是我，我就是这名玩家。",
        "level": 6,
        "official": {"role": 0, "type": -1},
        "live_room": {"title": "挖空我的世界大陆", "roomid": 26293550},
    },
}
VLIST_ITEM = {
    "comment": 48,
    "typeid": 17,
    "play": 43435,
    "description": "-",
    "copyright": "1",
    "title": "我的世界克苏鲁第五季第20期:初代禁卫军陨落",
    "author": "这名玩家",
    "mid": 411581408,
    "created": 1784602500,
    "length": "01:28",
    "video_review": 33,
    "aid": 116954710933583,
    "bvid": "BV1JMKx6sE6Q",
}
VIEW_DATA = {
    "bvid": "BV1JMKx6sE6Q",
    "aid": 116954710933583,
    "title": "我的世界克苏鲁第五季第20期:初代禁卫军陨落",
    "desc": "desc-text",
    "pubdate": 1784602500,
    "ctime": 1784602500,
    "duration": 88,
    "copyright": 1,
    "tname": "游戏",
    "owner": {"mid": 411581408, "name": "这名玩家"},
    "stat": {
        "view": 43435,
        "like": 1234,
        "reply": 48,
        "favorite": 567,
        "share": 12,
        "coin": 345,
        "danmaku": 33,
    },
}


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(f"断言失败: {label}")


def test_profile():
    c = BilibiliCollector()
    raw = c._build_profile_raw if hasattr(c, "_build_profile_raw") else None
    # _build_profile_raw 是模块级函数
    from collectors.bilibili import _build_profile_raw
    raw = _build_profile_raw("411581408", CARD, RELATION_STAT, ACC["data"])
    prof = c.normalize_profile(raw)
    print("profile:", json.dumps(prof, ensure_ascii=False))
    check("account_id", prof["account_id"] == "411581408")
    check("account_name", prof["account_name"] == "这名玩家")
    check("followers=481139", prof["followers"] == 481139)
    check("post_count=507", prof["post_count"] == 507)
    check("verified=False(官方type=-1)", prof["verified"] is False)
    check("level=6(acc.level 优先)", prof["level"] == 6)
    check("platform_metrics 为 {} (B站不进 total_likes)", prof["platform_metrics"] == {})
    check("field_visibility followers public", prof["field_visibility"]["followers"] == "public")
    # 兜底路径：stat=None 且 acc=None 时 level 取 card.level_info.current_level
    raw2 = _build_profile_raw("411581408", CARD, None, None)
    prof2 = c.normalize_profile(raw2)
    check("fallback followers=card.fans(481139)", prof2["followers"] == 481139)
    check("fallback level=card.level_info(6)", prof2["level"] == 6)


def test_vlist():
    raw = _build_post_raw_from_vlist(VLIST_ITEM, "https://www.bilibili.com/video/BV1JMKx6sE6Q")
    post = BilibiliCollector().normalize_post(raw)
    print("vlist post:", json.dumps(post, ensure_ascii=False))
    check("post_id=BV", post["post_id"] == "BV1JMKx6sE6Q")
    check("views=43435(play)", post["views"] == 43435)
    check("comments=48(comment 字段,非 reply)", post["comments"] == 48)
    check("danmaku=33(video_review)", post["danmaku"] == 33)
    check("likes=None(vlist 无 like)", post["likes"] is None)
    check("favorites=None(vlist 无 favorites)", post["favorites"] is None)
    check("is_repost=False(copyright=1)", post["is_repost"] is False)
    check("duration_seconds=88(01:28)", post["duration_seconds"] == 88)
    check("published_at ISO", post["published_at"].startswith("20"))
    # I4: vlist 的 typeid=17 应静态映射为子分区「单机游戏」
    check("partition=单机游戏(typeid静态映射)", post["platform_metrics"]["partition"] == "单机游戏")


def test_view():
    raw = _build_post_raw_from_view(VIEW_DATA, "https://www.bilibili.com/video/BV1JMKx6sE6Q")
    post = BilibiliCollector().normalize_post(raw)
    print("view post:", json.dumps(post, ensure_ascii=False))
    check("views=43435", post["views"] == 43435)
    check("likes=1234(来自 stat.like)", post["likes"] == 1234)
    check("comments=48(stat.reply)", post["comments"] == 48)
    check("favorites=567(stat.favorite)", post["favorites"] == 567)
    check("shares=12(stat.share)", post["shares"] == 12)
    check("coins=345(stat.coin)", post["coins"] == 345)
    check("danmaku=33(stat.danmaku)", post["danmaku"] == 33)
    check("partition in platform_metrics", post["platform_metrics"]["partition"] == "游戏")
    # normalize_post 必须保留 platform_metrics 与指标
    check("normalize_post 保留 platform_metrics", "partition" in post["platform_metrics"])
    check("normalize_post 透传 views", post["views"] == 43435)


def test_wbi():
    mk = get_mixin_key("a" * 64)
    check("mixin_key 长度 32", len(mk) == 32)
    check("mixin_key 仅含原字符", all(c in "a" for c in mk))
    signed = enc_wbi(
        {"mid": "411581408", "web_location": "333.1007"},
        "a" * 32,
        "b" * 32,
    )
    check("w_rid 存在且 32 位 hex", isinstance(signed.get("w_rid"), str) and len(signed["w_rid"]) == 32)
    check("wts 存在", "wts" in signed)
    check("web_location 参与签名(仍在参数中)", signed.get("web_location") == "333.1007")
    check("mixin 表长度 64", len(MIXIN_KEY_ENC_TAB) == 64)


def test_stop_reason_codes():
    from collectors.bilibili import (
        _stop_reason_for_code,
        STOP_VERIFICATION,
        STOP_ACCESS_RESTRICTED,
        STOP_ACCOUNT_UNAVAILABLE,
        STOP_LOGIN,
    )
    # M3: -400 重试耗尽应归 ACCESS_RESTRICTED（间歇型风控），非账号不可用
    check("-400 → ACCESS_RESTRICTED", _stop_reason_for_code(-400) == STOP_ACCESS_RESTRICTED)
    # I2 已修：-401/-352 直接归 VERIFICATION_REQUIRED，不再重试
    check("-401 → VERIFICATION_REQUIRED", _stop_reason_for_code(-401) == STOP_VERIFICATION)
    check("-352 → VERIFICATION_REQUIRED", _stop_reason_for_code(-352) == STOP_VERIFICATION)
    check("-404 → ACCOUNT_UNAVAILABLE", _stop_reason_for_code(-404) == STOP_ACCOUNT_UNAVAILABLE)
    check("-403 → ACCESS_RESTRICTED", _stop_reason_for_code(-403) == STOP_ACCESS_RESTRICTED)
    check("login 关键字 → LOGIN_REQUIRED", STOP_LOGIN == "LOGIN_REQUIRED")


def test_non_json_captcha():
    from collectors.bilibili import Session, BilibiliError, STOP_VERIFICATION, STOP_LOGIN

    def _fake_curl(self, url, referer):
        return "<html>verify_captcha required 请输入验证码完成滑块验证</html>"

    s = Session()
    s._curl = lambda url, referer: _fake_curl(s, url, referer)
    try:
        s.get_json("/x/web-interface/view", {"bvid": "BV1"}, retry=1)
        raise SystemExit("I3 失败：非 JSON 验证码页未上抛")
    except BilibiliError as e:
        check("验证码HTML → VERIFICATION_REQUIRED", e.stop_reason == STOP_VERIFICATION)

    def _fake_login(self, url, referer):
        return "<html>请先登录后查看 login</html>"

    s2 = Session()
    s2._curl = lambda url, referer: _fake_login(s2, url, referer)
    try:
        s2.get_json("/x/web-interface/view", {"bvid": "BV1"}, retry=1)
        raise SystemExit("I3 失败：登录墙页未上抛")
    except BilibiliError as e:
        check("登录墙HTML → LOGIN_REQUIRED", e.stop_reason == STOP_LOGIN)



def test_profile_luckycat():
    """T2/T3 回归守卫：幸运的一只猫真实形态（level=5, archive_count=98）。
    锁定「level 透传 / post_count 来自 archive_count / platform_metrics 不漏 collection_status」"""
    from collectors.bilibili import _build_profile_raw
    c = BilibiliCollector()
    card = {"data": {"card": {"name": "幸运的一只猫",
                              "sign": "我是生活区还是游戏区的？", "fans": 258,
                              "level_info": {"current_level": 0}}}}
    stat = {"data": {"follower": 258}}
    acc = {"name": "幸运的一只猫", "sign": "我是生活区还是游戏区的？",
           "level": 5, "archive_count": 98, "official": {"role": 0}}
    prof = c.normalize_profile(_build_profile_raw("518388027", card, stat, acc))
    check("luckycat level=5(acc.level 顶层)", prof["level"] == 5)
    check("luckycat post_count=98(archive_count)", prof["post_count"] == 98)
    check("luckycat platform_metrics 清洁({})", prof["platform_metrics"] == {})
    check("luckycat followers=258", prof["followers"] == 258)
    # archive_count 缺失时保持 None（绝不拿枚举子集大小回填）
    acc2 = dict(acc); acc2.pop("archive_count")
    prof2 = c.normalize_profile(_build_profile_raw("518388027", card, stat, acc2))
    check("archive_count 缺失 → post_count=None(不回填子集)", prof2["post_count"] is None)


def _mk_dyn_item(bvid, is_forward=False, with_bvid=True):
    item = {
        "type": "DYNAMIC_TYPE_AV",
        "orig": ({"something": 1} if is_forward else None),
        "modules": {
            "module_author": {"pub_ts": 1783827003, "pub_time": "07月12日"},
            "module_dynamic": {
                "desc": {"text": None},
                "major": {"archive": {
                    "bvid": (bvid if with_bvid else ""),
                    "title": f"title-{bvid}",
                    "stat": {"play": "117", "danmaku": "1"},
                }},
            },
            "module_stat": {"like": {"count": 8}, "comment": {"count": 2}, "forward": {"count": 0}},
        },
    }
    return item


def test_dynamics_parse():
    """T4：动态卡片解析 + 归一化。"""
    from collectors.bilibili import _extract_dynamic_card, _build_dynamic_raw
    c = BilibiliCollector()
    # 普通视频动态
    card = _extract_dynamic_card(_mk_dyn_item("BVdyn01", is_forward=False))
    check("动态卡提取 bvid", card["bvid"] == "BVdyn01")
    check("动态卡 is_forward=False", card["is_forward"] is False)
    check("动态卡 play 原始为 str(117)", card["stat"]["play"] == "117")
    post = c.normalize_post(_build_dynamic_raw(card))
    check("动态 content_type=dynamic(对齐 data-schema §9.4)", post["content_type"] == "dynamic")
    check("动态 platform_metrics.dynamic 存在", post["platform_metrics"]["dynamic"]["is_dynamic"] is True)
    check("动态 dynamic.like=8", post["platform_metrics"]["dynamic"]["like"] == 8)
    check("动态 dynamic.play=str→int(117)", post["platform_metrics"]["dynamic"]["play"] == 117)
    check("动态 published_at 来自 pub_ts", post["published_at"].startswith("20"))
    # 转发卡
    fwd = _extract_dynamic_card(_mk_dyn_item("BVdyn02", is_forward=True))
    check("转发卡 is_forward=True", fwd["is_forward"] is True)
    # 非视频类（无 bvid）应被丢弃
    none_card = _extract_dynamic_card(_mk_dyn_item("", with_bvid=False))
    check("非视频动态(无bvid)→None", none_card is None)


def test_discover_dynamics_pagination():
    """T4：discover_dynamics 分页——偶发空页靠 empty_streak 守卫，不无限循环。"""
    from collectors.bilibili import Session, _extract_dynamic_card
    class _FakeSession(Session):
        def __init__(self):
            super().__init__()
            self.calls = 0
        def get_json(self, path, params=None, wbi=False, referer=None, retry=3):
            self.calls += 1
            if self.calls == 1:
                return {"code": 0, "data": {"has_more": True, "offset": "A",
                        "items": [_mk_dyn_item("BVp1"), _mk_dyn_item("BVp2")]}}
            # 后续全是空页（has_more 仍 True）→ 应在 empty_streak>=2 时中止
            return {"code": 0, "data": {"has_more": True, "offset": "A", "items": []}}
    s = _FakeSession()
    cards = s.discover_dynamics("123", 100)
    check("discover_dynamics 返回 2 条", len(cards) == 2)
    check("discover_dynamics 未无限循环(calls<=5)", s.calls <= 5)
    check("discover_dynamics 调用了 _extract_dynamic_card", cards[0]["bvid"] == "BVp1")


def test_collect_dynamics_callable():
    check("BilibiliCollector 已实现 collect_dynamics", hasattr(BilibiliCollector, "collect_dynamics"))


def test_partition_reference_flag():
    """I4 残留项：分区来自静态参考映射(TYPENAME_MAP)时，必须标注
    partition_needs_verification=True（待官方分区表核对，不可伪装成 API 实时值）；
    来自 API tname 时不标。"""
    from collectors.bilibili import _build_post_raw_from_vlist, _build_post_raw_from_view

    # vlist typeid=17 → 单机游戏（参考映射）
    v = _build_post_raw_from_vlist(VLIST_ITEM, "url")
    check("vlist partition_source=reference", v["platform_metrics"]["partition_source"] == "reference")
    check("vlist partition_needs_verification=True", v["platform_metrics"]["partition_needs_verification"] is True)

    # view 无 tid、tname=游戏 → 来自 API，不标 needs_verification
    vw = _build_post_raw_from_view(VIEW_DATA, "url")
    check("view partition_source=api(来自tname)", vw["platform_metrics"]["partition_source"] == "api")
    check("view partition_needs_verification=None(非参考)", vw["platform_metrics"]["partition_needs_verification"] is None)

    # view 带 tid=17（在参考映射中）→ reference + needs_verification
    view_ref = dict(VIEW_DATA)
    view_ref["tid"] = 17
    vw2 = _build_post_raw_from_view(view_ref, "url")
    check("view(tid=17) partition=单机游戏", vw2["platform_metrics"]["partition"] == "单机游戏")
    check("view(tid=17) partition_source=reference", vw2["platform_metrics"]["partition_source"] == "reference")
    check("view(tid=17) partition_needs_verification=True", vw2["platform_metrics"]["partition_needs_verification"] is True)


if __name__ == "__main__":
    test_wbi()
    test_profile()
    test_vlist()
    test_view()
    test_stop_reason_codes()
    test_non_json_captcha()
    test_profile_luckycat()
    test_partition_reference_flag()
    test_dynamics_parse()
    test_discover_dynamics_pagination()
    test_collect_dynamics_callable()
    print("\n全部离线断言通过 ✅")
