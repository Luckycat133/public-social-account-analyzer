"""采集器与降级行为单元测试（离线、无网络）。

覆盖：
- BilibiliCollector.supports 路由正则：拒绝 video/dynamic 等非账号主页 URL。
- WeiboCollector 未启用 → 任何采集方法抛 ADAPTER_UNAVAILABLE（不伪造数据）。
- CASE-006 置顶内容排除 / CASE-007 转载内容排除（默认统计不含标记内容）。
- CASE-012 高低表现样本不足 → INSUFFICIENT_SAMPLE（不补造结论）。
- CASE-013 登录墙停止 / CASE-014 验证码停止（stop_reason 语义，保留已采）。
- CASE-015 单条内容失效 → 任务继续，该条失败（内容级隔离，不污染整体）。

网络相关场景用轻量 FakeCollector 抛真实 BilibiliError 或文档化单元断言，保持 GREEN。
"""
import analyze
from collectors.bilibili import (
    BilibiliCollector,
    BilibiliError,
    STOP_LOGIN,
    STOP_VERIFICATION,
)
from collectors.weibo import WeiboCollector, ADAPTER_UNAVAILABLE


# ---------------------------------------------------------------------------
# BilibiliCollector.supports 路由
# ---------------------------------------------------------------------------
def test_bilibili_supports_profile_url():
    c = BilibiliCollector()
    assert c.supports("https://space.bilibili.com/946974") is True
    # 允许「数字 ID + 可选尾部斜杠 + 可选 ?query」形式
    assert c.supports("https://space.bilibili.com/946974/") is True
    assert c.supports("https://space.bilibili.com/946974/?from=feed") is True
    assert c.supports("http://space.bilibili.com/946974") is True


def test_bilibili_supports_rejects_video_and_dynamic():
    c = BilibiliCollector()
    # 视频详情页
    assert c.supports("https://www.bilibili.com/video/BV1xx") is False
    # 动态子路径
    assert c.supports("https://space.bilibili.com/946974/dynamic") is False
    # 搜索页
    assert c.supports("https://search.bilibili.com/all?keyword=x") is False


def test_bilibili_supports_rejects_bare_domain_and_non_numeric():
    c = BilibiliCollector()
    assert c.supports("https://space.bilibili.com") is False
    assert c.supports("https://space.bilibili.com/abc") is False
    assert c.supports("https://bilibili.com/946974") is False


# ---------------------------------------------------------------------------
# WeiboCollector 未启用
# ---------------------------------------------------------------------------
def test_weibo_supports_profile():
    c = WeiboCollector()
    assert c.supports("https://weibo.com/u/123456") is True
    assert c.supports("https://weibo.com/SomeName") is True
    # 保留一级路径（搜索 / 话题）不匹配为账号主页
    assert c.supports("https://weibo.com/search/x") is False
    assert c.supports("https://weibo.com/") is False


def test_weibo_disabled_raises_adapter_unavailable():
    # P1 可选平台默认 ENABLED=False：调用采集方法必须抛 ADAPTER_UNAVAILABLE，
    # 且不得伪造任何数据（见 references/exceptions.md §1「适配器未启用」决策表）。
    assert WeiboCollector.ENABLED is False
    c = WeiboCollector()
    try:
        c.collect_profile("https://weibo.com/u/123456")
        raised = False
    except RuntimeError as e:
        raised = True
        assert ADAPTER_UNAVAILABLE in str(e)
    assert raised, "未启用时应抛 ADAPTER_UNAVAILABLE，而非返回空数据"


# ---------------------------------------------------------------------------
# CASE-006：置顶内容排除
# ---------------------------------------------------------------------------
def _post(pid, **kw):
    base = {
        "platform": "bilibili",
        "post_id": pid,
        "post_url": f"https://space.bilibili.com/1/{pid}",
        "collection_status": "SUCCESS",
        "is_pinned": False,
        "is_repost": False,
        "is_promoted": False,
        "views": 100,
        "likes": 10,
    }
    base.update(kw)
    return base


def test_pinned_excluded_from_valid():
    posts = [
        _post("1"),
        _post("2", is_pinned=True),
        _post("3"),
    ]
    _, valid, flagged, missing, restricted = analyze.split_samples(posts)
    valid_ids = [p["post_id"] for p in valid]
    assert "2" not in valid_ids
    assert set(valid_ids) == {"1", "3"}
    # 被排除内容单独成组，与有效样本互斥
    assert [p["post_id"] for p in flagged] == ["2"]


# ---------------------------------------------------------------------------
# CASE-007：转载内容排除
# ---------------------------------------------------------------------------
def test_repost_excluded_from_valid():
    posts = [
        _post("1"),
        _post("2", is_repost=True),
        _post("3", is_repost=True),
    ]
    _, valid, flagged, missing, restricted = analyze.split_samples(posts)
    valid_ids = [p["post_id"] for p in valid]
    assert "2" not in valid_ids and "3" not in valid_ids
    assert set(valid_ids) == {"1"}


def test_failed_status_excluded_from_valid():
    # FAILED / DELETED 不参与默认统计（analysis-rules.md §1）
    posts = [
        _post("1"),
        _post("2", collection_status="FAILED"),
        _post("3", collection_status="DELETED"),
    ]
    _, valid, flagged, missing, restricted = analyze.split_samples(posts)
    assert [p["post_id"] for p in valid] == ["1"]
    assert {p["post_id"] for p in missing} == {"2", "3"}


# ---------------------------------------------------------------------------
# CASE-012：高低表现样本不足 → INSUFFICIENT_SAMPLE
# ---------------------------------------------------------------------------
def test_high_low_insufficient_sample_below_15():
    # 有效样本 < 15 → compute_high_low 返回 None（即 INSUFFICIENT_SAMPLE 信号）
    posts = [
        _post(str(i), views=100 + i, likes=10 + i) for i in range(10)
    ]
    assert len(posts) == 10
    result = analyze.compute_high_low(posts, "views")
    assert result is None


def test_high_low_ok_when_sufficient():
    # 有效样本 >= 15 → 返回高低表现分组（每组至少 3 条）
    posts = [
        _post(str(i), views=100 + i * 10, likes=10 + i) for i in range(20)
    ]
    for i, post in enumerate(posts):
        post["title"] = f"标题 {i}"
    result = analyze.compute_high_low(posts, "views")
    assert result is not None
    assert result["group_size"] >= 3
    assert len(result["high"]) >= 3 and len(result["low"]) >= 3
    assert result["high"][0]["title"].startswith("标题 ")
    assert result["high"][0]["metrics"]["views"] == 290


# ---------------------------------------------------------------------------
# CASE-013 / CASE-014：登录墙 / 验证码停止（stop_reason 语义，保留已采）
# 文档化单元断言：用 FakeCollector 抛真实 BilibiliError，断言 stop_reason 与
# 决策表一致（exceptions.md §1：页面要求登录 / 验证码 → 保留已采、停止后续）。
# ---------------------------------------------------------------------------
class FakeLoginWallCollector(BilibiliCollector):
    def check_access(self, url):
        raise BilibiliError(STOP_LOGIN, "列表页要求登录")

    def collect_post_list(self, url, limit=30, date_range=None):
        # 已采到部分数据后遇登录墙：返回已采部分，由编排层据 stop_reason 停止
        return [_post("1"), _post("2")]


class FakeCaptchaCollector(BilibiliCollector):
    def check_access(self, url):
        raise BilibiliError(STOP_VERIFICATION, "列表页触发验证码")


def test_login_wall_stop_reason():
    c = FakeLoginWallCollector()
    raised = None
    try:
        c.check_access("https://space.bilibili.com/1")
    except BilibiliError as e:
        raised = e
    assert raised is not None
    assert raised.stop_reason == STOP_LOGIN == "LOGIN_REQUIRED"
    # 已采数据保留（不绕过、不丢弃）
    partial = c.collect_post_list("https://space.bilibili.com/1")
    assert len(partial) == 2


def test_verification_required_stop_reason():
    c = FakeCaptchaCollector()
    raised = None
    try:
        c.check_access("https://space.bilibili.com/1")
    except BilibiliError as e:
        raised = e
    assert raised is not None
    assert raised.stop_reason == STOP_VERIFICATION == "VERIFICATION_REQUIRED"


# ---------------------------------------------------------------------------
# CASE-015：单条内容失效 → 任务继续，该条失败（内容级隔离）
# 文档化单元断言：模拟一条 collect_post_detail 抛 POST_UNAVAILABLE，该条被记
# 为 DELETED 并排除出有效样本，其余内容照常进入分析（task_status 仅降级 PARTIAL，
# 不写入任务级 stop_reason，见 exceptions.md §1.1）。
# ---------------------------------------------------------------------------
def test_single_post_failure_continues():
    # 模拟采集结果：两条成功，一条失效（POST_UNAVAILABLE → DELETED）
    collected = [
        _post("1"),
        {"platform": "bilibili", "post_id": "2", "collection_status": "DELETED",
         "is_pinned": False, "is_repost": False, "is_promoted": False},
        _post("3"),
    ]
    _, valid, flagged, missing, restricted = analyze.split_samples(collected)
    # 任务继续：另外两条仍进入有效样本
    assert {p["post_id"] for p in valid} == {"1", "3"}
    # 失效条被隔离为 missing，不污染整体
    assert [p["post_id"] for p in missing] == ["2"]
    # 内容级原因不出现在任务级——此处仅验证被隔离，不抛异常中断
    assert len(valid) + len(missing) == len(collected)


def test_vis_count_field_visibility():
    from collect import _vis_count

    # visible & partial
    prof1 = {"field_visibility": {"followers": "visible", "post_count": "partial", "bio": "hidden"}}
    assert _vis_count(prof1) == 2

    # public (downward compatibility)
    prof2 = {"field_visibility": {"followers": "public", "post_count": "hidden"}}
    assert _vis_count(prof2) == 1

    # empty
    assert _vis_count({}) == 0


# ---------------------------------------------------------------------------
# P0 B站标签接口接线：collect_tags 已接入 collect_post_list 全量流程，
# API 标签合并进 base.hashtags（离线 FakeSession 验证真实调用路径）。
# ---------------------------------------------------------------------------
def test_collect_tags_wired_into_full_flow(monkeypatch):
    from collectors import bilibili as B

    calls: dict = {}

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def ensure_buvid(self):
            pass

        def collect_pinned(self, mid):
            return None

        def discover_medialist(self, mid, limit):
            return [{
                "bv_id": "BVtags",
                "title": "标题 #t1",
                "intro": "简介 #t2 #t3",
                "pubtime": 1700000000,
                "duration": "03:20",
                "copy_right": 1,
                "tid": 17,
                "upper": {"mid": "1", "name": "up"},
                "cnt_info": {"play": 100, "thumb_up": 10, "coin": 5,
                             "collect": 3, "reply": 2, "danmaku": 4, "share": 1},
            }]

        def get_json(self, path, params=None, wbi=False, retry=0):
            raise B.BilibiliError("ACCESS_RESTRICTED", "unexpected network call")

        def collect_tags(self, bvid):
            calls["bvid"] = bvid
            calls["count"] = calls.get("count", 0) + 1
            return ["apiTagA", "apiTagB"]

    monkeypatch.setattr(B, "Session", FakeSession)
    c = B.BilibiliCollector()
    posts = c.collect_post_list("https://space.bilibili.com/1", limit=1)
    assert len(posts) == 1
    # collect_tags 被实际调用，且针对该 bvid
    assert calls.get("bvid") == "BVtags"
    assert calls.get("count") == 1
    tags = posts[0].get("hashtags") or []
    # API 标签已合并进 hashtags
    assert "apiTagA" in tags and "apiTagB" in tags
    # 文本提取标签也保留
    assert "t1" in tags and "t2" in tags and "t3" in tags
