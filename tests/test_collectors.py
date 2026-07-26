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
import json
import os
import subprocess
import sys

import analyze
import pytest
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
    assert c.supports(
        "https://space.bilibili.com/946974?token=QUERY#FRAGMENT"
    ) is True
    assert c.supports("http://space.bilibili.com/946974") is True


def test_bilibili_supports_rejects_profile_credentials_and_ports():
    c = BilibiliCollector()

    assert c.supports("https://user:pass@space.bilibili.com/946974") is False
    assert c.supports("https://space.bilibili.com:443/946974") is False


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


def test_bilibili_comments_return_empty_only_for_explicit_valid_empty(
    monkeypatch
):
    collector = BilibiliCollector()
    session = collector._new_session()
    session.cookies = {"buvid3": "stable-public-id"}
    responses = iter([
        {"code": 0, "data": {"aid": 123}},
        {"code": 0, "data": {"replies": []}},
    ])
    monkeypatch.setattr(session, "get_json", lambda *args, **kwargs: next(responses))

    assert collector.collect_comments("https://www.bilibili.com/video/BV1abc") == []


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            json.dumps({"code": -101, "message": "secret restricted body"}),
            "ACCESS_RESTRICTED",
        ),
        (
            json.dumps({"code": 0, "data": {"cursor": "missing replies"}}),
            "COMMENTS_UNAVAILABLE",
        ),
        ("not-json secret response", "COMMENTS_UNAVAILABLE"),
        ("<html>WAF access denied: request was banned</html>", "ACCESS_RESTRICTED"),
    ],
)
def test_bilibili_comments_preserve_protection_or_sanitize_other_failures(
    monkeypatch, body, reason
):
    collector = BilibiliCollector()
    session = collector._new_session()
    session.cookies = {"buvid3": "stable-public-id"}
    responses = iter([
        json.dumps({"code": 0, "data": {"aid": 123}}),
        body,
    ])
    monkeypatch.setattr(
        session,
        "_curl",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_comments("https://www.bilibili.com/video/BV1abc")

    assert exc_info.value.stop_reason == reason
    assert "secret" not in str(exc_info.value)


def test_bilibili_comments_sanitize_aid_resolution_failure(monkeypatch):
    collector = BilibiliCollector()
    session = collector._new_session()
    session.cookies = {"buvid3": "stable-public-id"}
    monkeypatch.setattr(
        session,
        "get_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("secret aid failure")
        ),
    )

    with pytest.raises(BilibiliError) as exc_info:
        collector.collect_comments("https://www.bilibili.com/video/BV1abc")

    assert exc_info.value.stop_reason == "COMMENTS_UNAVAILABLE"
    assert "secret" not in str(exc_info.value)


def test_direct_bilibili_detail_canonicalizes_item_evidence(monkeypatch):
    class DetailSession:
        def ensure_buvid(self):
            return None

        def get_json(self, path, params):
            assert path == "/x/web-interface/view"
            assert params == {"bvid": "BV1abc"}
            return {
                "code": 0,
                "data": {
                    "bvid": "BV1abc",
                    "title": "safe title",
                    "owner": {},
                    "stat": {},
                },
            }

    collector = BilibiliCollector()
    monkeypatch.setattr(collector, "_new_session", lambda: DetailSession())

    post = collector.collect_post_detail(
        "https://bilibili.com/video/BV1abc?token=DETAIL_SECRET#DETAIL_FRAGMENT"
    )

    assert post["post_url"] == "https://www.bilibili.com/video/BV1abc"
    assert post["source_url"] == "https://www.bilibili.com/video/BV1abc"


@pytest.mark.parametrize("method_name", ["collect_post_detail", "collect_comments"])
def test_direct_bilibili_item_methods_reject_untrusted_hosts(
    monkeypatch, method_name
):
    collector = BilibiliCollector()
    monkeypatch.setattr(
        collector,
        "_new_session",
        lambda: pytest.fail("invalid item URL must not create a session"),
    )
    with pytest.raises(BilibiliError):
        getattr(collector, method_name)(
            "https://evil.example/path/BV1abc?token=EVIL_HOST_SECRET"
        )


# ---------------------------------------------------------------------------
# WeiboCollector 未启用
# ---------------------------------------------------------------------------
def test_weibo_supports_profile():
    c = WeiboCollector()
    assert c.supports("https://weibo.com/u/123456") is True
    assert c.supports("https://weibo.com/SomeName") is True
    assert c.supports(
        "https://www.weibo.com/u/123456?token=QUERY#FRAGMENT"
    ) is True
    assert c.supports("https://user:pass@weibo.com/u/123456") is False
    assert c.supports("https://weibo.com:443/u/123456") is False
    assert c.supports("https://weibo.com/home") is False
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


def test_base_collector_collection_coverage_defaults_to_empty():
    assert FakeLoginWallCollector().get_collection_coverage() == {}


@pytest.mark.parametrize("limit", [0, -1, 101, 1.5, True])
def test_bilibili_collector_rejects_invalid_limit_before_session(monkeypatch, limit):
    from collectors.bilibili import BilibiliCollector

    collector = BilibiliCollector()
    monkeypatch.setattr(
        collector,
        "_new_session",
        lambda: pytest.fail("network session must not be created"),
    )

    with pytest.raises(ValueError):
        collector.collect_post_list("https://space.bilibili.com/123", limit=limit)


@pytest.mark.parametrize("limit", [0, -1, 101, 1.5, True])
def test_weibo_collector_rejects_invalid_limit_before_resolution(
    monkeypatch, limit
):
    import collectors.weibo as weibo

    monkeypatch.setattr(weibo, "ENABLED", True)
    monkeypatch.setattr(
        weibo,
        "_resolve_uid",
        lambda url: pytest.fail("account resolution must not run"),
    )

    with pytest.raises(ValueError):
        weibo.WeiboCollector().collect_post_list(
            "https://weibo.com/u/123456", limit=limit
        )


def test_normalize_post_preserves_unknown_public_booleans():
    normalized = FakeLoginWallCollector().normalize_post({"post_id": "1"})

    assert normalized["is_pinned"] is None
    assert normalized["is_repost"] is None
    assert normalized["is_promoted"] is None


def test_normalize_post_preserves_field_visibility_evidence():
    visibility = {
        "title": "partial",
        "views": "visible",
        "custom_platform_field": "hidden",
    }

    normalized = FakeLoginWallCollector().normalize_post(
        {"post_id": "1", "field_visibility": visibility}
    )

    assert normalized["field_visibility"] == visibility


@pytest.mark.parametrize(
    ("raw_status", "expected_source"),
    [(None, "inferred_missing"), ("NOT_A_STATUS", "inferred_invalid")],
)
def test_normalize_post_does_not_invent_success_for_untrusted_status(
    raw_status, expected_source
):
    raw = {"post_id": "1"}
    if raw_status is not None:
        raw["collection_status"] = raw_status

    normalized = FakeLoginWallCollector().normalize_post(raw)

    assert normalized["collection_status"] == "PARTIAL"
    assert normalized["collection_status_source"] == expected_source


def test_normalize_post_marks_explicit_status_as_declared():
    normalized = FakeLoginWallCollector().normalize_post(
        {"post_id": "1", "collection_status": "ok"}
    )

    assert normalized["collection_status"] == "SUCCESS"
    assert normalized["collection_status_source"] == "declared"


def test_all_comments_persist_returns_parents_and_honest_outcomes(
    monkeypatch, tmp_path
):
    import collect

    class CommentAdapter:
        platform = "douyin"

        def __init__(self):
            self.calls = []

        def supports(self, url):
            return True

        def check_access(self, url):
            return {"accessible": True}

        def collect_profile(self, url):
            return {"platform": "douyin", "field_visibility": {}}

        def collect_all_post_list(self, url, **kwargs):
            return [
                {
                    "platform": "douyin",
                    "post_id": str(7000 + number),
                    "post_url": f"https://www.douyin.com/video/{7000 + number}",
                    "collection_status": "SUCCESS",
                }
                for number in range(1, 33)
            ]

        def get_collection_coverage(self):
            return {
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_post_count": 32,
                "stop_condition": "terminal_page",
            }

        def collect_comments(self, post_url, limit=20):
            self.calls.append((post_url, limit))
            post_id = post_url.rsplit("/", 1)[-1]
            if post_id == "7002":
                return []
            if post_id == "7003":
                raise RuntimeError("upstream response must not persist")
            count = 2 if post_id == "7001" else 1
            return [
                {"comment_id": f"{post_id}-{number}", "text": f"评论 {number}"}
                for number in range(count)
            ][:limit]

    adapter = CommentAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        collect_all=True,
        include_comments=True,
    ) == 0

    assert len(adapter.calls) == 32
    assert all(limit == 20 for _, limit in adapter.calls)
    comments = [
        json.loads(line)
        for line in (out / "source" / "comments.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(comments) == 31
    assert comments[0]["comment_id"] == "7001-0"
    assert comments[0]["text"] == "评论 0"
    assert comments[0]["parent_post_id"] == "7001"
    assert comments[0]["parent_post_url"] == "https://www.douyin.com/video/7001"
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["comment_collection"] == {
        "attempted_posts": 32,
        "comments_collected": 31,
        "empty_results": 1,
        "failures": 1,
        "per_post_limit": 20,
    }
    assert task["task_status"] == "COMPLETED"
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "comments_collected: 31" in report
    assert "empty_results: 1" in report
    assert "failures: 1" in report
    assert "upstream response must not persist" not in report


def test_comment_artifact_normalizes_allowlist_dedupes_and_rejects_malformed(
    monkeypatch, tmp_path
):
    import collect

    class BoundaryAdapter:
        platform = "douyin"

        def supports(self, url):
            return True

        def check_access(self, url):
            return {"accessible": True}

        def collect_profile(self, url):
            return {"platform": "douyin", "field_visibility": {}}

        def collect_post_list(self, url, limit=30, date_range=None):
            return [
                {
                    "platform": "douyin",
                    "post_id": post_id,
                    "post_url": f"https://www.douyin.com/video/{post_id}",
                    "collection_status": "SUCCESS",
                }
                for post_id in ("7001", "7002")
            ]

        def collect_comments(self, post_url, limit=20):
            post_id = post_url.rsplit("/", 1)[-1]
            if post_id == "7002":
                return [{"text": "missing comment id", "raw_token": "secret-two"}]
            return [
                {
                    "comment_id": 123,
                    "post_id": "7001",
                    "post_url": post_url,
                    "author": " Alice ",
                    "text": " first ",
                    "likes": 4,
                    "published_at": "2026-07-20T10:00:00+08:00",
                    "collected_at": "2026-07-24T10:00:00+08:00",
                    "raw_token": "secret-one",
                    "headers": {"Cookie": "must-not-persist"},
                },
                {"comment_id": "123", "text": "duplicate must lose"},
                {
                    "comment_id": "124",
                    "parent_post_id": "9999",
                    "text": "mismatched parent",
                },
                {
                    "comment_id": {"token": "secret-id"},
                    "text": "invalid identifier type",
                },
                {
                    "comment_id": "125",
                    "text": "invalid timestamp",
                    "published_at": "secret raw timestamp",
                },
                "raw response fragment",
            ]

    monkeypatch.setattr(collect, "_load_adapters", lambda: [BoundaryAdapter()])
    out = tmp_path / "task"

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
    ) == 0

    rows = [
        json.loads(line)
        for line in (out / "source" / "comments.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows == [{
        "comment_id": "123",
        "parent_post_id": "7001",
        "parent_post_url": "https://www.douyin.com/video/7001",
        "author": "Alice",
        "text": "first",
        "likes": 4,
        "published_at": "2026-07-20T10:00:00+08:00",
        "collected_at": "2026-07-24T10:00:00+08:00",
    }]
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["comment_collection"] == {
        "attempted_posts": 2,
        "comments_collected": 1,
        "empty_results": 0,
        "failures": 2,
        "per_post_limit": 20,
    }
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "secret-one" not in report
    assert "secret-two" not in report
    assert "secret-id" not in (out / "source" / "comments.jsonl").read_text()
    assert "secret raw timestamp" not in (out / "source" / "comments.jsonl").read_text()
    assert "must-not-persist" not in (out / "source" / "comments.jsonl").read_text()


class _SafeCommentAdapter:
    platform = "douyin"

    def supports(self, url):
        return True

    def check_access(self, url):
        return {"accessible": True}

    def collect_profile(self, url):
        return {"platform": "douyin", "field_visibility": {}}

    def collect_post_list(self, url, limit=30, date_range=None):
        return [{
            "platform": "douyin",
            "post_id": "7001",
            "post_url": "https://www.douyin.com/video/7001",
            "collection_status": "SUCCESS",
        }]

    def collect_comments(self, post_url, limit=20):
        return [{"comment_id": "c1", "text": "safe comment"}]


@pytest.mark.parametrize(
    ("platform", "post", "expected"),
    [
        (
            "douyin",
            {
                "platform": "douyin",
                "post_id": "7001",
                "post_url": (
                    "https://iesdouyin.com/video/7001?token=QUERY_SECRET"
                    "#FRAGMENT_SECRET"
                ),
                "collection_status": "SUCCESS",
            },
            ("7001", "https://www.douyin.com/video/7001"),
        ),
        (
            "bilibili",
            {
                "platform": "bilibili",
                "post_id": "BV1abc",
                "post_url": (
                    "https://bilibili.com/video/BV1abc?token=QUERY_SECRET"
                    "#FRAGMENT_SECRET"
                ),
                "collection_status": "SUCCESS",
            },
            ("BV1abc", "https://www.bilibili.com/video/BV1abc"),
        ),
        (
            "weibo",
            {
                "platform": "weibo",
                "post_id": "a1",
                "post_url": (
                    "https://www.weibo.com/123456/a1?token=QUERY_SECRET"
                    "#FRAGMENT_SECRET"
                ),
                "collection_status": "SUCCESS",
            },
            ("a1", "https://weibo.com/123456/a1"),
        ),
    ],
)
def test_comment_parent_urls_are_platform_canonical(platform, post, expected):
    import collect

    assert collect._valid_comment_parent(platform, post) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"collection_status": "FAILED"},
        {"collection_status": "DELETED"},
        {"collection_status": "RESTRICTED"},
        {"is_pinned": True},
        {"is_repost": True},
        {"is_promoted": True},
    ],
    ids=("failed", "deleted", "restricted", "pinned", "repost", "promoted"),
)
def test_comment_parent_rejects_six_analysis_ineligible_classes(overrides):
    import collect

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "collection_status": "SUCCESS",
    }
    post.update(overrides)

    assert collect._valid_comment_parent("douyin", post) is None


def test_comment_collection_attempts_only_distinct_valid_unflagged_parents(
    monkeypatch, tmp_path
):
    import collect

    class EligibilityAdapter(_SafeCommentAdapter):
        def __init__(self):
            self.calls = []

        def collect_post_list(self, url, limit=30, date_range=None):
            posts = [
                {
                    "platform": "douyin",
                    "post_id": "7001",
                    "post_url": "https://www.douyin.com/video/7001",
                    "collection_status": "SUCCESS",
                },
                {
                    "platform": "douyin",
                    "post_id": "7002",
                    "post_url": "https://www.douyin.com/video/7002",
                    "collection_status": "PARTIAL",
                },
                {
                    "platform": "douyin",
                    "post_id": "7001",
                    "post_url": "https://www.douyin.com/video/7001",
                    "collection_status": "SUCCESS",
                },
            ]
            excluded = (
                {"collection_status": "FAILED"},
                {"collection_status": "DELETED"},
                {"collection_status": "RESTRICTED"},
                {"is_pinned": True},
                {"is_repost": True},
                {"is_promoted": True},
            )
            for offset, overrides in enumerate(excluded, start=3):
                post = {
                    "platform": "douyin",
                    "post_id": str(7000 + offset),
                    "post_url": f"https://www.douyin.com/video/{7000 + offset}",
                    "collection_status": "SUCCESS",
                }
                post.update(overrides)
                posts.append(post)
            return posts

        def collect_comments(self, post_url, limit=20):
            self.calls.append(post_url)
            post_id = post_url.rsplit("/", 1)[-1]
            return [{"comment_id": f"c-{post_id}", "text": "公开评论"}]

    adapter = EligibilityAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
    ) == 0

    assert adapter.calls == [
        "https://www.douyin.com/video/7001",
        "https://www.douyin.com/video/7002",
    ]
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["comment_collection"] == {
        "attempted_posts": 2,
        "comments_collected": 2,
        "empty_results": 0,
        "failures": 0,
        "per_post_limit": 20,
    }


def test_douyin_item_url_is_canonical_before_calls_and_persistence(
    monkeypatch, tmp_path, capsys
):
    import collect

    secret_url = (
        "https://iesdouyin.com/video/7001?token=QUERY_SECRET"
        "#FRAGMENT_SECRET"
    )
    canonical_url = "https://www.douyin.com/video/7001"

    class CanonicalUrlAdapter(_SafeCommentAdapter):
        def __init__(self):
            self.detail_calls = []
            self.comment_calls = []

        def collect_post_list(self, url, limit=30, date_range=None):
            return [{
                "platform": "douyin",
                "post_id": "7001",
                "post_url": secret_url,
                "source_url": secret_url,
                "collection_status": "SUCCESS",
            }]

        def collect_post_detail(self, post_url):
            self.detail_calls.append(post_url)
            return {"post_id": "7001", "duration_seconds": 15}

        def collect_comments(self, post_url, limit=20):
            self.comment_calls.append(post_url)
            return [{
                "comment_id": "c1",
                "post_url": post_url,
                "text": "safe comment",
            }]

    adapter = CanonicalUrlAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
        enrich_details=True,
    ) == 0

    assert adapter.detail_calls == [canonical_url]
    assert adapter.comment_calls == [canonical_url]
    post = json.loads(
        (out / "source" / "posts.jsonl").read_text(encoding="utf-8")
    )
    comment = json.loads(
        (out / "source" / "comments.jsonl").read_text(encoding="utf-8")
    )
    assert post["post_url"] == canonical_url
    assert post["source_url"] == canonical_url
    assert comment["parent_post_url"] == canonical_url
    captured = capsys.readouterr()
    all_output = captured.out + captured.err
    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            all_output += artifact.read_text(encoding="utf-8")
    assert "QUERY_SECRET" not in all_output
    assert "FRAGMENT_SECRET" not in all_output


def test_account_and_all_artifact_urls_are_canonical_or_null(
    monkeypatch, tmp_path, capsys
):
    import collect

    supplied_url = (
        "https://iesdouyin.com/user/public_account/?token=ACCOUNT_SECRET"
        "#ACCOUNT_FRAGMENT_SECRET"
    )
    canonical_profile_url = "https://www.douyin.com/user/public_account"

    class AccountUrlBoundaryAdapter(_SafeCommentAdapter):
        def __init__(self):
            self.calls = []
            self.support_calls = []

        def supports(self, url):
            self.support_calls.append(url)
            return True

        def check_access(self, url):
            self.calls.append(("access", url))
            return {"accessible": True}

        def collect_post_list(self, url, limit=30, date_range=None):
            self.calls.append(("list", url))
            return [
                {
                    "platform": "douyin",
                    "post_id": "7001",
                    "post_url": (
                        "https://iesdouyin.com/video/7001?token=POST_SECRET"
                        "#POST_FRAGMENT_SECRET"
                    ),
                    "source_url": "https://evil.example/evidence?token=SOURCE_SECRET",
                    "collection_status": "SUCCESS",
                },
                {
                    "platform": "douyin",
                    "post_id": "7002",
                    "post_url": "https://evil.example/video/7002?token=INVALID_POST_SECRET",
                    "source_url": "not-a-url-SOURCE_TEXT_SECRET",
                    "collection_status": "SUCCESS",
                },
            ]

        def collect_profile(self, url):
            self.calls.append(("profile", url))
            return {
                "platform": "douyin",
                "profile_url": supplied_url,
                "field_visibility": {},
            }

    adapter = AccountUrlBoundaryAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(supplied_url, out_dir=str(out)) == 0

    assert adapter.support_calls == [
        "https://iesdouyin.com/user/public_account/"
    ]
    assert adapter.calls == [
        ("access", canonical_profile_url),
        ("list", canonical_profile_url),
        ("profile", canonical_profile_url),
    ]
    profile = json.loads(
        (out / "source" / "profile.json").read_text(encoding="utf-8")
    )
    posts = [
        json.loads(line)
        for line in (out / "source" / "posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert profile["profile_url"] == canonical_profile_url
    assert task["profile_url"] == canonical_profile_url
    assert posts[0]["post_url"] == "https://www.douyin.com/video/7001"
    assert posts[0]["source_url"] is None
    assert posts[1]["post_url"] is None
    assert posts[1]["source_url"] is None

    captured = capsys.readouterr()
    all_output = captured.out + captured.err
    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            all_output += artifact.read_text(encoding="utf-8")
    for secret in (
        "ACCOUNT_SECRET",
        "ACCOUNT_FRAGMENT_SECRET",
        "POST_SECRET",
        "POST_FRAGMENT_SECRET",
        "SOURCE_SECRET",
        "INVALID_POST_SECRET",
        "SOURCE_TEXT_SECRET",
    ):
        assert secret not in all_output


@pytest.mark.parametrize(
    ("profile_url", "expected_support_calls"),
    [
        ("https://user:password@www.douyin.com/user/public_account", []),
        ("https://www.douyin.com:443/user/public_account", []),
        (
            "https://www.douyin.com/video/7001?token=INVALID_PATH_SECRET",
            ["https://www.douyin.com/video/7001"],
        ),
        ("https://www.douyin.com%3A/user/public_account", []),
        ("https://www.douyin.com/user%2Fpublic_account", []),
    ],
)
def test_invalid_supported_profile_url_is_rejected_before_adapter_calls(
    monkeypatch, tmp_path, profile_url, expected_support_calls
):
    import collect

    class OverbroadAdapter(_SafeCommentAdapter):
        def __init__(self):
            self.calls = []
            self.support_calls = []

        def supports(self, url):
            self.support_calls.append(url)
            return True

        def check_access(self, url):
            self.calls.append(url)
            return {"accessible": True}

        def collect_post_list(self, url, limit=30, date_range=None):
            self.calls.append(url)
            return []

        def collect_profile(self, url):
            self.calls.append(url)
            return {}

    adapter = OverbroadAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(profile_url, out_dir=str(tmp_path / "out")) == 2
    assert adapter.calls == []
    assert adapter.support_calls == expected_support_calls
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("platform", "value"),
    [
        ("douyin", "https://www.douyin.com/user/example;secret=1"),
        ("douyin", "https://www.douyin.com:/user/example"),
        ("bilibili", "https://space.bilibili.com/123;secret=1"),
        ("weibo", "https://weibo.com/u/123;secret=1"),
    ],
)
def test_profile_url_policy_rejects_params_and_nonexact_authority(platform, value):
    from collectors.url_policy import canonical_profile_url

    assert canonical_profile_url(platform, value) is None


@pytest.mark.parametrize(
    ("platform", "value"),
    [
        ("douyin", "https://www.douyin.com/video/7001;secret=1"),
        ("douyin", "https://www.douyin.com:/video/7001"),
        ("bilibili", "https://www.bilibili.com/video/BV1abc;secret=1"),
        ("weibo", "https://weibo.com/123/a1;secret=1"),
    ],
)
def test_item_url_policy_rejects_params_and_nonexact_authority(platform, value):
    from collectors.url_policy import canonical_item_url

    assert canonical_item_url(platform, value) is None


@pytest.mark.parametrize(
    ("failure_stage", "expected_code"),
    [
        ("access_reason", 3),
        ("access_exception", 3),
        ("post_list", 0),
        ("profile", 0),
    ],
)
def test_adapter_failure_text_is_sanitized_at_every_output_boundary(
    monkeypatch, tmp_path, capsys, failure_stage, expected_code
):
    import collect

    secret = f"SECRET_{failure_stage.upper()}_VALUE"
    profile_url = (
        "https://www.douyin.com/user/example?token=PROFILE_QUERY_SECRET"
        "#PROFILE_FRAGMENT_SECRET"
    )

    class SecretAdapterError(Exception):
        stop_reason = "PARSER_FAILED"
        diagnostic_code = "SAFE_DIAGNOSTIC"

        def __init__(self, message, partial_posts=None):
            super().__init__(message)
            self.partial_posts = partial_posts

    class SecretBoundaryAdapter(_SafeCommentAdapter):
        def check_access(self, url):
            if failure_stage == "access_reason":
                return {
                    "accessible": False,
                    "stop_reason": "ACCESS_RESTRICTED",
                    "reason": secret,
                }
            if failure_stage == "access_exception":
                raise SecretAdapterError(secret)
            return {"accessible": True}

        def collect_post_list(self, url, limit=30, date_range=None):
            post = {
                "platform": "douyin",
                "post_id": "7001",
                "post_url": "https://www.douyin.com/video/7001",
                "collection_status": "SUCCESS",
            }
            if failure_stage == "post_list":
                raise SecretAdapterError(secret, partial_posts=[post])
            return [post]

        def collect_profile(self, url):
            if failure_stage == "profile":
                raise SecretAdapterError(secret)
            return {"platform": "douyin", "field_visibility": {}}

    monkeypatch.setattr(collect, "_load_adapters", lambda: [SecretBoundaryAdapter()])
    out = tmp_path / "task"

    assert collect.run(profile_url, out_dir=str(out)) == expected_code

    captured = capsys.readouterr()
    all_output = captured.out + captured.err
    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            all_output += artifact.read_text(encoding="utf-8")
    assert secret not in all_output
    assert "PROFILE_QUERY_SECRET" not in all_output
    assert "PROFILE_FRAGMENT_SECRET" not in all_output
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    if failure_stage == "post_list":
        assert "diagnostic_code=SAFE_DIAGNOSTIC" in report


def test_adapter_load_exception_text_is_not_printed(monkeypatch, capsys):
    import builtins
    import collect

    original_import = builtins.__import__

    def fail_bilibili_import(name, *args, **kwargs):
        if name == "collectors.bilibili":
            raise RuntimeError("SECRET_ADAPTER_IMPORT_VALUE")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_bilibili_import)

    collect._load_adapters()

    captured = capsys.readouterr()
    assert "SECRET_ADAPTER_IMPORT_VALUE" not in captured.out + captured.err


def test_report_writer_sanitizes_untrusted_error_metadata(tmp_path):
    import collect

    collect._write_report(
        _SafeCommentAdapter(),
        "https://www.douyin.com/user/example?token=SECRET_REPORT_URL",
        {},
        [],
        str(tmp_path),
        task_status="FAILED",
        stop_reason="INTERNAL_ERROR",
        error_log=[{
            "stage": "SECRET_REPORT_STAGE",
            "error_code": "SECRET_REPORT_CODE",
            "url": "https://example.com/path?token=SECRET_ERROR_URL",
            "message": "SECRET_REPORT_MESSAGE",
            "occurred_at": "SECRET_REPORT_TIMESTAMP",
            "diagnostic_code": "SECRET diagnostic value",
        }],
    )

    report = (tmp_path / "collection-report.md").read_text(encoding="utf-8")
    assert "SECRET_" not in report
    assert "SECRET diagnostic value" not in report


@pytest.mark.parametrize("link_kind", ["workspace", "source"])
def test_comments_reject_workspace_or_source_symlink_before_writes(
    monkeypatch, tmp_path, link_kind
):
    import collect

    target = tmp_path / "target"
    target.mkdir()
    if link_kind == "workspace":
        out = tmp_path / "out"
        out.symlink_to(target, target_is_directory=True)
    else:
        out = tmp_path / "out"
        out.mkdir()
        (out / "source").symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [_SafeCommentAdapter()])

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
    ) == 2
    assert list(target.iterdir()) == []


def test_invalid_comment_parent_is_failure_without_adapter_attempt(
    monkeypatch, tmp_path
):
    import collect

    class InvalidParentAdapter(_SafeCommentAdapter):
        def __init__(self):
            self.comment_calls = 0

        def collect_post_list(self, url, limit=30, date_range=None):
            return [{
                "platform": "douyin",
                "post_id": "7001",
                "post_url": "https://www.douyin.com/user/example",
                "collection_status": "SUCCESS",
            }]

        def collect_comments(self, post_url, limit=20):
            self.comment_calls += 1
            return []

    adapter = InvalidParentAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
    ) == 0

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert adapter.comment_calls == 0
    assert task["comment_collection"]["attempted_posts"] == 0
    assert task["comment_collection"]["failures"] == 1


def test_weibo_comment_parent_requires_matching_public_post_url(
    monkeypatch, tmp_path
):
    import collect

    class InvalidWeiboParentAdapter(_SafeCommentAdapter):
        platform = "weibo"

        def __init__(self):
            self.comment_calls = 0

        def collect_profile(self, url):
            return {"platform": "weibo", "field_visibility": {}}

        def collect_post_list(self, url, limit=30, date_range=None):
            return [{
                "platform": "weibo",
                "post_id": "a1",
                "post_url": "https://evil.example/123456/a1",
                "collection_status": "SUCCESS",
            }]

        def collect_comments(self, post_url, limit=20):
            self.comment_calls += 1
            return []

    adapter = InvalidWeiboParentAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        "https://weibo.com/u/123456",
        out_dir=str(out),
        include_comments=True,
    ) == 0

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert adapter.comment_calls == 0
    assert task["comment_collection"]["attempted_posts"] == 0
    assert task["comment_collection"]["failures"] == 1


def test_resume_comments_leave_legacy_temp_symlink_read_only(
    monkeypatch, tmp_path
):
    import collect

    old = tmp_path / "old"
    source = old / "source"
    source.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("do-not-touch", encoding="utf-8")
    predictable = source / "comments.jsonl.tmp"
    predictable.symlink_to(victim)
    new = tmp_path / "new"
    monkeypatch.setattr(collect, "_load_adapters", lambda: [_SafeCommentAdapter()])

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(old),
        include_comments=True,
        resume=True,
        resume_out=str(new),
    ) == 0
    assert victim.read_text(encoding="utf-8") == "do-not-touch"
    assert predictable.is_symlink()
    assert (new / "source" / "comments.jsonl").is_file()
    assert (new / ".complete").is_file()


def test_comment_serialization_failure_leaves_sanitized_incomplete_workspace(
    monkeypatch, tmp_path, capsys
):
    import collect

    original_dumps = collect.json.dumps

    def fail_comment_only(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("comment_id") == "c1":
            raise TypeError("SECRET_COMMENT_SERIALIZATION")
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(collect, "_load_adapters", lambda: [_SafeCommentAdapter()])
    monkeypatch.setattr(collect.json, "dumps", fail_comment_only)
    out = tmp_path / "out"

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
    ) == 3
    captured = capsys.readouterr()
    assert out.is_dir()
    assert not (out / ".complete").exists()
    assert "SECRET_COMMENT_SERIALIZATION" not in captured.out + captured.err


def test_concurrent_comment_leaf_is_preserved_and_commit_fails(
    monkeypatch, tmp_path
):
    import collect

    out = tmp_path / "out"
    concurrent_bytes = b"concurrent comments\x00must-survive"

    class ConflictingCommentAdapter(_SafeCommentAdapter):
        def collect_comments(self, post_url, limit=20):
            (out / "source" / "comments.jsonl").write_bytes(concurrent_bytes)
            return super().collect_comments(post_url, limit=limit)

    monkeypatch.setattr(
        collect, "_load_adapters", lambda: [ConflictingCommentAdapter()]
    )

    assert collect.run(
        "https://www.douyin.com/user/example",
        out_dir=str(out),
        include_comments=True,
    ) == 2
    assert (out / "source" / "comments.jsonl").read_bytes() == concurrent_bytes
    assert not (out / ".complete").exists()


def test_normalize_post_preserves_explicit_public_booleans():
    collector = FakeLoginWallCollector()

    explicit_true = collector.normalize_post({
        "is_pinned": True,
        "is_repost": True,
        "is_promoted": True,
    })
    explicit_false = collector.normalize_post({
        "is_pinned": False,
        "is_repost": False,
        "is_promoted": False,
    })

    assert (
        explicit_true["is_pinned"],
        explicit_true["is_repost"],
        explicit_true["is_promoted"],
    ) == (True, True, True)
    assert (
        explicit_false["is_pinned"],
        explicit_false["is_repost"],
        explicit_false["is_promoted"],
    ) == (False, False, False)


def test_collection_coverage_preserves_coherent_range_no_match_disclosure():
    from collect import _sanitize_collection_coverage

    coverage = _sanitize_collection_coverage({
        "requested_all": True,
        "is_exhaustive": True,
        "terminal_page_observed": True,
        "observed_post_count": 3,
        "stop_condition": "terminal_page",
        "range_filter_applied": True,
        "range_match_count": 0,
        "range_no_match": True,
    })

    assert coverage["observed_post_count"] == 3
    assert coverage["range_filter_applied"] is True
    assert coverage["range_match_count"] == 0
    assert coverage["range_no_match"] is True


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
