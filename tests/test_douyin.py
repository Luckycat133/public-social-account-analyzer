"""Offline tests for the Douyin browser-response transport."""

import json

import pytest

from collectors._constants import STOP_LOGIN, STOP_VERIFICATION
from collectors.base import BaseCollector


STOP_ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
STOP_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
STOP_NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"


AWEME = {
    "aweme_id": "7001",
    "desc": "公开作品 #测试",
    "create_time": 1700000000,
    "statistics": {"digg_count": 12, "comment_count": 3},
    "video": {"duration": 9000},
}


ACCOUNT_URL = "https://www.douyin.com/user/example"
ACCOUNT_AWEME = {**AWEME, "author": {"sec_uid": "example"}}


def _raise_http_error(status):
    import urllib.error

    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            ACCOUNT_URL,
            status,
            "controlled response",
            None,
            None,
        )

    return fail


def test_401_maps_to_login(monkeypatch):
    from collectors.douyin import DouyinCollector, DouyinError

    monkeypatch.setattr(
        "collectors.douyin.urllib.request.urlopen", _raise_http_error(401)
    )

    with pytest.raises(DouyinError) as exc_info:
        DouyinCollector()._fetch(ACCOUNT_URL)

    assert exc_info.value.stop_reason == "LOGIN_REQUIRED"


def test_403_maps_to_access_restricted(monkeypatch):
    from collectors.douyin import DouyinCollector, DouyinError

    monkeypatch.setattr(
        "collectors.douyin.urllib.request.urlopen", _raise_http_error(403)
    )

    with pytest.raises(DouyinError) as exc_info:
        DouyinCollector()._fetch(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED


def test_404_maps_to_account_unavailable(monkeypatch):
    from collectors.douyin import DouyinCollector, DouyinError

    monkeypatch.setattr(
        "collectors.douyin.urllib.request.urlopen", _raise_http_error(404)
    )

    with pytest.raises(DouyinError) as exc_info:
        DouyinCollector()._fetch(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_ACCOUNT_UNAVAILABLE


def test_proxy_credential_not_in_error(monkeypatch):
    import urllib.error

    from collectors.douyin import DouyinCollector, DouyinError

    secret = "proxy-user:proxy-password"

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(f"proxy authentication failed for {secret}")

    monkeypatch.setattr("collectors.douyin.urllib.request.urlopen", fail)

    with pytest.raises(DouyinError) as exc_info:
        DouyinCollector()._fetch(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_ACCESS_RESTRICTED
    assert str(exc_info.value) == "网络层错误，未保留远端原因文本"
    assert secret not in str(exc_info.value)


def test_browser_error_type_check():
    from collectors.browser_backend import BrowserError
    from collectors.douyin import DouyinCollector, DouyinError

    unavailable = DouyinCollector(
        browser_collect=lambda **_request: (_ for _ in ()).throw(
            BrowserError(
                "message wording is irrelevant",
                diagnostic_code="BROWSER_UNAVAILABLE",
            )
        )
    )
    with pytest.raises(DouyinError) as unavailable_error:
        unavailable._request_browser_result(ACCOUNT_URL, 30, None)

    misleading_generic = DouyinCollector(
        browser_collect=lambda **_request: (_ for _ in ()).throw(
            RuntimeError("未找到可用的浏览器")
        )
    )
    with pytest.raises(DouyinError) as transport_error:
        misleading_generic._request_browser_result(ACCOUNT_URL, 30, None)

    assert unavailable_error.value.diagnostic_code == "BROWSER_UNAVAILABLE"
    assert transport_error.value.diagnostic_code == "BROWSER_TRANSPORT_FAILED"


def test_partial_gate_no_browser_required():
    from collectors.douyin import DouyinCollector

    post = DouyinCollector._build_post_raw(
        ACCOUNT_URL,
        {
            "aweme_id": "7001",
            "desc": "只有列表文案",
            "share_url": "https://www.douyin.com/video/7001",
        },
        source="list",
    )

    assert post["collection_status"] == "PARTIAL"


def test_douyin_supports_canonicalizable_profile_and_rejects_authority_data():
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(browser_fallback=False)

    assert collector.supports(
        "https://iesdouyin.com/user/example?token=QUERY#FRAGMENT"
    ) is True
    assert collector.supports(
        "https://user:pass@www.douyin.com/user/example"
    ) is False
    assert collector.supports("https://www.douyin.com:443/user/example") is False


def test_short_profile_url_resolves_once_from_sanitized_candidate(
    monkeypatch, tmp_path, capsys
):
    import collect
    from collectors.douyin import DouyinCollector

    safe_short_url = "https://v.douyin.com/AbC123/"
    canonical_profile_url = "https://www.douyin.com/user/resolved_account"

    class ShortLinkAdapter(DouyinCollector):
        def __init__(self):
            super().__init__(browser_fallback=False)
            self.resolution_calls = []
            self.account_calls = []

        def _resolve_final_url(self, url):
            self.resolution_calls.append(url)
            return (
                canonical_profile_url
                + "?token=REDIRECT_SECRET#REDIRECT_FRAGMENT_SECRET"
            )

        def check_access(self, url):
            self.account_calls.append(("access", url))
            return {"accessible": True}

        def collect_post_list(self, url, limit=30, date_range=None):
            self.account_calls.append(("list", url))
            return [{
                "platform": "douyin",
                "post_id": "7001",
                "post_url": "https://www.douyin.com/video/7001",
                "source_url": "https://www.douyin.com/video/7001",
                "collection_status": "SUCCESS",
            }]

        def collect_profile(self, url):
            self.account_calls.append(("profile", url))
            return {"platform": "douyin", "field_visibility": {}}

    adapter = ShortLinkAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        "https://v.douyin.com/AbC123/?token=SHORT_SECRET#SHORT_FRAGMENT_SECRET",
        out_dir=str(out),
    ) == 0

    assert adapter.resolution_calls == [safe_short_url]
    assert adapter.account_calls == [
        ("access", canonical_profile_url),
        ("list", canonical_profile_url),
        ("profile", canonical_profile_url),
    ]
    captured = capsys.readouterr()
    all_output = captured.out + captured.err
    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            all_output += artifact.read_text(encoding="utf-8")
    assert "SHORT_SECRET" not in all_output
    assert "SHORT_FRAGMENT_SECRET" not in all_output
    assert "REDIRECT_SECRET" not in all_output
    assert "REDIRECT_FRAGMENT_SECRET" not in all_output


def test_docs_describe_zero_python_dependency_browser_fallback():
    """Public documentation states the implemented browser-fallback policy."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    usage = (root / "USAGE.md").read_text(encoding="utf-8")
    platform = (root / "skill/references/platform-douyin.md").read_text(
        encoding="utf-8"
    )
    skill = (root / "skill/SKILL.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    module_text = (
        root / "skill/scripts/collectors/douyin.py"
    ).read_text(encoding="utf-8")
    docs = "\n".join((readme, usage, platform, skill, changelog))

    assert "实验性支持" in readme
    assert "--no-browser-fallback" in usage
    assert "SOCIAL_BROWSER_FALLBACK" in usage
    assert "不新增 pip" in platform
    assert "临时用户目录" in platform
    assert "实验性支持" in skill
    assert "SSR 缺失或作品列表结构无法识别" in skill
    assert "默认自动降级" in skill
    assert "--no-browser-fallback" in skill
    assert "BROWSER_UNAVAILABLE" in skill
    assert "SSR 作品列表缺失" not in docs
    assert "若 `RENDER_DATA` 存在但无法识别作品列表，仍返回 `PARSER_FAILED`" not in docs
    assert "仅在主页没有可解析的 `RENDER_DATA`" not in docs
    assert "B站遇到登录、验证、限流或访问限制时始终立即停止" in usage
    assert "同时禁止 B站和抖音" not in usage
    assert "Headless Chrome" not in skill
    assert "urllib-only" not in module_text
    assert "不模拟浏览器" not in module_text


def _ssr_html(data):
    return '<script id="RENDER_DATA">' + json.dumps(data) + "</script>"


def test_ssr_list_skips_invalid_ids_merges_duplicate_gaps_and_uses_item_urls():
    """Only numeric platform IDs may become posts; duplicate evidence fills gaps."""
    from collectors.douyin import DouyinCollector

    first = {
        "aweme_id": "7001",
        "author": {"sec_uid": "example"},
        "desc": "列表页可靠标题 #列表话题",
        "create_time": None,
        "video": {},
    }
    duplicate = {
        "aweme_id": "7001",
        "author": {"sec_uid": "example"},
        "desc": "后出现的冲突标题",
        "create_time": 1_700_000_000,
        "video": {"duration": 9_000},
    }
    invalid = {
        "author": {"sec_uid": "example"},
        "desc": "没有 ID，不能以主页充当作品证据",
    }
    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html(
        {"user": {"post": {"data": [first, duplicate, invalid]}}}
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=30)

    assert len(posts) == 1
    assert posts[0]["post_id"] == "7001"
    assert posts[0]["post_url"] == "https://www.douyin.com/video/7001"
    assert posts[0]["post_url"] != ACCOUNT_URL
    assert posts[0]["title"] == "列表页可靠标题 #列表话题"
    assert posts[0]["published_at"] is not None
    assert posts[0]["duration_seconds"] == 9


def test_detail_enrichment_is_bounded_preserves_list_evidence_and_records_outcomes(
    monkeypatch, tmp_path
):
    import collect

    class DetailAdapter:
        platform = "douyin"

        def __init__(self):
            self.detail_calls = []

        def supports(self, url):
            return True

        def check_access(self, url):
            return {"accessible": True}

        def collect_profile(self, url):
            return {"platform": "douyin", "field_visibility": {}}

        def collect_post_list(self, url, limit=30, date_range=None):
            common = {
                "platform": "douyin",
                "collection_status": "SUCCESS",
                "platform_metrics": {"collection_source": "list"},
            }
            return [
                dict(
                    common,
                    post_id="7001",
                    post_url="https://www.douyin.com/video/7001",
                    title="列表标题",
                    published_at="2026-07-20T12:00:00+08:00",
                    duration_seconds=None,
                    hashtags=["列表话题"],
                ),
                dict(
                    common,
                    post_id="7002",
                    post_url="https://www.douyin.com/note/7002",
                    title="完整标题",
                    published_at="2026-07-21T12:00:00+08:00",
                    duration_seconds=8,
                    hashtags=["完整话题"],
                ),
                dict(
                    common,
                    post_id="7003",
                    post_url="https://www.douyin.com/video/7003",
                    title=None,
                    published_at="2026-07-22T12:00:00+08:00",
                    duration_seconds=9,
                    hashtags=["失败话题"],
                ),
                dict(
                    common,
                    post_id="7004",
                    post_url=ACCOUNT_URL,
                    title=None,
                    published_at=None,
                    duration_seconds=None,
                    hashtags=[],
                ),
            ]

        def collect_post_detail(self, post_url):
            self.detail_calls.append(post_url)
            if post_url.endswith("/7003"):
                raise RuntimeError("unsafe upstream body must not persist")
            return {
                "post_id": post_url.rsplit("/", 1)[-1],
                "title": "详情冲突标题",
                "published_at": "2026-07-19T12:00:00+08:00",
                "duration_seconds": 12,
                "hashtags": ["详情话题"],
            }

        def get_collection_coverage(self):
            return {}

    adapter = DetailAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(out),
        enrich_details=True,
    ) == 0

    assert adapter.detail_calls == [
        "https://www.douyin.com/video/7001",
        "https://www.douyin.com/video/7003",
    ]
    posts = [
        json.loads(line)
        for line in (out / "source" / "posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert posts[0]["title"] == "列表标题"
    assert posts[0]["published_at"] == "2026-07-20T12:00:00+08:00"
    assert posts[0]["hashtags"] == ["列表话题"]
    assert posts[0]["duration_seconds"] == 12
    assert posts[0]["platform_metrics"]["detail_status"] == "SUCCESS"
    assert posts[1]["platform_metrics"]["detail_status"] == "NOT_NEEDED"
    assert posts[2]["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert posts[3]["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert posts[2]["collection_status"] == "PARTIAL"
    assert posts[3]["collection_status"] == "PARTIAL"
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["enrich_details"] is True
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] is None
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "stage=collect_post_detail" in report
    assert "unsafe upstream body must not persist" not in report


def test_detail_enrichment_rejects_mismatched_detail_post_id():
    import collect

    class MismatchedDetailAdapter:
        def collect_post_detail(self, post_url):
            return {
                "post_id": "9999",
                "duration_seconds": 99,
                "title": "wrong item evidence",
            }

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "title": "list title",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": None,
        "hashtags": ["list topic"],
        "collection_status": "SUCCESS",
    }
    errors = []

    unavailable = collect._enrich_douyin_details(
        MismatchedDetailAdapter(),
        [post],
        errors,
        "2026-07-24T10:00:00+08:00",
    )

    assert unavailable == 1
    assert post["duration_seconds"] is None
    assert post["title"] == "list title"
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert errors[0]["message"] == "作品详情补充不可用"


@pytest.mark.parametrize(
    "stop_reason",
    [
        "LOGIN_REQUIRED",
        "VERIFICATION_REQUIRED",
        "RATE_LIMITED",
        "ACCESS_RESTRICTED",
    ],
)
def test_detail_enrichment_circuit_breaks_on_platform_protection(stop_reason):
    import collect
    from collectors.douyin import DouyinError

    class ProtectedDetailAdapter:
        def __init__(self):
            self.calls = []

        def collect_post_detail(self, post_url):
            self.calls.append(post_url)
            raise DouyinError(stop_reason, "unsafe upstream protection text")

    posts = [
        {
            "platform": "douyin",
            "post_id": post_id,
            "post_url": f"https://www.douyin.com/video/{post_id}",
            "title": None,
            "published_at": None,
            "duration_seconds": None,
            "hashtags": [],
            "collection_status": "SUCCESS",
            "platform_metrics": {"collection_source": "list"},
        }
        for post_id in ("7001", "7002")
    ]
    errors = []
    adapter = ProtectedDetailAdapter()

    unavailable = collect._enrich_douyin_details(
        adapter,
        posts,
        errors,
        "2026-07-27T10:00:00+08:00",
    )

    assert unavailable == 2
    assert adapter.calls == ["https://www.douyin.com/video/7001"]
    assert len(errors) == 1
    assert errors[0]["stage"] == "collect_post_detail"
    assert errors[0]["error_code"] == stop_reason
    assert "unsafe upstream protection text" not in json.dumps(errors)
    assert posts[0]["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert posts[0]["platform_metrics"]["detail_attempted"] is True
    assert posts[0]["platform_metrics"]["detail_stop_reason"] == stop_reason
    assert posts[1]["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert posts[1]["platform_metrics"]["detail_attempted"] is False
    assert posts[1]["platform_metrics"]["detail_stop_reason"] == stop_reason


@pytest.mark.parametrize(
    "stop_reason",
    [
        "LOGIN_REQUIRED",
        "VERIFICATION_REQUIRED",
        "RATE_LIMITED",
        "ACCESS_RESTRICTED",
    ],
)
def test_detail_protection_stops_later_details_and_all_comments(
    monkeypatch, tmp_path, stop_reason
):
    import collect
    from collectors.douyin import DouyinError

    class ProtectedRunAdapter:
        platform = "douyin"

        def __init__(self):
            self.detail_calls = []
            self.comment_calls = []

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
                    "title": None,
                    "published_at": None,
                    "duration_seconds": None,
                    "hashtags": [],
                    "collection_status": "SUCCESS",
                    "platform_metrics": {"collection_source": "list"},
                }
                for post_id in ("7001", "7002")
            ]

        def collect_post_detail(self, post_url):
            self.detail_calls.append(post_url)
            raise DouyinError(stop_reason, "unsafe protection response")

        def collect_comments(self, post_url, limit=20):
            self.comment_calls.append((post_url, limit))
            return [{"comment_id": "must-not-collect", "text": "unsafe"}]

        def get_collection_coverage(self):
            return {}

    adapter = ProtectedRunAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(out),
        enrich_details=True,
        include_comments=True,
    ) == 0

    assert adapter.detail_calls == ["https://www.douyin.com/video/7001"]
    assert adapter.comment_calls == []
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == stop_reason
    assert task["comment_collection"] == {
        "attempted_posts": 0,
        "comments_collected": 0,
        "empty_results": 0,
        "failures": 0,
        "per_post_limit": 20,
    }
    assert (out / "source" / "comments.jsonl").read_text(encoding="utf-8") == ""
    posts = [
        json.loads(line)
        for line in (out / "source" / "posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert posts[0]["platform_metrics"]["detail_attempted"] is True
    assert posts[1]["platform_metrics"]["detail_attempted"] is False
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert f"error_code={stop_reason}" in report
    assert "unsafe protection response" not in report


@pytest.mark.parametrize(
    "profile_stop_reason",
    [
        "LOGIN_REQUIRED",
        "VERIFICATION_REQUIRED",
        "RATE_LIMITED",
        "ACCESS_RESTRICTED",
    ],
)
def test_profile_protection_dominates_list_parser_failure_and_blocks_followups(
    monkeypatch, tmp_path, profile_stop_reason
):
    import collect
    from collectors.douyin import DouyinError

    partial_posts = [
        {
            "platform": "douyin",
            "post_id": post_id,
            "post_url": f"https://www.douyin.com/video/{post_id}",
            "title": None,
            "published_at": None,
            "duration_seconds": None,
            "hashtags": [],
            "collection_status": "SUCCESS",
            "platform_metrics": {"collection_source": "list"},
        }
        for post_id in ("7001", "7002")
    ]

    class ParserThenProtectedProfileAdapter:
        platform = "douyin"

        def __init__(self):
            self.detail_calls = []
            self.comment_calls = []

        def supports(self, url):
            return True

        def check_access(self, url):
            return {"accessible": True}

        def collect_post_list(self, url, limit=30, date_range=None):
            raise DouyinError(
                "PARSER_FAILED",
                "unsafe list parser response",
                partial_posts=partial_posts,
            )

        def collect_profile(self, url):
            raise DouyinError(
                profile_stop_reason,
                "unsafe profile protection response",
            )

        def collect_post_detail(self, post_url):
            self.detail_calls.append(post_url)
            return {
                "post_id": post_url.rsplit("/", 1)[-1],
                "title": "must not fetch",
                "published_at": "2026-07-20T10:00:00+08:00",
                "duration_seconds": 1,
                "hashtags": [],
            }

        def collect_comments(self, post_url, limit=20):
            self.comment_calls.append((post_url, limit))
            return []

        def get_collection_coverage(self):
            return {}

    adapter = ParserThenProtectedProfileAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "profile-protection"

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(out),
        enrich_details=True,
        include_comments=True,
    ) == 0

    assert adapter.detail_calls == []
    assert adapter.comment_calls == []
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == profile_stop_reason
    assert task["comment_collection"] == {
        "attempted_posts": 0,
        "comments_collected": 0,
        "empty_results": 0,
        "failures": 0,
        "per_post_limit": 20,
    }
    assert (out / "source" / "comments.jsonl").read_text(encoding="utf-8") == ""
    posts = [
        json.loads(line)
        for line in (out / "source" / "posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all(
        post["platform_metrics"]["detail_attempted"] is False
        and post["platform_metrics"]["detail_stop_reason"]
        == profile_stop_reason
        for post in posts
    )
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "error_code=PARSER_FAILED" in report
    assert f"error_code={profile_stop_reason}" in report
    assert "unsafe list parser response" not in report
    assert "unsafe profile protection response" not in report


def test_douyin_detail_rejects_candidate_whose_id_does_not_match_url():
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html({
        "aweme": {"detail": dict(AWEME, aweme_id="9999", desc="wrong")},
        "analytics": {"aweme_id": "7001", "cursor": "unrelated"},
    })

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == "PARSER_FAILED"


def test_collect_post_detail_uses_one_browser_detail_fallback_after_ssr_parser_failure(
    monkeypatch,
):
    """Removing the parser-only browser fallback must make this test fail."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    calls = []

    def browser_detail(**request):
        calls.append(request)
        return DouyinBrowserResult(
            aweme_items=[
                {
                    "aweme_id": "7001",
                    "aweme_id_str": "7001",
                    "share_url": "https://www.douyin.com/video/7001",
                    "desc": "公开详情没有话题",
                    "text_extra": [],
                    "create_time": 1_700_000_000,
                    "statistics": {
                        "digg_count": 0,
                        "comment_count": None,
                    },
                    "video": {"duration": 0},
                    "_collection_source": "network",
                }
            ],
            source="network",
        )

    collector = DouyinCollector(browser_collect_detail=browser_detail)
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    post = collector.collect_post_detail(
        "https://www.douyin.com/video/7001?secret=strip-me"
    )

    assert len(calls) == 1
    assert calls[0]["url"] == "https://www.douyin.com/video/7001"
    assert post["post_id"] == "7001"
    assert post["post_url"] == "https://www.douyin.com/video/7001"
    assert post["likes"] == 0
    assert post["comments"] is None
    assert post["views"] is None
    assert post["duration_seconds"] == 0
    assert post["hashtags"] == []
    assert post["collection_status"] == "SUCCESS"


@pytest.mark.parametrize(
    "render_data",
    [
        {"awemeDetail": {**AWEME, "text_extra": []}},
        {"data": {"aweme_detail": {**AWEME, "text_extra": []}}},
        {"data": {"awemeDetail": {**AWEME, "text_extra": []}}},
    ],
)
def test_collect_post_detail_uses_every_frozen_ssr_detail_path_without_browser(
    monkeypatch, render_data
):
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: pytest.fail(
            "a frozen SSR detail must stay on the existing fast path"
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(render_data),
    )

    post = collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert post["post_id"] == "7001"
    assert post["hashtags"] == ["测试"]


def test_collect_post_detail_id_only_ssr_uses_exactly_one_browser_fallback(
    monkeypatch,
):
    """An identity is routing evidence, not sufficient public post detail."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []

    def browser_detail(**request):
        browser_calls.append(request)
        return DouyinBrowserResult(
            aweme_items=[
                {
                    "aweme_id": "7001",
                    "share_url": "https://www.douyin.com/video/7001",
                    "desc": "浏览器公开详情",
                    "text_extra": [],
                }
            ],
            source="network",
        )

    collector = DouyinCollector(browser_collect_detail=browser_detail)
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"aweme_detail": {"aweme_id": "7001"}}),
    )

    post = collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert browser_calls == [{"url": "https://www.douyin.com/video/7001"}]
    assert post["post_id"] == "7001"
    assert post["title"] == "浏览器公开详情"


def test_collect_post_detail_id_only_ssr_fails_when_browser_fallback_is_disabled(
    monkeypatch,
):
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_fallback=False,
        browser_collect_detail=lambda **_request: pytest.fail(
            "disabled fallback must not open a browser"
        ),
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"aweme_detail": {"aweme_id": "7001"}}),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED


@pytest.mark.parametrize(
    "conflicting_identity",
    [
        {"aweme_id": "9999"},
        {
            "aweme_id": "7001",
            "share_url": "https://www.douyin.com/video/9999",
        },
    ],
)
def test_collect_post_detail_id_only_conflict_fails_before_browser(
    monkeypatch, conflicting_identity
):
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    browser_calls = []
    collector = DouyinCollector(
        browser_collect_detail=lambda **request: browser_calls.append(request)
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"aweme_detail": conflicting_identity}),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert browser_calls == []


def test_collect_post_detail_empty_desc_without_hashtag_observation_uses_browser(
    monkeypatch,
):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []

    def browser_detail(**request):
        browser_calls.append(request)
        return DouyinBrowserResult(
            aweme_items=[
                {
                    "aweme_id": "7001",
                    "desc": "浏览器补充文案",
                    "text_extra": [],
                }
            ]
        )

    collector = DouyinCollector(browser_collect_detail=browser_detail)
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {"aweme_detail": {"aweme_id": "7001", "desc": ""}}
        ),
    )

    post = collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert len(browser_calls) == 1
    assert post["title"] == "浏览器补充文案"


def test_collect_post_detail_empty_desc_with_known_empty_hashtags_is_trusted_ssr(
    monkeypatch,
):
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: pytest.fail(
            "known-empty hashtag evidence is a valid mapped detail field"
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {
                "aweme_detail": {
                    "aweme_id": "7001",
                    "desc": "",
                    "text_extra": [],
                }
            }
        ),
    )

    post = collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert post["post_id"] == "7001"
    assert post["title"] == ""
    assert post["hashtags"] == []
    assert "hashtags" not in post["platform_metrics"].get(
        "missing_detail_fields", []
    )


def test_collect_post_detail_respects_the_browser_fallback_disable_switch(monkeypatch):
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_fallback=False,
        browser_collect_detail=lambda **_request: pytest.fail(
            "disabled detail fallback must not open a browser"
        ),
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED


@pytest.mark.parametrize(
    ("status", "expected_stop_reason"),
    [
        (401, "LOGIN_REQUIRED"),
        (403, STOP_ACCESS_RESTRICTED),
        (429, STOP_ACCESS_RESTRICTED),
    ],
    ids=["401-login", "403-access-restricted", "429-rate-limited"],
)
def test_collect_post_detail_never_falls_back_after_http_restrictions(
    monkeypatch, status, expected_stop_reason
):
    import urllib.error

    from collectors.douyin import DouyinCollector, DouyinError

    browser_calls = []
    collector = DouyinCollector(
        browser_collect_detail=lambda **request: browser_calls.append(request)
    )

    def restricted(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://www.douyin.com/video/7001",
            status,
            "restricted",
            None,
            None,
        )

    monkeypatch.setattr("collectors.douyin.urllib.request.urlopen", restricted)

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == expected_stop_reason
    assert browser_calls == []


def test_collect_post_detail_preserves_browser_restriction_over_item_data(monkeypatch):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: DouyinBrowserResult(
            aweme_items=[AWEME],
            restriction=STOP_VERIFICATION,
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_VERIFICATION


def test_collect_post_detail_does_not_report_success_after_browser_cleanup_failure(
    monkeypatch,
):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: DouyinBrowserResult(
            aweme_items=[
                {
                    **AWEME,
                    "share_url": "https://www.douyin.com/video/7001",
                    "text_extra": [],
                }
            ],
            diagnostic_code="BROWSER_CLEANUP_FAILED",
            diagnostics={"cleanup_codes": ["TEMP_PROFILE_REMOVE_FAILED"]},
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert exc_info.value.diagnostic_code == "BROWSER_CLEANUP_FAILED"


@pytest.mark.parametrize(
    "identity",
    [
        {"aweme_id": "9999", "aweme_id_str": "9999"},
        {"aweme_id": "7001", "aweme_id_str": "9999"},
        {
            "aweme_id": "7001",
            "aweme_id_str": "7001",
            "share_url": "https://www.douyin.com/video/9999",
        },
        {
            "aweme_id": "7001",
            "aweme_id_str": "7001",
            "share_url": "https://www.douyin.com/note/7001",
        },
    ],
)
def test_collect_post_detail_rechecks_raw_and_normalized_browser_identity(
    monkeypatch, identity
):
    """Removing any collector-boundary identity check must make this test fail."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    browser_item = {
        **AWEME,
        "share_url": "https://www.douyin.com/video/7001",
        "text_extra": [],
        **identity,
    }
    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: DouyinBrowserResult(
            aweme_items=[browser_item],
            source="network",
        )
    )
    collector._browser_profile_cache[ACCOUNT_URL] = {"sentinel": "unchanged"}
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert exc_info.value.raw is None
    assert collector._browser_profile_cache == {
        ACCOUNT_URL: {"sentinel": "unchanged"}
    }


def test_collect_post_detail_rejects_a_multi_item_browser_payload(monkeypatch):
    """The known-item fallback must not become an implicit discovery channel."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: DouyinBrowserResult(
            aweme_items=[
                {
                    **AWEME,
                    "share_url": "https://www.douyin.com/video/7001",
                    "text_extra": [],
                },
                {
                    **AWEME,
                    "share_url": "https://www.douyin.com/video/7001",
                    "text_extra": [],
                },
            ],
            source="network",
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert exc_info.value.raw is None


def test_collect_post_detail_fails_closed_on_a_malformed_single_browser_item(
    monkeypatch,
):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_collect_detail=lambda **_request: DouyinBrowserResult(
            aweme_items=[None],
            source="network",
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert exc_info.value.raw is None


def test_collect_post_detail_does_not_fallback_past_an_explicit_ssr_id_conflict(
    monkeypatch,
):
    """Treating an SSR identity conflict as mere absence must make this test fail."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    browser_calls = []

    def browser_detail(**request):
        browser_calls.append(request)
        return DouyinBrowserResult()

    collector = DouyinCollector(
        browser_collect_detail=browser_detail
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {
                "aweme": {
                    "detail": {
                        **AWEME,
                        "aweme_id": "9999",
                        "share_url": "https://www.douyin.com/video/9999",
                    }
                }
            }
        ),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert browser_calls == []


def test_enrich_details_cli_flag_is_forwarded(monkeypatch):
    import collect

    captured = {}
    monkeypatch.setattr(
        collect,
        "run",
        lambda *args, **kwargs: captured.update(kwargs) or 0,
    )
    monkeypatch.setattr("sys.argv", ["collect.py", ACCOUNT_URL, "--enrich-details"])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert captured["enrich_details"] is True


def test_douyin_comments_distinguish_explicit_empty_from_unavailable():
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html(
        {"comment": {"data": {"comments": []}}}
    )
    assert collector.collect_comments("https://www.douyin.com/video/7001") == []

    collector._fetch = lambda _url: _ssr_html({"aweme": {"detail": AWEME}})
    with pytest.raises(DouyinError) as exc_info:
        collector.collect_comments("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == "COMMENTS_UNAVAILABLE"


@pytest.mark.parametrize(
    "comments",
    [
        ["secret malformed comment"],
        [
            {"cid": "c1", "user": {}, "text": "valid-looking comment"},
            "secret malformed comment",
        ],
    ],
)
def test_douyin_nonempty_malformed_comments_are_unavailable(comments):
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html(
        {"comment": {"data": {"comments": comments}}}
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_comments("https://www.douyin.com/video/7001")

    assert exc_info.value.stop_reason == "COMMENTS_UNAVAILABLE"
    assert "secret malformed comment" not in str(exc_info.value)


def test_direct_douyin_item_methods_fetch_only_canonical_urls():
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(browser_fallback=False)
    fetched = []

    def detail_fetch(url):
        fetched.append(url)
        return _ssr_html({"aweme": {"detail": AWEME}})

    collector._fetch = detail_fetch
    detail = collector.collect_post_detail(
        "https://iesdouyin.com/video/7001?token=DETAIL_SECRET#DETAIL_FRAGMENT"
    )
    assert detail["post_url"] == "https://www.douyin.com/video/7001"

    def comments_fetch(url):
        fetched.append(url)
        return _ssr_html({"comment": {"data": {"comments": []}}})

    collector._fetch = comments_fetch
    assert collector.collect_comments(
        "https://iesdouyin.com/video/7001?token=COMMENT_SECRET#COMMENT_FRAGMENT"
    ) == []
    assert fetched == [
        "https://www.douyin.com/video/7001",
        "https://www.douyin.com/video/7001",
    ]


@pytest.mark.parametrize(
    "post_url",
    [
        "https://user:password@www.douyin.com/video/7001",
        "https://www.douyin.com:443/video/7001",
    ],
)
def test_direct_douyin_item_methods_reject_credentials_and_ports(post_url):
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: pytest.fail("invalid URL must not be fetched")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_detail(post_url)

    assert exc_info.value.stop_reason == "UNSUPPORTED_PLATFORM"


def test_load_adapters_can_disable_only_douyin_browser_fallback():
    """Adapter policy controls the Douyin instance without changing others."""
    import collect

    adapters = collect._load_adapters(douyin_browser_fallback=False)

    douyin = next(adapter for adapter in adapters if adapter.platform == "douyin")
    assert douyin.browser_fallback is False


def test_no_browser_policy_overrides_bilibili_legacy_env(monkeypatch):
    """Explicit global opt-out beats BILIBILI_BROWSER_FALLBACK=1."""
    import collect

    monkeypatch.setenv("BILIBILI_BROWSER_FALLBACK", "1")

    adapters = collect._load_adapters(
        douyin_browser_fallback=False,
        bilibili_browser_fallback=False,
    )

    bilibili = next(adapter for adapter in adapters if adapter.platform == "bilibili")
    douyin = next(adapter for adapter in adapters if adapter.platform == "douyin")
    assert bilibili.browser_fallback is False
    assert bilibili._new_session()._browser_fallback is False
    assert douyin.browser_fallback is False


def test_run_passes_explicit_no_policy_to_both_browser_collectors(monkeypatch):
    """`--no-browser-fallback` is represented by run(..., False) globally."""
    import collect

    captured = {}

    def load(*, douyin_browser_fallback=True, bilibili_browser_fallback=None):
        captured["douyin"] = douyin_browser_fallback
        captured["bilibili"] = bilibili_browser_fallback
        return []

    monkeypatch.setenv("BILIBILI_BROWSER_FALLBACK", "1")
    monkeypatch.setattr(collect, "_load_adapters", load)

    assert collect.run(ACCOUNT_URL, browser_fallback=False) == 2
    assert captured == {"douyin": False, "bilibili": False}


def test_positive_cli_policy_does_not_permanently_mutate_environment(monkeypatch):
    """Compatibility enablement is passed explicitly instead of leaking env state."""
    import collect

    captured = {}
    monkeypatch.delenv("BILIBILI_BROWSER_FALLBACK", raising=False)
    monkeypatch.setattr(
        collect,
        "run",
        lambda *args, **kwargs: captured.update(kwargs) or 0,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["collect.py", ACCOUNT_URL, "--browser-fallback"],
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert captured["browser_fallback"] is True
    assert "BILIBILI_BROWSER_FALLBACK" not in __import__("os").environ


class _PartialDouyinAdapter(BaseCollector):
    platform = "douyin"

    def supports(self, url):
        return True

    def check_access(self, url):
        return {"accessible": True}

    def collect_profile(self, url):
        return {
            "platform": "douyin",
            "account_name": "公开账号",
            "field_visibility": {},
        }

    def collect_post_list(self, url, limit=30, date_range=None):
        from collectors.douyin import DouyinError

        raise DouyinError(
            STOP_VERIFICATION,
            "验证",
            raw={"secret": "must not be written"},
            partial_posts=[{
                "platform": "douyin",
                "post_id": "7001",
                "post_url": "https://www.douyin.com/video/7001",
                "collection_status": "SUCCESS",
            }],
            diagnostic_code="BROWSER_RESTRICTION",
        )

    def collect_post_detail(self, post_url):
        return {}


def test_run_persists_partial_douyin_posts_before_marking_task_partial(monkeypatch, tmp_path):
    """A restricted browser collection retains its safe normalized posts."""
    import collect

    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda douyin_browser_fallback=True: [_PartialDouyinAdapter()],
    )
    out = tmp_path / "task"

    rc = collect.run(ACCOUNT_URL, limit=30, out_dir=str(out))

    assert rc == 0
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "VERIFICATION_REQUIRED"
    rows = (out / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["post_id"] == "7001"
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "BROWSER_RESTRICTION" in report
    assert "must not be written" not in report


class _AllDouyinAdapter(_PartialDouyinAdapter):
    def __init__(self, stop_condition="terminal_page"):
        self.stop_condition = stop_condition
        self.standard_calls = []

    def collect_post_list(self, url, limit=30, date_range=None):
        self.standard_calls.append((url, limit, date_range))
        return [{
            "platform": "douyin",
            "post_id": "7001",
            "post_url": "https://www.douyin.com/video/7001",
            "collection_status": "SUCCESS",
        }]

    def collect_all_post_list(
        self,
        url,
        date_range=None,
        max_items=10000,
        max_seconds=1800.0,
        max_scrolls=2000,
    ):
        from collectors.douyin import DouyinError

        posts = self.collect_post_list(url, limit=max_items, date_range=date_range)
        if self.stop_condition != "terminal_page":
            raise DouyinError(
                "PARSER_FAILED",
                "全量作品采集在安全边界停止",
                partial_posts=posts,
                diagnostic_code="ALL_POSTS_INCOMPLETE",
            )
        return posts

    def get_collection_coverage(self):
        terminal = self.stop_condition == "terminal_page"
        return {
            "requested_all": True,
            "is_exhaustive": terminal,
            "terminal_page_observed": terminal,
            "observed_page_count": 2,
            "observed_post_count": 1,
            "cursor_fingerprint_count": 1,
            "repeated_cursor_count": 0,
            "stop_condition": self.stop_condition,
            "raw_cursor": "must-not-persist",
        }


def test_all_disabled_browser_records_requested_and_launched_false():
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(browser_fallback=False)

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_all_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    coverage = collector.get_collection_coverage()
    assert coverage["browser_fallback_requested"] is False
    assert coverage["browser_fallback_launched"] is False


def test_all_rejects_non_douyin_urls_before_writing(monkeypatch, tmp_path):
    import collect

    class OtherAdapter(_AllDouyinAdapter):
        platform = "bilibili"

    monkeypatch.setattr(collect, "_load_adapters", lambda: [OtherAdapter()])
    out = tmp_path / "task"

    rc = collect.run(
        "https://space.bilibili.com/1",
        out_dir=str(out),
        collect_all=True,
    )

    assert rc == 2
    assert not (out / "task.json").exists()


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-items", "0"),
        ("--max-seconds", "0"),
        ("--max-seconds", "nan"),
        ("--max-scrolls", "-1"),
    ],
)
def test_all_cli_budgets_must_be_positive(monkeypatch, flag, value):
    import collect

    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: pytest.fail("must reject before adapter loading"),
    )
    monkeypatch.setattr("sys.argv", ["collect.py", ACCOUNT_URL, "--all", flag, value])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


def test_all_terminal_page_writes_exhaustive_coverage(monkeypatch, tmp_path):
    import collect

    adapter = _AllDouyinAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    rc = collect.run(ACCOUNT_URL, out_dir=str(out), collect_all=True)

    assert rc == 0
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "COMPLETED"
    assert task["collection_coverage"]["is_exhaustive"] is True
    assert "raw_cursor" not in task["collection_coverage"]
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert "## 覆盖与完备性" in report
    assert "is_exhaustive: true" in report
    assert "must-not-persist" not in report


@pytest.mark.parametrize(
    "stop_condition",
    ["idle", "timeout", "repeated_cursor", "max_items", "max_scrolls"],
)
def test_all_safety_stops_keep_posts_and_mark_task_partial(
    monkeypatch, tmp_path, stop_condition
):
    import collect

    adapter = _AllDouyinAdapter(stop_condition)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    rc = collect.run(ACCOUNT_URL, out_dir=str(out), collect_all=True)

    assert rc == 0
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["collection_coverage"]["is_exhaustive"] is False
    assert task["collection_coverage"]["stop_condition"] == stop_condition
    rows = (out / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1


def test_standard_limit_thirty_keeps_existing_collection_path(monkeypatch, tmp_path):
    import collect

    adapter = _AllDouyinAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(ACCOUNT_URL, limit=30, out_dir=str(out)) == 0
    assert adapter.standard_calls == [(ACCOUNT_URL, 30, None)]


@pytest.mark.parametrize(
    "coverage",
    [
        {
            "requested_all": True,
            "is_exhaustive": True,
            "terminal_page_observed": False,
            "stop_condition": "terminal_page",
        },
        {
            "requested_all": True,
            "is_exhaustive": True,
            "terminal_page_observed": True,
            "stop_condition": "idle",
        },
        {
            "requested_all": True,
            "is_exhaustive": True,
            "terminal_page_observed": True,
            "stop_condition": ["terminal_page"],
        },
    ],
)
def test_all_collector_rejects_contradictory_exhaustive_coverage(coverage):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[AWEME],
            coverage=coverage,
        )
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_all_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == "PARSER_FAILED"
    assert exc_info.value.partial_posts[0]["post_id"] == "7001"
    assert collector.get_collection_coverage()["is_exhaustive"] is False


def test_all_workspace_downgrades_contradictory_exhaustive_coverage(
    monkeypatch, tmp_path
):
    import collect

    class ContradictoryCoverageAdapter(_AllDouyinAdapter):
        def get_collection_coverage(self):
            return {
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "stop_condition": "idle",
            }

    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda: [ContradictoryCoverageAdapter()],
    )
    out = tmp_path / "task"

    assert collect.run(ACCOUNT_URL, out_dir=str(out), collect_all=True) == 0
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["collection_coverage"]["is_exhaustive"] is False
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "PARSER_FAILED"


@pytest.mark.parametrize(
    "invalid_item",
    [
        {"desc": "缺少平台作品 ID"},
        {"aweme_id": "not-a-number", "desc": "非数字平台作品 ID"},
        {"aweme_id_str": "", "desc": "空平台作品 ID"},
    ],
)
def test_all_collector_rejects_items_without_numeric_platform_post_id(invalid_item):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[invalid_item],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "stop_condition": "terminal_page",
            },
        )
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_all_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == "PARSER_FAILED"
    assert exc_info.value.partial_posts == []
    assert collector.get_collection_coverage()["is_exhaustive"] is False
    assert collector.get_collection_coverage()["terminal_page_observed"] is False


def test_limited_ssr_invalid_only_payload_raises_parser_failed():
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html({
        "user": {"post": {"data": [
            {
                "author": {"sec_uid": "example"},
                "desc": "missing id",
            },
            {
                "aweme_id": "not-numeric",
                "author": {"sec_uid": "example"},
                "desc": "invalid id",
            },
        ]}}
    })

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL, limit=30)

    assert exc_info.value.stop_reason == "PARSER_FAILED"
    assert exc_info.value.diagnostic_code == "INVALID_PLATFORM_POST_ID"
    assert exc_info.value.partial_posts == []


def test_limited_browser_invalid_only_payload_raises_parser_failed():
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[{"aweme_id": "bad", "desc": "invalid id"}],
            source="network",
        )
    )
    collector._fetch = lambda _url: "<html>no render data</html>"

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL, limit=30)

    assert exc_info.value.stop_reason == "PARSER_FAILED"
    assert exc_info.value.diagnostic_code == "INVALID_PLATFORM_POST_ID"
    assert exc_info.value.partial_posts == []


def test_duplicate_merge_fills_empty_containers_but_preserves_zero_and_false():
    from collectors.douyin import DouyinCollector

    items = DouyinCollector._validated_aweme_items([
        {
            "aweme_id": "7001",
            "text_extra": [],
            "video": {},
            "statistics": {"digg_count": 0},
            "is_top": False,
        },
        {
            "aweme_id": "7001",
            "text_extra": [{"hashtag_name": "filled"}],
            "video": {"duration": 9000},
            "statistics": {"digg_count": 99, "comment_count": 5},
            "is_top": True,
        },
    ])

    assert items == [{
        "aweme_id": "7001",
        "text_extra": [{"hashtag_name": "filled"}],
        "video": {"duration": 9000},
        "statistics": {"digg_count": 0, "comment_count": 5},
        "is_top": False,
    }]


def test_duplicate_merge_does_not_mutate_input_evidence():
    from collectors.douyin import DouyinCollector

    first = {
        "aweme_id": "7001",
        "statistics": {"digg_count": 0},
        "video": {},
    }
    second = {
        "aweme_id": "7001",
        "statistics": {"comment_count": 5},
        "video": {"duration": 9_000},
    }

    DouyinCollector._validated_aweme_items([first, second])

    assert first == {
        "aweme_id": "7001",
        "statistics": {"digg_count": 0},
        "video": {},
    }
    assert second == {
        "aweme_id": "7001",
        "statistics": {"comment_count": 5},
        "video": {"duration": 9_000},
    }


def test_all_collector_drops_invalid_ids_without_profile_url_fallback():
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[
                {"aweme_id": "invalid", "desc": "必须丢弃"},
                AWEME,
            ],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "stop_condition": "terminal_page",
            },
        )
    )

    posts = collector.collect_all_post_list(ACCOUNT_URL)

    assert [post["post_id"] for post in posts] == ["7001"]
    assert posts[0]["post_url"] != ACCOUNT_URL
    assert posts[0]["source_url"] != ACCOUNT_URL


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({}, (None, None, None)),
        (
            {"is_top": True, "is_repost": True, "is_ad": True},
            (True, True, True),
        ),
        (
            {"is_top": False, "is_repost": False, "is_ad": False},
            (False, False, False),
        ),
    ],
)
def test_all_collector_preserves_public_boolean_evidence(flags, expected):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[dict(AWEME, **flags)],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "stop_condition": "terminal_page",
            },
        )
    )

    post = collector.collect_all_post_list(ACCOUNT_URL)[0]

    assert (
        post["is_pinned"],
        post["is_repost"],
        post["is_promoted"],
    ) == expected


def test_all_terminal_empty_list_raises_no_public_content_with_coverage():
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_page_count": 1,
                "observed_post_count": 0,
                "stop_condition": "terminal_page",
            },
        )
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_all_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_NO_PUBLIC_CONTENT
    assert collector.get_collection_coverage()["is_exhaustive"] is True


def test_all_terminal_empty_list_writes_failed_no_public_content(
    monkeypatch, tmp_path, capsys
):
    import collect
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_page_count": 1,
                "observed_post_count": 0,
                "stop_condition": "terminal_page",
            },
        )
    )
    monkeypatch.setattr(
        collector,
        "check_access",
        lambda url: {"accessible": True},
    )
    monkeypatch.setattr(
        collector,
        "collect_profile",
        lambda url: {"platform": "douyin", "field_visibility": {}},
    )
    monkeypatch.setattr(collect, "_load_adapters", lambda: [collector])
    out = tmp_path / "task"

    assert collect.run(ACCOUNT_URL, out_dir=str(out), collect_all=True) == 3
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["stop_reason"] == STOP_NO_PUBLIC_CONTENT
    assert task["collection_coverage"]["is_exhaustive"] is True
    captured = capsys.readouterr()
    assert "[COMMITTED]" in captured.out
    assert "[FAILED]" in captured.out
    assert "[OK]" not in captured.out


def test_all_exhaustive_date_range_with_no_matches_returns_successful_empty():
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[AWEME],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_page_count": 1,
                "observed_post_count": 1,
                "stop_condition": "terminal_page",
            },
        )
    )

    posts = collector.collect_all_post_list(
        ACCOUNT_URL,
        date_range=("2030-01-01T00:00:00+08:00", None),
    )

    assert posts == []
    assert collector.get_collection_coverage()["observed_post_count"] == 1
    assert collector.get_collection_coverage()["range_filter_applied"] is True
    assert collector.get_collection_coverage()["range_match_count"] == 0
    assert collector.get_collection_coverage()["range_no_match"] is True


def test_all_exhaustive_date_range_no_match_writes_completed_workspace(
    monkeypatch, tmp_path
):
    import collect
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[AWEME],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_page_count": 1,
                "observed_post_count": 1,
                "stop_condition": "terminal_page",
            },
        )
    )
    monkeypatch.setattr(
        collector,
        "check_access",
        lambda url: {"accessible": True},
    )
    monkeypatch.setattr(
        collector,
        "collect_profile",
        lambda url: {"platform": "douyin", "field_visibility": {}},
    )
    monkeypatch.setattr(collect, "_load_adapters", lambda: [collector])
    out = tmp_path / "task"

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(out),
        collect_all=True,
        date_from="2030-01-01",
    ) == 0
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "COMPLETED"
    assert task["stop_reason"] is None
    assert task["collected_count"] == 0
    assert task["collection_coverage"]["observed_post_count"] == 1
    assert task["collection_coverage"]["range_no_match"] is True


def test_collect_post_list_keeps_ssr_fast_path_without_browser(monkeypatch):
    """A valid SSR document must not start the optional browser fallback."""
    from collectors.douyin import DouyinCollector

    browser_calls = []
    collector = DouyinCollector(
        browser_collect=lambda **kwargs: browser_calls.append(kwargs),
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda url: _ssr_html({
            "user": {
                "post": {
                    "data": [dict(
                        ACCOUNT_AWEME,
                        share_url="https://www.douyin.com/note/7001?secret=x",
                    )]
                }
            }
        }),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert [post["post_id"] for post in posts] == ["7001"]
    assert posts[0]["post_url"] == "https://www.douyin.com/note/7001"
    assert browser_calls == []
    coverage = collector.get_collection_coverage()
    assert coverage["browser_fallback_requested"] is True
    assert coverage["browser_fallback_launched"] is False


def test_collect_post_list_uses_browser_when_ssr_is_missing(monkeypatch):
    """Browser-aweme data shares the existing normalization path."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []

    def browser_collect(**kwargs):
        browser_calls.append(kwargs)
        return DouyinBrowserResult(
            aweme_items=[dict(
                AWEME,
                share_url="https://www.douyin.com/note/7001?secret=x",
            )],
            source="network",
        )

    collector = DouyinCollector(browser_collect=browser_collect)
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert browser_calls == [{"url": ACCOUNT_URL, "limit": 1, "date_range": None}]
    assert posts[0]["post_id"] == "7001"
    assert posts[0]["post_url"] == "https://www.douyin.com/note/7001"
    assert posts[0]["likes"] == 12


def test_collect_post_list_uses_browser_when_ssr_shape_is_unrecognized(monkeypatch):
    """Present-but-unknown SSR is the same fallback case as absent SSR."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []
    collector = DouyinCollector(
        browser_collect=lambda **kwargs: (
            browser_calls.append(kwargs)
            or DouyinBrowserResult(aweme_items=[AWEME], source="network")
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda url: _ssr_html({"user": {"post": {"unexpected": []}}}),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert posts[0]["post_id"] == "7001"
    assert len(browser_calls) == 1


def test_limited_ssr_ignores_arbitrary_recommendation_tree(monkeypatch):
    """A same-author recommendation list is not an account-post container."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []
    browser_item = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "浏览器账号作品",
    }
    collector = DouyinCollector(
        browser_collect=lambda **request: (
            browser_calls.append(request)
            or DouyinBrowserResult(aweme_items=[browser_item], source="network")
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {"recommendations": {"items": [ACCOUNT_AWEME]}}
        ),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert browser_calls == [
        {"url": ACCOUNT_URL, "limit": 1, "date_range": None}
    ]
    assert [post["post_id"] for post in posts] == ["7999"]


@pytest.mark.parametrize(
    "author",
    [None, {"sec_uid": "foreign-account"}],
    ids=["missing-author", "foreign-author"],
)
def test_limited_ssr_frozen_nonempty_container_requires_target_author(
    monkeypatch, author
):
    """Every item in a frozen SSR account page must bind to the requested user."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    ssr_item = dict(AWEME)
    if author is not None:
        ssr_item["author"] = author
    browser_item = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "浏览器账号作品",
    }
    browser_calls = []
    collector = DouyinCollector(
        browser_collect=lambda **request: (
            browser_calls.append(request)
            or DouyinBrowserResult(aweme_items=[browser_item], source="network")
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {"user": {"post": {"data": [ssr_item]}}}
        ),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert len(browser_calls) == 1
    assert [post["post_id"] for post in posts] == ["7999"]


@pytest.mark.parametrize(
    "post_container",
    [
        {"data": []},
        {"data": [], "sec_uid": "foreign-account"},
        {"data": [], "sec_user_id": "foreign-account"},
    ],
    ids=["missing-binding", "foreign-sec-uid", "foreign-sec-user-id"],
)
def test_limited_empty_ssr_requires_target_account_evidence(
    monkeypatch, post_container
):
    """An empty SSR list without exact account evidence must use the browser."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_calls = []
    browser_item = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "浏览器账号作品",
    }
    collector = DouyinCollector(
        browser_collect=lambda **request: (
            browser_calls.append(request)
            or DouyinBrowserResult(aweme_items=[browser_item], source="network")
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"user": {"post": post_container}}),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert len(browser_calls) == 1
    assert [post["post_id"] for post in posts] == ["7999"]


def test_limited_unbound_empty_ssr_fails_closed_without_browser(monkeypatch):
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"user": {"post": {"data": []}}}),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert exc_info.value.stop_reason == "PARSER_FAILED"


def test_collect_post_list_maps_recognized_empty_ssr_to_no_public_content(monkeypatch):
    """A real empty list is not a parser failure and does not start Chrome."""
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: pytest.fail("recognized [] must not fallback")
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda url: _ssr_html(
            {"user": {"post": {"data": [], "sec_uid": "example"}}}
        ),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_NO_PUBLIC_CONTENT


def test_collect_post_list_can_disable_browser_fallback(monkeypatch):
    """The opt-out preserves the previous public parser-failure behavior."""
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_fallback=False,
        browser_collect=lambda **kwargs: pytest.fail("browser should stay disabled"),
    )
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert collector.get_collection_coverage()["browser_fallback_requested"] is False
    assert collector.get_collection_coverage()["browser_fallback_launched"] is False


def test_collect_post_list_retains_normalized_partial_posts_on_restriction(monkeypatch):
    """A browser restriction retains already-collected normalized post data."""
    from collectors._constants import STOP_VERIFICATION
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[AWEME],
            source="network",
            restriction=STOP_VERIFICATION,
            diagnostics={"stop_condition": STOP_VERIFICATION},
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_VERIFICATION
    assert exc_info.value.partial_posts[0]["post_id"] == "7001"


class FakeBrowser:
    """Small in-memory CDP page double for bounded collection tests."""

    def __init__(self, events=(), bodies=None, body_errors=None, page_texts=(), cards=()):
        self.events = list(events)
        self.bodies = dict(bodies or {})
        self.body_errors = dict(body_errors or {})
        self.page_texts = list(page_texts)
        self.cards = list(cards)
        self.navigations = []
        self.scrolls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def navigate(self, url, timeout):
        self.navigations.append((url, timeout))

    def poll_event(self, timeout):
        return self.events.pop(0) if self.events else None

    def get_response_body(self, request_id):
        if request_id in self.body_errors:
            raise self.body_errors[request_id]
        return self.bodies[request_id]

    def page_text(self):
        return self.page_texts.pop(0) if self.page_texts else ""

    def scroll_by(self, viewports):
        self.scrolls.append(viewports)

    def evaluate(self, expression):
        return self.cards


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 50_001},
        {"limit": 1.5},
        {"limit": True},
        {"limit": 1, "max_seconds": 0},
        {"limit": 1, "max_seconds": float("nan")},
        {"limit": 1, "max_seconds": float("inf")},
        {"limit": 1, "max_seconds": 14_400.1},
        {"limit": 1, "max_scrolls": 0},
        {"limit": 1, "max_scrolls": 20_001},
        {"limit": 1, "max_scrolls": 1.5},
    ],
)
def test_all_transport_rejects_invalid_budgets_without_opening_browser(kwargs):
    from collectors._douyin_browser_transport import collect_account_page

    with pytest.raises(ValueError):
        collect_account_page(
            ACCOUNT_URL,
            all_posts=True,
            session_factory=lambda: pytest.fail("browser must not open"),
            **kwargs,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": 0},
        {"max_items": 50_001},
        {"max_items": 1.5},
        {"max_seconds": float("nan")},
        {"max_seconds": 14_400.1},
        {"max_scrolls": 20_001},
        {"max_scrolls": 1.5},
    ],
)
def test_all_collector_rejects_invalid_budgets_before_transport(kwargs):
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **request: pytest.fail("transport must not run")
    )

    with pytest.raises(ValueError):
        collector.collect_all_post_list(ACCOUNT_URL, **kwargs)


def test_all_transport_accepts_exact_caps_and_reports_effective_max_items():
    from collectors._douyin_browser_transport import collect_account_page

    payload = {
        "aweme_list": [ACCOUNT_AWEME],
        "has_more": False,
        "cursor": "must-not-persist",
    }
    browser = FakeBrowser(
        events=[
            _response_event("cap"),
            _loading_event("Network.loadingFinished", "cap"),
        ],
        bodies={"cap": json.dumps(payload)},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=50_000,
        all_posts=True,
        max_seconds=14_400.0,
        max_scrolls=20_000,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.coverage["max_items"] == 50_000
    assert result.coverage["stop_condition"] == "terminal_page"


def test_all_collector_forwards_exact_caps_and_reports_effective_max_items():
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    captured = {}

    def browser_collect(**request):
        captured.update(request)
        return DouyinBrowserResult(
            aweme_items=[AWEME],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_page_count": 1,
                "observed_post_count": 1,
                "stop_condition": "terminal_page",
                "max_items": request["limit"],
            },
        )

    collector = DouyinCollector(browser_collect=browser_collect)
    posts = collector.collect_all_post_list(
        ACCOUNT_URL,
        max_items=50_000,
        max_seconds=14_400.0,
        max_scrolls=20_000,
    )

    assert posts[0]["post_id"] == "7001"
    assert captured["limit"] == 50_000
    assert captured["max_seconds"] == 14_400.0
    assert captured["max_scrolls"] == 20_000
    assert collector.get_collection_coverage()["max_items"] == 50_000


def test_all_collector_transport_failure_keeps_accepted_max_items_coverage():
    from collectors.douyin import DouyinCollector, DouyinError

    def fail_transport(**request):
        raise RuntimeError("transport failed")

    collector = DouyinCollector(browser_collect=fail_transport)

    with pytest.raises(DouyinError):
        collector.collect_all_post_list(ACCOUNT_URL, max_items=50_000)

    coverage = collector.get_collection_coverage()
    assert coverage["requested_all"] is True
    assert coverage["max_items"] == 50_000


RESPONSE_EVENT = {
    "method": "Network.responseReceived",
    "params": {
        "requestId": "r1",
        "type": "Fetch",
        "response": {
            "url": "https://www.douyin.com/aweme/v1/web/aweme/post/?signed=secret#x",
            "mimeType": "application/json",
            "status": 200,
        },
    },
}


def _response_event(request_id, *, host="www.douyin.com", url=None, status=200):
    event = json.loads(json.dumps(RESPONSE_EVENT))
    event["params"]["requestId"] = request_id
    event["params"]["response"]["url"] = url or (
        f"https://{host}/aweme/v1/web/aweme/post/?signed=secret"
    )
    event["params"]["response"]["status"] = status
    return event


def _loading_event(method, request_id):
    return {"method": method, "params": {"requestId": request_id}}


@pytest.mark.parametrize(
    ("unbound_items", "expected_ids"),
    [
        (
            [
                {
                    **AWEME,
                    "author": {"sec_uid": "foreign-account"},
                }
            ],
            ["7999"],
        ),
        ([AWEME], ["7999"]),
        (
            [
                ACCOUNT_AWEME,
                {
                    **AWEME,
                    "aweme_id": "7002",
                    "author": {"sec_uid": "foreign-account"},
                },
            ],
            ["7001", "7999"],
        ),
    ],
    ids=["foreign-author", "missing-author", "mixed-authors"],
)
def test_account_page_rejects_unvalidated_candidate_and_continues(
    unbound_items,
    expected_ids,
):
    """An unvalidated target candidate cannot donate data or prove continuity."""
    from collectors._douyin_browser_transport import collect_account_page

    later = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "目标账号后续作品",
    }
    browser = FakeBrowser(
        events=[
            _response_event(
                "unbound",
                url=(
                    "https://www.douyin.com/aweme/v1/web/aweme/post/"
                    "?sec_uid=example&signed=must-not-win"
                ),
            ),
            _loading_event("Network.loadingFinished", "unbound"),
            _response_event("bound"),
            _loading_event("Network.loadingFinished", "bound"),
        ],
        bodies={
            "unbound": json.dumps(
                {
                    "aweme_list": unbound_items,
                    "has_more": False,
                    "max_cursor": "foreign-terminal-cursor",
                }
            ),
            "bound": json.dumps(
                {
                    "aweme_list": [later],
                    "has_more": False,
                    "max_cursor": "bound-terminal-cursor",
                }
            ),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == expected_ids
    assert result.coverage["observed_page_count"] == 1
    assert result.coverage["cursor_fingerprint_count"] == 1
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


@pytest.mark.parametrize(
    ("body_binding", "response_url"),
    [
        (
            {},
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_uid=foreign-account"
            ),
        ),
        (
            {"sec_uid": "foreign-account"},
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_uid=example"
            ),
        ),
        (
            {"sec_user_id": "foreign-account"},
            "https://www.douyin.com/aweme/v1/web/aweme/post/",
        ),
    ],
    ids=[
        "foreign-response-url",
        "foreign-container-sec-uid",
        "foreign-container-sec-user-id",
    ],
)
def test_nonempty_account_page_rejects_explicit_foreign_binding(
    body_binding, response_url
):
    """Matching item authors cannot override a foreign page-level identity."""
    from collectors._douyin_browser_transport import collect_account_page

    body = {
        "aweme_list": [ACCOUNT_AWEME],
        "has_more": False,
        "max_cursor": "foreign-terminal-cursor",
        **body_binding,
    }
    browser = FakeBrowser(
        events=[
            _response_event("foreign", url=response_url),
            _loading_event("Network.loadingFinished", "foreign"),
        ],
        bodies={"foreign": json.dumps(body)},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.profile_raw is None
    assert result.coverage["observed_page_count"] == 0
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False


def test_limited_account_page_does_not_mix_foreign_network_items():
    """Limited mode applies the same account binding before satisfying its limit."""
    from collectors._douyin_browser_transport import collect_account_page

    foreign = {
        **AWEME,
        "author": {"sec_uid": "foreign-account"},
    }
    target = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "目标账号作品",
    }
    browser = FakeBrowser(
        events=[
            _response_event("foreign"),
            _loading_event("Network.loadingFinished", "foreign"),
            _response_event("target"),
            _loading_event("Network.loadingFinished", "target"),
        ],
        bodies={
            "foreign": json.dumps({"aweme_list": [foreign]}),
            "target": json.dumps({"aweme_list": [target]}),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7999"]
    assert result.coverage["observed_page_count"] == 1


def test_account_page_accepts_only_bound_list_items_not_detail_siblings():
    """Only a bound list container may contribute account-page network items."""
    from collectors._douyin_browser_transport import collect_account_page

    unrelated_detail = {
        **AWEME,
        "aweme_id": "7998",
        "desc": "同响应中的无关详情",
        "author": {"sec_uid": "foreign-account"},
    }
    browser = FakeBrowser(
        events=[
            _response_event("bound"),
            _loading_event("Network.loadingFinished", "bound"),
        ],
        bodies={
            "bound": json.dumps(
                {
                    "data": {
                        "aweme_list": [ACCOUNT_AWEME],
                        "has_more": False,
                    },
                    "aweme_detail": unrelated_detail,
                }
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["is_exhaustive"] is True


@pytest.mark.parametrize(
    ("body", "response_url"),
    [
        (
            {"aweme_list": [], "has_more": False},
            "https://www.douyin.com/aweme/v1/web/aweme/post/",
        ),
        (
            {"aweme_list": [], "has_more": False},
            "https://www.douyin.com/aweme/v1/web/aweme/post/?signed=irrelevant",
        ),
        (
            {"aweme_list": [], "has_more": False},
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_uid=example&sec_uid=example"
            ),
        ),
        (
            {"aweme_list": [], "has_more": False},
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_uid=example&sec_user_id=foreign-account"
            ),
        ),
        (
            {"aweme_list": [], "has_more": False},
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_uid=%FF"
            ),
        ),
        (
            {"aweme_list": [], "has_more": False},
            (
                "https://www.douyin.com/aweme/v1/web/general/search/"
                "?sec_uid=example"
            ),
        ),
        (
            {
                "aweme_list": [],
                "sec_uid": "foreign-account",
                "has_more": False,
            },
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_uid=example"
            ),
        ),
        (
            {
                "aweme_list": [],
                "sec_uid": "example",
                "sec_user_id": "foreign-account",
                "has_more": False,
            },
            "https://www.douyin.com/aweme/v1/web/aweme/post/",
        ),
    ],
    ids=[
        "missing-binding",
        "unrelated-query",
        "duplicate-binding",
        "conflicting-query-bindings",
        "invalid-utf8-binding",
        "unrelated-response-path",
        "container-conflicts-with-query",
        "container-conflicting-bindings",
    ],
)
def test_unbound_empty_page_cannot_prove_terminal_or_exhaustive(body, response_url):
    """An empty list needs one unambiguous account proof from its owner or URL."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _response_event("empty", url=response_url),
            _loading_event("Network.loadingFinished", "empty"),
        ],
        bodies={"empty": json.dumps(body)},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.coverage["observed_page_count"] == 0
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False


@pytest.mark.parametrize(
    ("body", "response_url"),
    [
        (
            {
                "aweme_list": [],
                "sec_uid": "example",
                "has_more": False,
            },
            "https://www.douyin.com/aweme/v1/web/aweme/post/",
        ),
        (
            {
                "aweme_list": [],
                "sec_user_id": "example",
                "has_more": False,
            },
            "https://www.douyin.com/aweme/v1/web/aweme/post/",
        ),
        (
            {"aweme_list": [], "has_more": False},
            (
                "https://www.douyin.com/aweme/v1/web/aweme/post/"
                "?sec_user_id=%65xample&signed=query-secret"
            ),
        ),
    ],
    ids=["container-sec-uid", "container-sec-user-id", "strict-decoded-url"],
)
def test_bound_empty_page_can_prove_terminal_without_leaking_query(body, response_url):
    """A single exact empty-page binding may prove exhaustion; query stays ephemeral."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _response_event("empty", url=response_url),
            _loading_event("Network.loadingFinished", "empty"),
        ],
        bodies={"empty": json.dumps(body)},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.coverage["observed_page_count"] == 1
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is True
    assert result.diagnostics["response_paths"] == [
        "https://www.douyin.com/aweme/v1/web/aweme/post/"
    ]
    assert "example" not in json.dumps(result.diagnostics)
    assert "query-secret" not in json.dumps(result.diagnostics)


@pytest.mark.parametrize(
    "response_path",
    [
        "/aweme/v1/web/recommend/feed/",
        "/aweme/v1/web/general/search/",
        "/aweme/v1/web/aweme/detail/",
    ],
    ids=["recommend", "search", "detail"],
)
def test_account_page_ignores_matching_lists_from_non_post_responses(response_path):
    """A matching author cannot turn a non-account response into pagination."""
    from collectors._douyin_browser_transport import collect_account_page

    unrelated = {
        **ACCOUNT_AWEME,
        "aweme_id": "7888",
        "desc": "非账号作品列表响应",
    }
    target = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "账号作品接口结果",
    }
    browser = FakeBrowser(
        events=[
            _response_event(
                "unrelated",
                url=(
                    f"https://www.douyin.com{response_path}"
                    "?sec_uid=example"
                ),
            ),
            _loading_event("Network.loadingFinished", "unrelated"),
            _response_event("bound"),
            _loading_event("Network.loadingFinished", "bound"),
        ],
        bodies={
            "unrelated": json.dumps(
                {
                    "aweme_list": [unrelated],
                    "has_more": False,
                    "max_cursor": "unrelated-terminal-cursor",
                }
            ),
            "bound": json.dumps(
                {
                    "aweme_list": [target],
                    "has_more": False,
                    "max_cursor": "bound-terminal-cursor",
                }
            ),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7999"]
    assert result.coverage["observed_page_count"] == 1
    assert result.coverage["cursor_fingerprint_count"] == 1
    assert result.coverage["is_exhaustive"] is True


def test_account_post_response_ignores_recommendation_list_sibling():
    """A nested recommendation cannot donate items or a terminal flag."""
    from collectors._douyin_browser_transport import collect_account_page

    recommendation = {
        **ACCOUNT_AWEME,
        "aweme_id": "7888",
        "desc": "推荐区同作者作品",
    }
    later = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "下一页账号作品",
    }
    browser = FakeBrowser(
        events=[
            _response_event("first"),
            _loading_event("Network.loadingFinished", "first"),
            _response_event("later"),
            _loading_event("Network.loadingFinished", "later"),
        ],
        bodies={
            "first": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME],
                    "has_more": True,
                    "max_cursor": "account-cursor",
                    "recommendations": {
                        "aweme_list": [recommendation],
                        "has_more": False,
                        "max_cursor": "recommendation-terminal-cursor",
                    },
                }
            ),
            "later": json.dumps(
                {
                    "aweme_list": [later],
                    "has_more": False,
                    "max_cursor": "account-terminal-cursor",
                }
            ),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == [
        "7001",
        "7999",
    ]
    assert result.coverage["observed_page_count"] == 2
    assert result.coverage["cursor_fingerprint_count"] == 2
    assert result.coverage["is_exhaustive"] is True


def test_account_post_response_rejects_deep_arbitrary_list_owner():
    """A deep arbitrary list is inert and leaves collection non-exhaustive."""
    from collectors._douyin_browser_transport import collect_account_page

    deep_item = {
        **ACCOUNT_AWEME,
        "aweme_id": "7888",
        "desc": "深层任意列表",
    }
    later = {
        **ACCOUNT_AWEME,
        "aweme_id": "7999",
        "desc": "冻结路径账号作品",
    }
    browser = FakeBrowser(
        events=[
            _response_event("deep"),
            _loading_event("Network.loadingFinished", "deep"),
            _response_event("later"),
            _loading_event("Network.loadingFinished", "later"),
        ],
        bodies={
            "deep": json.dumps(
                {
                    "envelope": {
                        "data": {
                            "aweme_list": [deep_item],
                            "has_more": False,
                            "max_cursor": "deep-terminal-cursor",
                        }
                    }
                }
            ),
            "later": json.dumps(
                {
                    "data": {
                        "aweme_list": [later],
                        "has_more": False,
                        "max_cursor": "bound-terminal-cursor",
                    }
                }
            ),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7999"]
    assert result.coverage["observed_page_count"] == 1
    assert result.coverage["cursor_fingerprint_count"] == 1
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


def test_collect_post_page_returns_only_the_bound_detail_payload():
    """Removing the dedicated detail extractor must make this contract fail."""
    from collectors._douyin_browser_transport import collect_post_page

    item_url = "https://www.douyin.com/video/7001"
    browser = FakeBrowser(
        events=[
            _response_event("detail"),
            _loading_event("Network.loadingFinished", "detail"),
        ],
        bodies={
            "detail": json.dumps(
                {
                    "aweme_detail": {
                        **AWEME,
                        "share_url": item_url,
                        "text_extra": [],
                    }
                }
            )
        },
    )

    result = collect_post_page(
        item_url,
        session_factory=lambda: browser,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.source == "network"
    assert result.restriction is None
    assert len(browser.navigations) == 1
    navigated_url, navigation_timeout = browser.navigations[0]
    assert navigated_url == item_url
    assert 0 < navigation_timeout <= 20.0
    assert browser.scrolls == []


def test_collect_post_page_ignores_lists_recommendations_and_arbitrary_id_objects():
    """A detail fallback must not discover an item from unrelated payload shapes."""
    from collectors._douyin_browser_transport import collect_post_page

    browser = FakeBrowser(
        events=[
            _response_event("pollution"),
            _loading_event("Network.loadingFinished", "pollution"),
        ],
        bodies={
            "pollution": json.dumps(
                {
                    "aweme_list": [AWEME],
                    "recommendations": {
                        "aweme_detail": {
                            **AWEME,
                            "share_url": "https://www.douyin.com/video/7001",
                        }
                    },
                    "analytics": {"aweme_id": "7001", "desc": "unrelated"},
                }
            )
        },
    )

    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        session_factory=lambda: browser,
    )

    assert result.aweme_items == []
    assert result.diagnostic_code is None


def test_collect_post_page_visible_restriction_overrides_a_network_detail():
    """Restriction evidence wins even when the same event reveals a bound item."""
    from collectors._douyin_browser_transport import collect_post_page

    class RestrictedBrowser(FakeBrowser):
        def evaluate(self, _expression):
            pytest.fail("restriction must stop before DOM fallback")

    browser = RestrictedBrowser(
        events=[
            _response_event("detail"),
            _loading_event("Network.loadingFinished", "detail"),
        ],
        bodies={
            "detail": json.dumps(
                {
                    "aweme_detail": {
                        **AWEME,
                        "share_url": "https://www.douyin.com/video/7001",
                    }
                }
            )
        },
        page_texts=["", "请登录后查看完整内容"],
    )

    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        session_factory=lambda: browser,
    )

    assert result.aweme_items == []
    assert result.restriction == STOP_LOGIN
    assert result.diagnostics["stop_condition"] == STOP_LOGIN


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_seconds": 0},
        {"max_seconds": float("nan")},
        {"max_seconds": 90.1},
        {"max_candidates": 0},
        {"max_candidates": 33},
        {"max_candidates": 1.5},
        {"max_body_chars": 0},
        {"max_body_chars": 4_000_001},
        {"max_body_chars": 1.5},
    ],
)
def test_collect_post_page_rejects_invalid_budgets_before_opening_browser(kwargs):
    """Removing any hard detail budget validation must make this test fail."""
    from collectors._douyin_browser_transport import collect_post_page

    with pytest.raises(ValueError):
        collect_post_page(
            "https://www.douyin.com/video/7001",
            session_factory=lambda: pytest.fail("invalid budgets must not open Chrome"),
            **kwargs,
        )


def test_collect_post_page_does_not_navigate_after_its_deadline_is_spent():
    """Session startup time is part of the hard detail-page time budget."""
    from collectors._douyin_browser_transport import collect_post_page

    browser = FakeBrowser()
    clock_reads = iter([0.0, 2.0, 2.0, 2.0])

    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        max_seconds=1.0,
        session_factory=lambda: browser,
        monotonic=lambda: next(clock_reads),
    )

    assert browser.navigations == []
    assert result.aweme_items == []
    assert result.diagnostics["stop_condition"] == "timeout"


@pytest.mark.parametrize(
    "conflict",
    [
        {"aweme_id": "9999"},
        {"aweme_id": "7001", "aweme_id_str": "9999"},
        {
            "aweme_id": "7001",
            "share_url": "https://www.douyin.com/video/9999?secret=do-not-leak",
        },
        {
            "aweme_id": "7001",
            "share_url": "https://www.douyin.com/note/7001",
        },
    ],
)
def test_collect_post_page_fails_closed_on_every_explicit_detail_identity_conflict(
    conflict,
):
    """Removing raw ID/share-URL binding must make this test fail."""
    from collectors._douyin_browser_transport import collect_post_page

    browser = FakeBrowser(
        events=[
            _response_event("conflict"),
            _loading_event("Network.loadingFinished", "conflict"),
        ],
        bodies={
            "conflict": json.dumps(
                {"aweme_detail": {**AWEME, "text_extra": [], **conflict}}
            )
        },
    )

    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        session_factory=lambda: browser,
    )

    assert result.aweme_items == []
    assert result.diagnostic_code == "DETAIL_ID_MISMATCH"
    assert "secret" not in json.dumps(result.diagnostics)


def test_collect_post_page_uses_one_bound_visible_detail_snapshot_when_network_is_empty():
    """Removing the detail-page DOM fallback must make this test fail."""
    from collectors._douyin_browser_transport import collect_post_page

    class VisibleDetailBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(events=[], page_texts=[""])
            self.evaluations = 0

        def evaluate(self, _expression):
            self.evaluations += 1
            return {
                "aweme_id": "7001",
                "share_url": "https://www.douyin.com/video/7001",
                "desc": "可见详情 #现场",
                "text_extra": [{"hashtag_name": "现场"}],
                "statistics": {"digg_count": "0", "comment_count": "3"},
            }

    browser = VisibleDetailBrowser()
    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        session_factory=lambda: browser,
    )

    assert result.source == "dom"
    assert result.aweme_items == [
        {
            "aweme_id": "7001",
            "share_url": "https://www.douyin.com/video/7001",
            "desc": "可见详情 #现场",
            "text_extra": [{"hashtag_name": "现场"}],
            "statistics": {"digg_count": "0", "comment_count": "3"},
            "_collection_source": "dom",
        }
    ]
    assert browser.evaluations == 1
    assert browser.scrolls == []


def test_collect_post_page_rejects_a_path_only_dom_snapshot_without_visible_evidence():
    """A matching address alone must never be promoted to public detail data."""
    from collectors._douyin_browser_transport import collect_post_page

    class PathOnlyBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return {
                "aweme_id": "7001",
                "share_url": "https://www.douyin.com/video/7001",
                "desc": None,
                "text_extra": [],
                "statistics": {
                    "digg_count": None,
                    "comment_count": None,
                    "collect_count": None,
                    "share_count": None,
                },
            }

    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        session_factory=PathOnlyBrowser,
    )

    assert result.aweme_items == []
    assert result.diagnostic_code is None


def test_collect_post_page_candidate_cap_still_finishes_the_first_candidate_once():
    """Stopping before the accepted candidate finishes must make this test fail."""
    from collectors._douyin_browser_transport import collect_post_page

    class BodyCountingBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(
                events=[
                    _response_event("first"),
                    _response_event("ignored"),
                    _loading_event("Network.loadingFinished", "first"),
                    _loading_event("Network.loadingFinished", "ignored"),
                ],
                bodies={
                    "first": json.dumps(
                        {
                            "aweme_detail": {
                                **AWEME,
                                "share_url": "https://www.douyin.com/video/7001",
                            }
                        }
                    ),
                    "ignored": json.dumps(
                        {"aweme_detail": {**AWEME, "aweme_id": "9999"}}
                    ),
                },
            )
            self.body_reads = []

        def get_response_body(self, request_id):
            self.body_reads.append(request_id)
            return super().get_response_body(request_id)

        def evaluate(self, _expression):
            return None

    browser = BodyCountingBrowser()
    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        max_candidates=1,
        session_factory=lambda: browser,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert browser.body_reads == ["first"]
    assert result.diagnostics["candidate_response_count"] == 1


def test_collect_post_page_attempts_each_response_body_at_most_once():
    """Retrying or surfacing a transient body read must make this test fail."""
    from collectors._douyin_browser_transport import collect_post_page

    class OneShotBodyBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(
                events=[
                    _response_event("broken"),
                    _loading_event("Network.loadingFinished", "broken"),
                    None,
                ],
                body_errors={"broken": RuntimeError("signed body must not escape")},
            )
            self.body_reads = 0

        def get_response_body(self, request_id, timeout=None):
            del timeout
            self.body_reads += 1
            return super().get_response_body(request_id)

        def evaluate(self, _expression):
            return None

    browser = OneShotBodyBrowser()
    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        session_factory=lambda: browser,
    )

    assert result.aweme_items == []
    assert result.diagnostic_code is None
    assert browser.body_reads == 1
    assert "signed body" not in json.dumps(result.diagnostics)


def test_collect_post_page_never_reads_a_response_body_after_deadline():
    """A loading event cannot extend the hard deadline into a body read."""
    from collectors._douyin_browser_transport import collect_post_page

    class DeadlineBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(
                events=[
                    _response_event("late"),
                    _loading_event("Network.loadingFinished", "late"),
                ],
                bodies={
                    "late": json.dumps(
                        {
                            "aweme_detail": {
                                **AWEME,
                                "share_url": "https://www.douyin.com/video/7001",
                            }
                        }
                    )
                },
            )
            self.body_reads = 0

        def get_response_body(self, request_id, timeout=None):
            del timeout
            self.body_reads += 1
            return super().get_response_body(request_id)

    browser = DeadlineBrowser()
    clock_state = {"reads": 0}

    def clock():
        clock_state["reads"] += 1
        return 2.0 if clock_state["reads"] >= 7 else 0.0

    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        max_seconds=1.0,
        session_factory=lambda: browser,
        monotonic=clock,
    )

    assert browser.body_reads == 0
    assert result.aweme_items == []
    assert result.diagnostics["stop_condition"] == "timeout"


def test_collect_post_page_never_parses_a_body_past_the_character_budget():
    """Removing the body-size gate must make this test fail."""
    from collectors._douyin_browser_transport import collect_post_page

    body = json.dumps(
        {
            "aweme_detail": {
                **AWEME,
                "share_url": "https://www.douyin.com/video/7001",
            }
        }
    )

    class NoDomBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return None

    browser = NoDomBrowser(
        events=[
            _response_event("oversized"),
            _loading_event("Network.loadingFinished", "oversized"),
        ],
        bodies={"oversized": body},
    )
    result = collect_post_page(
        "https://www.douyin.com/video/7001",
        max_body_chars=len(body) - 1,
        session_factory=lambda: browser,
    )

    assert result.aweme_items == []
    assert result.diagnostic_code is None


def test_extract_aweme_items_deduplicates_nested_lists():
    from collectors._douyin_browser_transport import extract_aweme_items

    data = {"data": {"aweme_list": [AWEME, dict(AWEME)]}}
    assert [item["aweme_id"] for item in extract_aweme_items(data)] == ["7001"]


def test_page_observation_accepts_metadata_only_from_post_list_owner():
    from collectors._douyin_browser_transport import extract_post_page_observations

    payload = {
        "data": {
            "aweme_list": [AWEME],
            "has_more": False,
            "max_cursor": "secret-cursor",
        }
    }

    pages = extract_post_page_observations(payload)

    assert [item["aweme_id"] for item in pages[0].items] == ["7001"]
    assert pages[0].has_more is False
    assert pages[0].cursor == "secret-cursor"
    assert extract_post_page_observations({"feed": {"has_more": False}}) == []


def test_page_observation_merges_duplicate_items_without_persisting_cursor():
    from collectors._douyin_browser_transport import (
        collect_account_page,
        extract_post_page_observations,
    )

    listed = dict(ACCOUNT_AWEME, desc="列表文案", video={})
    enriched = dict(
        ACCOUNT_AWEME, desc="不同文案", video={"duration": 9000}
    )
    generic_payload = {
        "first": {"aweme_list": [listed], "has_more": True, "cursor": "alpha"},
        "second": {
            "post_list": [enriched],
            "has_more": False,
            "max_cursor": "secret-cursor",
        },
    }

    pages = extract_post_page_observations(generic_payload)
    assert len(pages) == 2
    assert pages[1].items[0]["video"] == {"duration": 9000}

    account_payload = {
        "aweme_list": [listed],
        "has_more": True,
        "cursor": "alpha",
        "data": {
            "post_list": [enriched],
            "has_more": False,
            "max_cursor": "secret-cursor",
        },
    }
    browser = FakeBrowser(
        events=[_response_event("r1")],
        bodies={"r1": json.dumps(account_payload)},
    )
    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1
    assert "cursor" not in result.coverage
    assert "secret-cursor" not in json.dumps(result.coverage)


def test_extract_aweme_items_rejects_id_only_objects():
    """An aweme-like identifier without credible post fields is unrelated JSON."""
    from collectors._douyin_browser_transport import extract_aweme_items

    data = {"data": {"aweme_list": [{"aweme_id": "7001", "cursor": 1}]}}

    assert extract_aweme_items(data) == []


def test_extract_aweme_items_merges_detail_into_only_missing_fields():
    """A later detail response enriches gaps without replacing reliable values."""
    from collectors._douyin_browser_transport import extract_aweme_items

    listed = {
        "aweme_id": "7001",
        "desc": "列表文案",
        "statistics": {"digg_count": 12, "comment_count": None},
    }
    detailed = {
        "aweme_id": "7001",
        "desc": "详情页不同文案",
        "statistics": {"digg_count": 999, "comment_count": 5},
        "video": {"duration": 9000},
    }

    result = extract_aweme_items({
        "aweme_list": [listed],
        "aweme_detail": detailed,
    })

    assert result[0]["desc"] == "列表文案"
    assert result[0]["statistics"] == {"digg_count": 12, "comment_count": 5}
    assert result[0]["video"] == {"duration": 9000}


def test_extract_dom_items_only_keeps_post_links():
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://www.douyin.com/video/7002?x=1", "text": "作品二"},
        {"href": "https://www.douyin.com/search?q=x", "text": "搜索"},
    ]
    result = extract_dom_items(cards)
    assert result[0]["aweme_id"] == "7002"
    assert result[0]["statistics"] == {}
    assert result[0]["_collection_source"] == "dom"


def test_extract_dom_items_requires_exact_post_path():
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://www.douyin.com/video/7002/extra", "text": "无效"},
        {"href": "https://www.douyin.com/note/7003?x=1#part", "text": "有效"},
    ]

    result = extract_dom_items(cards)

    assert [item["aweme_id"] for item in result] == ["7003"]
    assert result[0]["share_url"] == "https://www.douyin.com/note/7003"


def test_extract_dom_items_rejects_non_https_and_non_douyin_hosts():
    """Visible-card evidence must still be an allowlisted public Douyin URL."""
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://evil.example/video/7001", "text": "伪造"},
        {"href": "http://www.douyin.com/video/7002", "text": "非 HTTPS"},
        {"href": "https://www.iesdouyin.com/note/7003?token=x", "text": "有效"},
    ]

    result = extract_dom_items(cards)

    assert [item["aweme_id"] for item in result] == ["7003"]
    assert result[0]["share_url"] == "https://www.douyin.com/note/7003"


def test_extract_dom_items_keeps_only_explicit_visible_metrics_and_pin():
    """DOM fallback maps labeled public values and leaves unknowns absent."""
    from collectors._douyin_browser_transport import extract_dom_items

    result = extract_dom_items([
        {
            "href": "https://www.douyin.com/video/7002",
            "text": "作品二",
            "is_pinned": True,
            "statistics": {"digg_count": "1.2万", "comment_count": None},
        },
        {
            "href": "https://www.douyin.com/video/7003",
            "text": "作品三",
        },
    ])

    assert result[0]["is_top"] is True
    assert result[0]["statistics"] == {"digg_count": "1.2万"}
    assert result[1]["is_top"] is None
    assert result[1]["statistics"] == {}


def test_dom_labeled_metric_text_maps_without_inference():
    """A visible label is stripped to its displayed number, not guessed as zero."""
    from collectors._douyin_browser_transport import extract_dom_items
    from collectors.douyin import DouyinCollector

    item = extract_dom_items([{
        "href": "https://www.douyin.com/video/7002",
        "text": "作品二",
        "statistics": {
            "digg_count": "点赞 1.2万",
            "comment_count": "评论 3",
        },
    }])[0]
    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, item, source="dom")
    )

    assert post["likes"] == 12_000
    assert post["comments"] == 3


def test_dom_expression_requests_only_visible_pin_and_metric_fields():
    from collectors._douyin_browser_transport import _DOM_CARDS_EXPRESSION

    assert "is_pinned" in _DOM_CARDS_EXPRESSION
    assert "statistics" in _DOM_CARDS_EXPRESSION
    assert "digg_count" in _DOM_CARDS_EXPRESSION
    assert "comment_count" in _DOM_CARDS_EXPRESSION
    assert (
        "document.querySelectorAll('[data-e2e=\"user-post-item\"]')"
        in _DOM_CARDS_EXPRESSION
    )
    assert "document.querySelectorAll('a[href" not in _DOM_CARDS_EXPRESSION
    assert "a.parentElement" not in _DOM_CARDS_EXPRESSION
    assert "[data-e2e=\"user-post-item\"],li" not in _DOM_CARDS_EXPRESSION


def test_restriction_priority_and_url_sanitization():
    from collectors._douyin_browser_transport import (
        detect_restriction,
        sanitize_response_url,
    )

    assert detect_restriction("请先登录并完成滑动验证") == STOP_VERIFICATION
    assert detect_restriction("登录后查看") == STOP_LOGIN
    assert sanitize_response_url("https://www.douyin.com/aweme/post/?secret=1#x") == (
        "https://www.douyin.com/aweme/post/"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("账号不存在，请先登录并完成滑动验证", STOP_VERIFICATION),
        ("访问过于频繁，请先登录", STOP_LOGIN),
        ("请求频率过高，账号不存在", STOP_ACCESS_RESTRICTED),
        ("该账号已注销，暂无作品", STOP_ACCOUNT_UNAVAILABLE),
        ("该账号还没有发布公开作品", STOP_NO_PUBLIC_CONTENT),
    ],
)
def test_restriction_and_empty_state_priority_is_shared(text, expected):
    """Visible page states use the approved priority before parser fallback."""
    from collectors._douyin_browser_transport import detect_restriction
    from collectors.douyin import _detect_restriction

    assert detect_restriction(text) == expected
    assert _detect_restriction(text) == expected


def test_sanitize_response_url_removes_userinfo_and_handles_ports():
    from collectors._douyin_browser_transport import sanitize_response_url

    assert sanitize_response_url(
        "https://name:password@www.douyin.com:8443/aweme/post/?secret=1#x"
    ) == "https://www.douyin.com:8443/aweme/post/"
    assert sanitize_response_url(
        "https://name:password@[2001:db8::1]:8443/aweme/post/?secret=1"
    ) == "https://[2001:db8::1]:8443/aweme/post/"
    assert sanitize_response_url(
        "https://name:password@www.douyin.com:not-a-port/aweme/post/?secret=1"
    ) == "https://www.douyin.com/aweme/post/"


def test_collect_account_page_keeps_allowed_network_items_and_safe_paths():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[RESPONSE_EVENT],
        bodies={"r1": json.dumps({"aweme_list": [ACCOUNT_AWEME]})},
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example?secret=1",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.aweme_items[0]["_collection_source"] == "network"
    assert result.source == "network"
    assert result.diagnostics["response_paths"] == [
        "https://www.douyin.com/aweme/v1/web/aweme/post/"
    ]
    assert result.diagnostics["candidate_response_count"] == 1


def test_collect_account_page_returns_restriction_with_retained_items():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[RESPONSE_EVENT, None],
        bodies={"r1": json.dumps({"aweme_list": [ACCOUNT_AWEME]})},
        page_texts=["", "请完成滑动验证"],
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=2,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.restriction == STOP_VERIFICATION
    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.aweme_items[0]["_collection_source"] == "network"
    assert result.diagnostics["stop_condition"] == STOP_VERIFICATION


@pytest.mark.parametrize(
    ("visible_text", "expected_reason", "expected_marker"),
    [
        ("扫码登录", STOP_LOGIN, "LOGIN_WALL_VISIBLE"),
        ("请完成滑动验证", STOP_VERIFICATION, "VERIFICATION_CHALLENGE_VISIBLE"),
        ("访问过于频繁", STOP_ACCESS_RESTRICTED, "ACCESS_RESTRICTION_VISIBLE"),
        ("该账号已注销", STOP_ACCOUNT_UNAVAILABLE, "ACCOUNT_UNAVAILABLE_VISIBLE"),
        ("暂无公开作品", STOP_NO_PUBLIC_CONTENT, "NO_PUBLIC_CONTENT_VISIBLE"),
    ],
)
def test_collect_account_page_records_safe_visible_restriction_audit(
    visible_text, expected_reason, expected_marker
):
    """A visible platform state is persisted as fixed enums, never page text."""
    from collectors._douyin_browser_transport import collect_account_page

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: FakeBrowser(page_texts=[visible_text]),
        sleep=lambda _seconds: None,
    )

    assert result.restriction == expected_reason
    assert result.coverage["restriction_source"] == "browser_visible_text"
    assert result.coverage["restriction_marker"] == expected_marker
    assert visible_text not in json.dumps(result.coverage, ensure_ascii=False)


def test_restriction_retains_visible_profile_header_but_ignores_dom_cards():
    """Reading the already-visible account header must not bypass a login stop."""
    from collectors._douyin_browser_transport import collect_account_page

    class RestrictedProfileBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return {
                "cards": [
                    {
                        "href": "https://www.douyin.com/video/7999",
                        "text": "不得在限制后接纳的作品",
                    }
                ],
                "profile": {
                    "profile_url": ACCOUNT_URL,
                    "sec_uid": "example",
                    "nickname": "公开昵称",
                    "dom_verified_badge": "搞笑短视频创作者",
                },
            }

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: RestrictedProfileBrowser(
            page_texts=["登录后查看"]
        ),
        sleep=lambda _seconds: None,
    )

    assert result.restriction == STOP_LOGIN
    assert result.aweme_items == []
    assert result.profile_raw["account_name"] == "公开昵称"
    assert result.profile_raw["verified"] == "搞笑短视频创作者"


def test_restriction_uses_profile_only_dom_snapshot_contract():
    """The restricted path consumes only one raw profile-header snapshot."""
    from collectors._douyin_browser_transport import collect_account_page

    class ProfileOnlyBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return {
                "profile_url": ACCOUNT_URL,
                "sec_uid": "example",
                "nickname": "公开昵称",
                "verified": True,
            }

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: ProfileOnlyBrowser(page_texts=["登录后查看"]),
        sleep=lambda _seconds: None,
    )

    assert result.restriction == STOP_LOGIN
    assert result.aweme_items == []
    assert result.profile_raw["account_name"] == "公开昵称"
    assert result.profile_raw["verified"] is True


def test_restricted_dom_expression_is_scoped_profile_only():
    """Restricted reads may inspect badges, never body text or post cards."""
    from collectors._douyin_browser_transport import _DOM_PROFILE_EXPRESSION

    assert 'profileRoot.querySelectorAll(badgeSelector)' in _DOM_PROFILE_EXPRESSION
    assert 'img[alt*="认证"]' in _DOM_PROFILE_EXPRESSION
    assert '[aria-label*="认证"]' in _DOM_PROFILE_EXPRESSION
    assert '[title*="认证"]' in _DOM_PROFILE_EXPRESSION
    assert "dom_verified_badge" in _DOM_PROFILE_EXPRESSION
    assert "document.body" not in _DOM_PROFILE_EXPRESSION
    assert 'a[href*="/video/"]' not in _DOM_PROFILE_EXPRESSION
    assert 'a[href*="/note/"]' not in _DOM_PROFILE_EXPRESSION
    assert "const cards" not in _DOM_PROFILE_EXPRESSION


def test_restriction_remains_authoritative_when_profile_snapshot_fails():
    """Best-effort header evidence cannot replace an already observed stop."""
    from collectors._douyin_browser_transport import collect_account_page

    class BrokenProfileBrowser(FakeBrowser):
        def evaluate(self, _expression):
            raise RuntimeError("private browser detail must not escape")

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: BrokenProfileBrowser(page_texts=["登录后查看"]),
        sleep=lambda _seconds: None,
    )

    assert result.restriction == STOP_LOGIN
    assert result.profile_raw is None
    assert result.aweme_items == []


@pytest.mark.parametrize(
    ("visible_text", "expected"),
    [
        ("登录后查看", STOP_LOGIN),
        ("请完成滑动验证", STOP_VERIFICATION),
        ("访问过于频繁", STOP_ACCESS_RESTRICTED),
    ],
)
def test_terminal_page_cannot_bypass_visible_restriction(visible_text, expected):
    from collectors._douyin_browser_transport import collect_account_page

    terminal_payload = {
        "data": {
            "aweme_list": [ACCOUNT_AWEME],
            "has_more": False,
            "max_cursor": "must-not-persist",
        }
    }
    browser = FakeBrowser(
        events=[
            _response_event("terminal"),
            _loading_event("Network.loadingFinished", "terminal"),
        ],
        bodies={"terminal": json.dumps(terminal_payload)},
        page_texts=["", visible_text],
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.restriction == expected
    assert result.coverage["is_exhaustive"] is False
    assert result.coverage["stop_condition"] == expected


def test_collect_account_page_uses_dom_cards_when_network_is_empty():
    from collectors._douyin_browser_transport import collect_account_page

    class BoundDomBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return {
                "cards": [{
                    "href": (
                        "https://www.douyin.com/video/7002?token=secret"
                    ),
                    "text": "作品二",
                }],
                "profile": {
                    "profile_url": ACCOUNT_URL,
                    "sec_uid": "example",
                },
            }

    browser = BoundDomBrowser()

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.source == "dom"
    assert result.aweme_items[0]["aweme_id"] == "7002"
    assert result.aweme_items[0]["share_url"] == "https://www.douyin.com/video/7002"


@pytest.mark.parametrize(
    "snapshot",
    [
        [
            {
                "href": "https://www.douyin.com/video/7002",
                "text": "legacy list-only card",
            }
        ],
        {
            "cards": [{
                "href": "https://www.douyin.com/video/7002",
                "text": "missing profile card",
            }]
        },
        {
            "cards": [{
                "href": "https://www.douyin.com/video/7002",
                "text": "missing sec_uid card",
            }],
            "profile": {"profile_url": ACCOUNT_URL},
        },
        {
            "cards": [{
                "href": "https://www.douyin.com/video/7002",
                "text": "foreign profile card",
            }],
            "profile": {
                "profile_url": "https://www.douyin.com/user/foreign-account",
                "sec_uid": "foreign-account",
            },
        },
    ],
    ids=[
        "legacy-list-only",
        "missing-profile",
        "missing-profile-sec-uid",
        "foreign-profile",
    ],
)
def test_account_page_ignores_dom_cards_without_same_snapshot_binding(snapshot):
    """DOM cards need an exact profile.sec_uid in the same snapshot."""
    from collectors._douyin_browser_transport import collect_account_page

    class SnapshotBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return snapshot

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        max_scrolls=1,
        session_factory=lambda: SnapshotBrowser(),
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.profile_raw is None
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False


def test_bound_dom_empty_snapshot_cannot_prove_terminal_or_exhaustive():
    """An account-bound visible empty card set is not a pagination terminal."""
    from collectors._douyin_browser_transport import collect_account_page

    class EmptyBoundSnapshotBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return {
                "cards": [],
                "profile": {
                    "profile_url": ACCOUNT_URL,
                    "sec_uid": "example",
                },
            }

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: EmptyBoundSnapshotBrowser(),
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False


def test_collect_account_page_continues_after_response_body_is_unavailable():
    from collectors._douyin_browser_transport import collect_account_page
    from collectors.browser_backend import BrowserError

    later_event = {
        "method": "Network.responseReceived",
        "params": {
            "requestId": "r2",
            "type": "Fetch",
            "response": {
                "url": "https://www.iesdouyin.com/aweme/v1/web/aweme/post/?signed=later",
                "mimeType": "application/json",
                "status": 200,
            },
        },
    }
    browser = FakeBrowser(
        events=[RESPONSE_EVENT, later_event],
        bodies={"r2": json.dumps({"aweme_list": [ACCOUNT_AWEME]})},
        body_errors={"r1": BrowserError("response body is no longer available")},
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.aweme_items[0]["_collection_source"] == "network"
    assert result.diagnostics["response_paths"] == [
        "https://www.douyin.com/aweme/v1/web/aweme/post/",
        "https://www.iesdouyin.com/aweme/v1/web/aweme/post/"
    ]
    assert result.diagnostics["candidate_response_count"] == 2


def _bound_post_response(request_id):
    return _response_event(
        request_id,
        url=(
            "https://www.douyin.com/aweme/v1/web/aweme/post/"
            "?sec_uid=example&signed=secret"
        ),
    )


def _terminal_account_body(post_id="7002"):
    item = {
        **ACCOUNT_AWEME,
        "aweme_id": post_id,
        "desc": f"末页作品 {post_id}",
    }
    return json.dumps({"aweme_list": [item], "has_more": False})


def test_terminal_page_drains_earlier_readable_bound_body_before_exhaustive():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={
            "r1": json.dumps({"aweme_list": [ACCOUNT_AWEME], "has_more": True}),
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {"7001", "7002"}
    assert result.coverage["observed_page_count"] == 2
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is True
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 0


def test_terminal_page_quiet_drains_candidate_registered_after_terminal():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
            None,
        ],
        bodies={
            "r1": json.dumps({"aweme_list": [ACCOUNT_AWEME], "has_more": True}),
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {"7001", "7002"}
    assert result.coverage["observed_page_count"] == 2
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is True
    assert result.diagnostics["candidate_response_count"] == 2
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 0
    assert browser.events == []
    assert browser.scrolls == []


def test_terminal_page_quiet_drain_records_late_candidate_failure():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
            _bound_post_response("r1"),
            _loading_event("Network.loadingFailed", "r1"),
            None,
        ],
        bodies={"r2": _terminal_account_body()},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7002"]
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["candidate_response_count"] == 2
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 1
    assert browser.events == []
    assert browser.scrolls == []


def test_terminal_quiet_drain_cannot_overwrite_late_repeated_cursor():
    from collectors._douyin_browser_transport import collect_account_page

    late = {
        **ACCOUNT_AWEME,
        "aweme_id": "7003",
        "desc": "静默排空时出现的重复游标页",
    }
    browser = FakeBrowser(
        events=[
            _bound_post_response("r0"),
            _loading_event("Network.loadingFinished", "r0"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
            None,
        ],
        bodies={
            "r0": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME],
                    "has_more": True,
                    "max_cursor": "repeat-me",
                }
            ),
            "r1": json.dumps(
                {
                    "aweme_list": [late],
                    "has_more": True,
                    "max_cursor": "repeat-me",
                }
            ),
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {
        "7001",
        "7002",
        "7003",
    }
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["repeated_cursor_count"] == 1
    assert result.coverage["stop_condition"] == "repeated_cursor"
    assert result.coverage["is_exhaustive"] is False


def test_terminal_quiet_boundary_is_rechecked_after_page_text_cdp_events():
    from collectors._douyin_browser_transport import collect_account_page

    class InjectDuringPageTextBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(
                events=[
                    _bound_post_response("r2"),
                    _loading_event("Network.loadingFinished", "r2"),
                    None,
                ],
                bodies={
                    "r1": json.dumps(
                        {"aweme_list": [ACCOUNT_AWEME], "has_more": True}
                    ),
                    "r2": _terminal_account_body(),
                },
            )
            self.page_text_calls = 0

        def page_text(self):
            self.page_text_calls += 1
            if self.page_text_calls == 3:
                self.events.extend(
                    [
                        _bound_post_response("r1"),
                        _loading_event("Network.loadingFinished", "r1"),
                        None,
                    ]
                )
            return super().page_text()

    browser = InjectDuringPageTextBrowser()
    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {"7001", "7002"}
    assert result.coverage["is_exhaustive"] is True
    assert result.diagnostics["candidate_response_count"] == 2
    assert browser.events == []


@pytest.mark.parametrize(
    "invalid_item",
    [
        {"aweme_id": "7002", "author": {"sec_uid": "example"}},
        "not-an-object",
        {
            "aweme_id": "invalid-id",
            "author": {"sec_uid": "example"},
            "desc": "ID 非法",
        },
    ],
    ids=["sparse", "non-object", "invalid-id"],
)
def test_terminal_page_rejects_mixed_invalid_raw_items(invalid_item):
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={
            "r1": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME, invalid_item],
                    "has_more": False,
                }
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


@pytest.mark.parametrize(
    "conflicting_item",
    [
        {
            **ACCOUNT_AWEME,
            "aweme_id": "7002",
            "aweme_id_str": "7999",
        },
        {
            **ACCOUNT_AWEME,
            "aweme_id": "7002",
            "share_url": "https://www.douyin.com/video/7999?source=test",
        },
        {
            **ACCOUNT_AWEME,
            "aweme_id": "7002",
            "share_url": "https://www.douyin.com/video/7999/",
        },
    ],
    ids=[
        "id-alias-conflict",
        "public-url-id-conflict",
        "trailing-slash-public-url-id-conflict",
    ],
)
def test_terminal_page_rejects_conflicting_raw_item_identity(conflicting_item):
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={
            "r1": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME, conflicting_item],
                    "has_more": False,
                }
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


def test_terminal_page_accepts_consistent_raw_item_identity_aliases():
    from collectors._douyin_browser_transport import collect_account_page

    item = {
        **ACCOUNT_AWEME,
        "aweme_id": "7002",
        "aweme_id_str": "7002",
        "share_url": "https://www.douyin.com/note/7002?source=test",
    }
    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={
            "r1": json.dumps(
                {"aweme_list": [item], "has_more": False}
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7002"]
    assert result.coverage["is_exhaustive"] is True
    assert result.diagnostics["failed_account_post_count"] == 0


def test_terminal_page_rejects_invalid_sibling_frozen_owner():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={
            "r1": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME],
                    "has_more": False,
                    "max_cursor": "root-terminal",
                    "data": {
                        "aweme_list": [
                            {
                                **ACCOUNT_AWEME,
                                "aweme_id": "7002",
                                "author": {},
                            }
                        ],
                        "has_more": True,
                        "max_cursor": "invalid-sibling",
                    },
                }
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


def test_consistent_duplicate_owners_commit_one_logical_page():
    from collectors._douyin_browser_transport import collect_account_page

    enriched = {
        **ACCOUNT_AWEME,
        "desc": "同页补充字段",
        "video": {"duration": 9000},
    }
    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={
            "r1": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME],
                    "has_more": True,
                    "max_cursor": "same-page",
                    "data": {
                        "post_list": [enriched],
                        "has_more": True,
                        "cursor": "same-page",
                    },
                }
            ),
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {"7001", "7002"}
    assert result.coverage["observed_page_count"] == 2
    assert result.coverage["repeated_cursor_count"] == 0
    assert result.coverage["is_exhaustive"] is True


def test_terminal_page_rejects_conflicting_cursor_aliases_in_one_owner():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={
            "r1": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME],
                    "has_more": False,
                    "max_cursor": "first",
                    "cursor": "second",
                }
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


@pytest.mark.parametrize(
    ("root_has_more", "root_cursor", "data_has_more", "data_cursor"),
    [
        (False, "same", True, "same"),
        (False, "first", False, "second"),
    ],
    ids=["has-more-conflict", "cursor-conflict"],
)
def test_conflicting_observations_in_one_candidate_do_not_prove_terminal(
    root_has_more,
    root_cursor,
    data_has_more,
    data_cursor,
):
    from collectors._douyin_browser_transport import collect_account_page

    second = {
        **ACCOUNT_AWEME,
        "aweme_id": "7002",
        "desc": "同一响应的第二个冻结 owner",
    }
    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={
            "r1": json.dumps(
                {
                    "aweme_list": [ACCOUNT_AWEME],
                    "has_more": root_has_more,
                    "max_cursor": root_cursor,
                    "data": {
                        "aweme_list": [second],
                        "has_more": data_has_more,
                        "max_cursor": data_cursor,
                    },
                }
            )
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {"7001", "7002"}
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


def test_terminal_page_is_not_exhaustive_with_earlier_unresolved_bound_body():
    from collectors._douyin_browser_transport import collect_account_page
    from collectors.browser_backend import BrowserError

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={"r2": _terminal_account_body()},
        body_errors={"r1": BrowserError("body is not ready")},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7002"]
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["unresolved_account_post_count"] == 1
    assert result.diagnostics["failed_account_post_count"] == 0


def test_terminal_page_is_not_exhaustive_after_bound_loading_failed():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFailed", "r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={"r2": _terminal_account_body()},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 1


def test_terminal_page_is_not_exhaustive_after_bound_invalid_json():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={
            "r1": "{not-json",
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 1


def test_terminal_page_is_not_exhaustive_after_bound_invalid_schema():
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={
            "r1": "{}",
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 1


@pytest.mark.parametrize(
    "invalid_url",
    [
        (
            "https://www.douyin.com/aweme/v1/web/aweme/post/"
            "?sec_uid=example&sec_uid=example"
        ),
        (
            "https://www.douyin.com/aweme/v1/web/aweme/post/"
            "?sec_uid=%FF"
        ),
        "https://www.douyin.com/aweme/v1/web/aweme/post/?sec_uid=",
        "https://www.douyin.com/aweme/v1/web/aweme/post/?sec_uid=%20%20",
        "https://www.douyin.com/aweme/v1/web/aweme/post/?sec_uid=%0A",
    ],
    ids=[
        "duplicate-binding",
        "invalid-percent-encoding",
        "empty-binding",
        "whitespace-binding",
        "control-binding",
    ],
)
def test_terminal_page_is_not_exhaustive_after_ambiguous_binding(invalid_url):
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _response_event("r1", url=invalid_url),
            _loading_event("Network.loadingFinished", "r1"),
            _bound_post_response("r2"),
            _loading_event("Network.loadingFinished", "r2"),
        ],
        bodies={
            "r1": json.dumps({"aweme_list": [ACCOUNT_AWEME], "has_more": True}),
            "r2": _terminal_account_body(),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7002"]
    assert result.coverage["terminal_page_observed"] is True
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["unresolved_account_post_count"] == 0
    assert result.diagnostics["failed_account_post_count"] == 1


@pytest.mark.parametrize(
    "status",
    [401, 403, 429, 500, 206, None, "200", True],
    ids=[
        "unauthorized",
        "forbidden",
        "rate-limited",
        "server-error",
        "partial-content",
        "missing",
        "string",
        "boolean",
    ],
)
def test_terminal_page_rejects_non_success_http_status(status):
    from collectors._douyin_browser_transport import collect_account_page

    event = _bound_post_response("r1")
    if status is None:
        event["params"]["response"].pop("status")
    else:
        event["params"]["response"]["status"] = status
    browser = FakeBrowser(
        events=[
            event,
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={"r1": _terminal_account_body()},
    )
    body_calls = []
    original_get_body = browser.get_response_body
    browser.get_response_body = lambda request_id: (
        body_calls.append(request_id) or original_get_body(request_id)
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1
    assert body_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status_code", 1),
        ("status_code", -1),
        ("status_code", True),
        ("status_code", "0"),
        ("error_code", 1),
    ],
    ids=[
        "status-nonzero",
        "status-negative",
        "status-boolean",
        "status-string",
        "error-nonzero",
    ],
)
def test_terminal_page_rejects_api_error_status(field, value):
    from collectors._douyin_browser_transport import collect_account_page

    body = json.loads(_terminal_account_body())
    body[field] = value
    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={"r1": json.dumps(body)},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.aweme_items == []
    assert result.coverage["terminal_page_observed"] is False
    assert result.coverage["is_exhaustive"] is False
    assert result.diagnostics["failed_account_post_count"] == 1


def test_terminal_page_accepts_exact_zero_api_status():
    from collectors._douyin_browser_transport import collect_account_page

    body = json.loads(_terminal_account_body())
    body.update({"status_code": 0, "error_code": 0})
    browser = FakeBrowser(
        events=[
            _bound_post_response("r1"),
            _loading_event("Network.loadingFinished", "r1"),
        ],
        bodies={"r1": json.dumps(body)},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7002"]
    assert result.coverage["is_exhaustive"] is True
    assert result.diagnostics["failed_account_post_count"] == 0


def test_collect_account_page_counts_duplicate_path_candidates_independently():
    """Each eligible response is counted even when safe paths de-duplicate."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(events=[
        _response_event("r1"),
        _loading_event("Network.loadingFailed", "r1"),
        _response_event("r2"),
        _loading_event("Network.loadingFailed", "r2"),
    ])

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.diagnostics["candidate_response_count"] == 2
    assert result.diagnostics["response_paths"] == [
        "https://www.douyin.com/aweme/v1/web/aweme/post/"
    ]


def test_collect_account_page_reads_body_only_after_loading_finished():
    """A response header registers a candidate; body retrieval waits for completion."""
    from collectors._douyin_browser_transport import collect_account_page
    from collectors.browser_backend import BrowserError

    class CompletionBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(
                events=[
                    _response_event("r1"),
                    _loading_event("Network.loadingFinished", "r1"),
                ],
                bodies={
                    "r1": json.dumps(
                        {"aweme_list": [ACCOUNT_AWEME]}
                    )
                },
            )
            self.finished = set()
            self.body_calls = []

        def poll_event(self, timeout):
            event = super().poll_event(timeout)
            if event and event["method"] == "Network.loadingFinished":
                self.finished.add(event["params"]["requestId"])
            return event

        def get_response_body(self, request_id):
            self.body_calls.append(request_id)
            if request_id not in self.finished:
                raise BrowserError("body not ready")
            return super().get_response_body(request_id)

    browser = CompletionBrowser()

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert browser.body_calls == ["r1"]


def test_collect_account_page_drops_candidates_on_loading_failed():
    """Failed requests never trigger response-body reads."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(events=[
        _response_event("r1"),
        _loading_event("Network.loadingFailed", "r1"),
    ])
    body_calls = []
    browser.get_response_body = lambda request_id: body_calls.append(request_id) or "{}"

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.aweme_items == []
    assert body_calls == []


def test_collect_account_page_retries_pending_body_for_header_only_fake():
    """A bounded compatibility path supports fakes that omit lifecycle events."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[_response_event("r1")],
        bodies={"r1": json.dumps({"aweme_list": [ACCOUNT_AWEME]})},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]


def test_collect_account_page_resets_idle_after_a_productive_round():
    """Three non-consecutive idle rounds do not stop collection early."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            None,
            None,
            _response_event("r1"),
            _loading_event("Network.loadingFinished", "r1"),
            None,
            None,
            None,
            None,
        ],
        bodies={"r1": json.dumps({"aweme_list": [ACCOUNT_AWEME]})},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=2,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.diagnostics["scroll_rounds"] >= 5


def test_collect_account_page_never_scrolls_more_than_twenty(monkeypatch):
    """The configured scroll cap has no <= off-by-one."""
    from collectors import _douyin_browser_transport as transport

    monkeypatch.setattr(transport, "MAX_IDLE_ROUNDS", 999)
    browser = FakeBrowser(events=[None] * 25)

    result = transport.collect_account_page(
        ACCOUNT_URL,
        limit=100,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.diagnostics["scroll_rounds"] == 20
    assert len(browser.scrolls) == 20
    assert result.coverage["browser_fallback_requested"] is True
    assert result.coverage["browser_fallback_launched"] is True
    assert result.coverage["browser_evidence_source"] == "none"
    assert result.coverage["scroll_rounds"] == 20
    assert result.coverage["max_seconds"] == 90.0
    assert result.coverage["max_scrolls"] == 20


def test_collect_account_page_skips_dom_after_deadline():
    """The 90-second budget is a hard boundary, including final DOM fallback."""
    from collectors._douyin_browser_transport import collect_account_page

    class DeadlineBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(cards=[{
                "href": "https://www.douyin.com/video/7002",
                "text": "must not be read",
            }])
            self.evaluations = []

        def evaluate(self, expression):
            self.evaluations.append(expression)
            return super().evaluate(expression)

    ticks = iter([0.0, 91.0, 92.0, 93.0])
    browser = DeadlineBrowser()

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        monotonic=lambda: next(ticks),
        sleep=lambda _: None,
    )

    assert result.aweme_items == []
    assert browser.evaluations == []
    assert result.diagnostics["stop_condition"] == "timeout"


def test_terminal_page_timeout_after_response_decode_is_not_exhaustive():
    from collectors._douyin_browser_transport import collect_account_page

    state = {"decoded": False}

    class DecodeExpiryBrowser(FakeBrowser):
        def get_response_body(self, request_id):
            body = super().get_response_body(request_id)
            state["decoded"] = True
            return body

    browser = DecodeExpiryBrowser(
        events=[
            _response_event("terminal"),
            _loading_event("Network.loadingFinished", "terminal"),
        ],
        bodies={
            "terminal": json.dumps({
                "aweme_list": [ACCOUNT_AWEME],
                "has_more": False,
            })
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_seconds=1.0,
        session_factory=lambda: browser,
        monotonic=lambda: 2.0 if state["decoded"] else 0.0,
        sleep=lambda _: None,
    )

    assert result.diagnostics["stop_condition"] == "timeout"
    assert result.coverage["stop_condition"] == "timeout"
    assert result.coverage["is_exhaustive"] is False


def test_terminal_page_timeout_during_page_text_is_not_exhaustive():
    from collectors._douyin_browser_transport import collect_account_page

    state = {"decoded": False, "expired": False}

    class PageTextExpiryBrowser(FakeBrowser):
        def get_response_body(self, request_id):
            body = super().get_response_body(request_id)
            state["decoded"] = True
            return body

        def page_text(self):
            text = super().page_text()
            if state["decoded"]:
                state["expired"] = True
            return text

    browser = PageTextExpiryBrowser(
        events=[
            _response_event("terminal"),
            _loading_event("Network.loadingFinished", "terminal"),
        ],
        bodies={
            "terminal": json.dumps({
                "aweme_list": [ACCOUNT_AWEME],
                "has_more": False,
            })
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        all_posts=True,
        max_seconds=1.0,
        session_factory=lambda: browser,
        monotonic=lambda: 2.0 if state["expired"] else 0.0,
        sleep=lambda _: None,
    )

    assert result.diagnostics["stop_condition"] == "timeout"
    assert result.coverage["stop_condition"] == "timeout"
    assert result.coverage["is_exhaustive"] is False


def test_terminal_page_timeout_during_dom_fallback_is_not_exhaustive():
    from collectors._douyin_browser_transport import collect_account_page

    state = {"expired": False}

    class DomFallbackExpiryBrowser(FakeBrowser):
        def __init__(self):
            super().__init__(
                events=[
                    _response_event("terminal"),
                    _loading_event("Network.loadingFinished", "terminal"),
                ],
                bodies={
                    "terminal": json.dumps({
                        "aweme_list": [ACCOUNT_AWEME],
                        "has_more": False,
                    })
                },
                cards=[{
                    "href": "https://www.douyin.com/video/7002",
                    "text": "must not be read",
                }],
            )
            self.evaluations = []

        def evaluate(self, expression):
            self.evaluations.append(expression)
            cards = super().evaluate(expression)
            state["expired"] = True
            return cards

    browser = DomFallbackExpiryBrowser()

    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        max_seconds=1.0,
        session_factory=lambda: browser,
        monotonic=lambda: 2.0 if state["expired"] else 0.0,
        sleep=lambda _: None,
    )

    assert len(browser.evaluations) == 1
    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.diagnostics["stop_condition"] == "timeout"
    assert result.coverage["stop_condition"] == "timeout"
    assert result.coverage["is_exhaustive"] is False


def test_collect_account_page_confirms_date_lower_bound_on_following_round():
    """An old non-pinned post needs a later round with no in-range addition."""
    from collectors._douyin_browser_transport import collect_account_page

    old = dict(
        ACCOUNT_AWEME, aweme_id="6999", create_time=1_600_000_000
    )
    recent = dict(
        ACCOUNT_AWEME, aweme_id="7001", create_time=1_700_000_000
    )
    browser = FakeBrowser(
        events=[
            _response_event("old"),
            _loading_event("Network.loadingFinished", "old"),
            None,
            _response_event("recent"),
            _loading_event("Network.loadingFinished", "recent"),
            None,
            None,
        ],
        bodies={
            "old": json.dumps({"aweme_list": [old]}),
            "recent": json.dumps({"aweme_list": [recent]}),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=10,
        date_range=("2023-01-01T00:00:00+08:00", None),
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert {item["aweme_id"] for item in result.aweme_items} == {"6999", "7001"}
    assert result.diagnostics["stop_condition"] == "date_lower_bound"
    assert result.diagnostics["scroll_rounds"] == 2


@pytest.mark.parametrize(
    "old_item",
    [
        dict(
            ACCOUNT_AWEME,
            aweme_id="6998",
            create_time=1_600_000_000,
            is_top=True,
        ),
        dict(ACCOUNT_AWEME, aweme_id="6997", create_time=None),
    ],
)
def test_collect_account_page_pin_or_unknown_date_cannot_trigger_date_stop(old_item):
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _response_event("old"),
            _loading_event("Network.loadingFinished", "old"),
            None,
            None,
            None,
            None,
        ],
        bodies={"old": json.dumps({"aweme_list": [old_item]})},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=10,
        date_range=("2023-01-01T00:00:00+08:00", None),
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.diagnostics["stop_condition"] != "date_lower_bound"


def test_network_and_dom_items_keep_per_post_collection_source(monkeypatch):
    """Aggregate source does not erase the evidence source of each post."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    network = dict(AWEME, _collection_source="network")
    dom = {
        "aweme_id": "7002",
        "desc": "DOM 作品",
        "share_url": "https://www.douyin.com/video/7002?secret=x",
        "statistics": {},
        "_collection_source": "dom",
    }
    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[network, dom], source="network+dom"
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    posts = collector.collect_post_list(ACCOUNT_URL, limit=2)

    assert [post["platform_metrics"]["collection_source"] for post in posts] == [
        "network",
        "dom",
    ]
    assert posts[1]["likes"] is None


def test_network_share_url_is_replaced_by_canonical_public_url():
    """Signed, credentialed, or foreign share URLs are never persisted."""
    from collectors.douyin import DouyinCollector

    aweme = dict(
        AWEME,
        share_url="https://name:secret@evil.example/video/7001?signed=secret#x",
        _collection_source="network",
    )

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, aweme, source="network")
    )

    assert post["post_url"] == "https://www.douyin.com/video/7001"
    assert post["source_url"] == "https://www.douyin.com/video/7001"


@pytest.mark.parametrize("source", ["ssr", "network"])
def test_safe_note_share_url_is_preserved_for_ssr_and_network(source):
    """A matching public note URL keeps its kind while dropping query data."""
    from collectors.douyin import DouyinCollector

    aweme = dict(
        AWEME,
        share_url="https://www.douyin.com/note/7001?signed=secret#fragment",
    )

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, aweme, source=source)
    )

    assert post["post_url"] == "https://www.douyin.com/note/7001"
    assert "secret" not in post["source_url"]


def test_note_kind_is_inferred_from_image_media_without_safe_share_url():
    from collectors.douyin import DouyinCollector

    aweme = dict(AWEME, images=[{"url_list": ["https://example.test/image"]}])
    aweme.pop("video")

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, aweme, source="network")
    )

    assert post["post_url"] == "https://www.douyin.com/note/7001"


@pytest.mark.parametrize(
    "share_url",
    [
        "https://www.douyin.com/note/9999?signed=secret",
        "https://name:password@www.douyin.com/note/7001?signed=secret",
        "http://www.douyin.com/note/7001?signed=secret",
        "https://evil.example/note/7001?signed=secret",
    ],
)
def test_unsafe_or_mismatched_note_share_url_cannot_change_video_kind(share_url):
    from collectors.douyin import DouyinCollector

    aweme = dict(AWEME, share_url=share_url)

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, aweme, source="network")
    )

    assert post["post_url"] == "https://www.douyin.com/video/7001"
    assert "secret" not in post["source_url"]


def test_collect_account_page_returns_items_with_cleanup_diagnostic():
    """A normal-exit cleanup failure retains already-observed network items."""
    from collectors._douyin_browser_transport import collect_account_page
    from collectors.browser_backend import BrowserError

    class CleanupFailBrowser(FakeBrowser):
        def __exit__(self, exc_type, exc, traceback):
            raise BrowserError(
                "浏览器清理失败: PROFILE_REMOVE_FAILED",
                diagnostic_code="BROWSER_CLEANUP_FAILED",
                cleanup_diagnostics=(
                    "PROFILE_REMOVE_FAILED",
                    "/tmp/private-profile?cookie=secret",
                ),
                is_cleanup_failure=True,
            )

    browser = CleanupFailBrowser(
        events=[RESPONSE_EVENT],
        bodies={"r1": json.dumps({"aweme_list": [ACCOUNT_AWEME]})},
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.diagnostic_code == "BROWSER_CLEANUP_FAILED"
    assert result.diagnostics["cleanup_codes"] == ["PROFILE_REMOVE_FAILED"]


@pytest.mark.parametrize("items", [[AWEME], []])
def test_collector_maps_cleanup_diagnostic_to_parser_failure_with_partial_posts(
    monkeypatch,
    items,
):
    """Cleanup failure is a parser failure and retains any normalized evidence."""
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=items,
            source="network",
            diagnostic_code="BROWSER_CLEANUP_FAILED",
            diagnostics={"cleanup_codes": ["PROFILE_REMOVE_FAILED"]},
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda url: "<html>shell</html>")

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL)

    error = exc_info.value
    assert error.stop_reason == STOP_PARSER_FAILED
    assert error.diagnostic_code == "BROWSER_CLEANUP_FAILED"
    assert [post["post_id"] for post in error.partial_posts] == (
        ["7001"] if items else []
    )


# ---------------------------------------------------------------------------
# Task 3B: bounded public completeness
# ---------------------------------------------------------------------------


def test_limited_ssr_filters_every_valid_item_before_limit_and_counts_unknown_dates(
    monkeypatch,
):
    """Newer/unknown leading rows cannot consume the requested in-range limit."""
    from collectors.douyin import DouyinCollector

    items = [
        dict(ACCOUNT_AWEME, aweme_id="6001", create_time=1_640_995_200),
        dict(ACCOUNT_AWEME, aweme_id="6002", create_time=None),
        dict(ACCOUNT_AWEME, aweme_id="7001", create_time=1_685_577_600),
        dict(ACCOUNT_AWEME, aweme_id="7002", create_time=1_690_000_000),
    ]
    collector = DouyinCollector(browser_fallback=False)
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"user": {"post": {"data": items}}}),
    )

    posts = collector.collect_post_list(
        ACCOUNT_URL,
        limit=2,
        date_range=(
            "2023-01-01T00:00:00+08:00",
            "2023-12-31T23:59:59+08:00",
        ),
    )

    assert [post["post_id"] for post in posts] == ["7001", "7002"]
    assert collector.get_collection_coverage() == {
        "requested_all": False,
        "browser_fallback_requested": False,
        "browser_fallback_launched": False,
        "terminal_page_observed": False,
        "is_exhaustive": False,
        "observed_post_count": 4,
        "unknown_date_count": 1,
        "range_filter_applied": True,
        "range_match_count": 2,
        "range_no_match": False,
    }


def test_limited_nonempty_ssr_underfill_merges_browser_evidence_first_seen(
    monkeypatch,
):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    ssr_item = {
        "aweme_id": "7001",
        "author": {"sec_uid": "example"},
        "desc": "SSR 首见文案",
        "create_time": 1_700_000_000,
        "statistics": {"digg_count": 0},
        "video": {},
        "is_top": False,
    }
    browser_calls = []

    def browser_collect(**request):
        browser_calls.append(request)
        return DouyinBrowserResult(
            aweme_items=[
                {
                    "aweme_id": "7001",
                    "desc": "浏览器冲突文案",
                    "statistics": {"digg_count": 99, "comment_count": 5},
                    "video": {"duration": 9_000},
                    "is_top": True,
                },
                dict(AWEME, aweme_id="7002"),
            ],
            source="network",
        )

    collector = DouyinCollector(browser_collect=browser_collect)
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"user": {"post": {"data": [ssr_item]}}}),
    )

    posts = collector.collect_post_list(ACCOUNT_URL, limit=2)

    assert browser_calls == [{"url": ACCOUNT_URL, "limit": 2, "date_range": None}]
    assert [post["post_id"] for post in posts] == ["7001", "7002"]
    assert posts[0]["title"] == "SSR 首见文案"
    assert posts[0]["likes"] == 0
    assert posts[0]["comments"] == 5
    assert posts[0]["duration_seconds"] == 9
    assert posts[0]["is_pinned"] is False


def test_collection_source_is_internal_allowlisted_evidence(monkeypatch):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    ssr = dict(ACCOUNT_AWEME, _collection_source="SSR_SECRET")
    ssr_collector = DouyinCollector(browser_fallback=False)
    monkeypatch.setattr(
        ssr_collector,
        "_fetch",
        lambda _url: _ssr_html({"user": {"post": {"data": [ssr]}}}),
    )
    ssr_post = ssr_collector.collect_post_list(ACCOUNT_URL, limit=1)[0]
    assert ssr_post["platform_metrics"]["collection_source"] == "list"

    browser_collector = DouyinCollector(
        browser_collect=lambda **_request: DouyinBrowserResult(
            aweme_items=[dict(AWEME, _collection_source="BROWSER_SECRET")],
            source="network",
        )
    )
    monkeypatch.setattr(browser_collector, "_fetch", lambda _url: "<html>shell</html>")
    browser_post = browser_collector.collect_post_list(ACCOUNT_URL, limit=1)[0]
    assert browser_post["platform_metrics"]["collection_source"] == "network"
    assert "SECRET" not in json.dumps([ssr_post, browser_post], ensure_ascii=False)


def test_limited_ssr_browser_restriction_retains_merged_partial_posts(monkeypatch):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    ssr_item = dict(AWEME, aweme_id="7001", video={})
    collector = DouyinCollector(
        browser_collect=lambda **_request: DouyinBrowserResult(
            aweme_items=[
                dict(AWEME, aweme_id="7001", video={"duration": 7_000}),
                dict(AWEME, aweme_id="7002"),
            ],
            source="network",
            restriction=STOP_VERIFICATION,
            diagnostics={"stop_condition": STOP_VERIFICATION},
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html({"user": {"post": {"data": [ssr_item]}}}),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL, limit=3)

    assert exc_info.value.stop_reason == STOP_VERIFICATION
    assert [post["post_id"] for post in exc_info.value.partial_posts] == [
        "7001",
        "7002",
    ]
    assert exc_info.value.partial_posts[0]["duration_seconds"] == 7


def test_restriction_batch_circuit_breaks_detail_enrichment_and_keeps_provenance(
    monkeypatch, tmp_path
):
    import collect
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **_request: DouyinBrowserResult(
            aweme_items=[{
                "aweme_id": "7001",
                "desc": "",
                "_collection_source": "network",
            }],
            restriction=STOP_VERIFICATION,
        )
    )
    collector.check_access = lambda _url: {"accessible": True}
    collector._fetch = lambda _url: "<html>shell</html>"
    collector.collect_profile = lambda _url: {
        "platform": "douyin",
        "field_visibility": {},
    }
    detail_calls = []

    def collect_post_detail(post_url):
        detail_calls.append(post_url)
        pytest.fail("detail collection must stop after a task protection reason")

    collector.collect_post_detail = collect_post_detail
    monkeypatch.setattr(collect, "_load_adapters", lambda: [collector])
    out = tmp_path / "restricted"

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(out),
        limit=1,
        enrich_details=True,
    ) == 0

    post = json.loads(
        (out / "source" / "posts.jsonl").read_text(encoding="utf-8")
    )
    assert detail_calls == []
    assert post["title"] == ""
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert post["platform_metrics"]["detail_attempted"] is False
    assert (
        post["platform_metrics"]["detail_stop_reason"]
        == "VERIFICATION_REQUIRED"
    )
    assert post["platform_metrics"]["partial_reasons"] == [
        "missing_p0_detail",
        "verification_required"
    ]
    assert collector._detail_provenance == {}


def test_ssr_underfill_keeps_restriction_priority_when_browser_rows_are_invalid(
    monkeypatch,
):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **_request: DouyinBrowserResult(
            aweme_items=[{"aweme_id": "invalid", "desc": "不可采信"}],
            restriction=STOP_VERIFICATION,
        )
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {"user": {"post": {"data": [ACCOUNT_AWEME]}}}
        ),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_post_list(ACCOUNT_URL, limit=2)

    assert exc_info.value.stop_reason == STOP_VERIFICATION
    assert [post["post_id"] for post in exc_info.value.partial_posts] == ["7001"]


def test_explicit_range_excludes_unknown_dates_and_persists_unknown_count():
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **_request: DouyinBrowserResult(
            aweme_items=[
                dict(AWEME, aweme_id="7001", create_time=None),
                dict(AWEME, aweme_id="7002", create_time=1_700_000_000),
            ],
            coverage={
                "requested_all": True,
                "is_exhaustive": True,
                "terminal_page_observed": True,
                "observed_page_count": 1,
                "observed_post_count": 2,
                "stop_condition": "terminal_page",
            },
        )
    )

    posts = collector.collect_all_post_list(
        ACCOUNT_URL,
        date_range=("2030-01-01T00:00:00+08:00", None),
    )

    assert posts == []
    coverage = collector.get_collection_coverage()
    assert coverage["unknown_date_count"] == 1
    assert coverage["range_match_count"] == 0
    assert coverage["range_filter_applied"] is True
    assert coverage["range_no_match"] is True


def test_workspace_coverage_allowlist_keeps_unknown_date_count():
    import collect

    clean = collect._sanitize_collection_coverage({
        "requested_all": False,
        "unknown_date_count": 3,
        "range_match_count": 0,
        "range_filter_applied": True,
        "range_no_match": True,
        "observed_post_count": 4,
        "cookie": "must-not-persist",
    })

    assert clean["unknown_date_count"] == 3
    assert "cookie" not in clean


def test_none_browser_evidence_source_survives_strict_sanitizers():
    import collect
    from collectors.douyin import DouyinCollector

    raw = {
        "browser_fallback_requested": True,
        "browser_fallback_launched": True,
        "browser_evidence_source": "none",
    }

    assert collect._sanitize_collection_coverage(raw)[
        "browser_evidence_source"
    ] == "none"
    assert DouyinCollector._sanitize_collection_coverage(raw)[
        "browser_evidence_source"
    ] == "none"


def test_browser_runtime_coverage_reaches_workspace_without_secrets(
    monkeypatch, tmp_path
):
    import collect
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: DouyinBrowserResult(
            aweme_items=[ACCOUNT_AWEME],
            source="network+dom",
            coverage={
                "requested_all": False,
                "browser_fallback_requested": True,
                "browser_fallback_launched": True,
                "browser_evidence_source": "network+dom",
                "scroll_rounds": 3,
                "max_seconds": 90.0,
                "max_scrolls": 20,
                "observed_page_count": 1,
                "observed_post_count": 1,
                "stop_condition": "limit",
                "cookie": "must-not-persist",
                "response_paths": ["/must-not-persist"],
            },
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")
    monkeypatch.setattr(
        collector, "check_access", lambda _url: {"accessible": True}
    )
    monkeypatch.setattr(
        collector,
        "collect_profile",
        lambda _url: {"platform": "douyin", "field_visibility": {}},
    )
    monkeypatch.setattr(collect, "_load_adapters", lambda: [collector])
    out = tmp_path / "task"

    assert collect.run(ACCOUNT_URL, limit=1, out_dir=str(out)) == 0

    coverage = json.loads((out / "task.json").read_text(encoding="utf-8"))[
        "collection_coverage"
    ]
    assert coverage["browser_fallback_requested"] is True
    assert coverage["browser_fallback_launched"] is True
    assert coverage["browser_evidence_source"] == "network+dom"
    assert coverage["scroll_rounds"] == 3
    assert coverage["max_seconds"] == 90.0
    assert coverage["max_scrolls"] == 20
    assert "cookie" not in coverage
    assert "response_paths" not in coverage


def test_visible_login_audit_reaches_collection_task_and_report_without_page_text(
    monkeypatch, tmp_path
):
    import collect
    from collectors._douyin_browser_transport import collect_account_page
    from collectors.douyin import DouyinCollector

    visible_text = "登录后查看 PAGE_TEXT_MUST_NOT_PERSIST"
    browser_result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: FakeBrowser(page_texts=[visible_text]),
        sleep=lambda _seconds: None,
    )
    collector = DouyinCollector(
        browser_collect=lambda **_request: browser_result,
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")
    monkeypatch.setattr(
        collector, "check_access", lambda _url: {"accessible": True}
    )
    monkeypatch.setattr(
        collector,
        "collect_profile",
        lambda _url: {"platform": "douyin", "field_visibility": {}},
    )
    monkeypatch.setattr(collect, "_load_adapters", lambda: [collector])
    out = tmp_path / "task"

    assert collect.run(ACCOUNT_URL, limit=1, out_dir=str(out)) == 3

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["stop_reason"] == STOP_LOGIN
    assert task["collection_coverage"]["restriction_source"] == (
        "browser_visible_text"
    )
    assert task["collection_coverage"]["restriction_marker"] == (
        "LOGIN_WALL_VISIBLE"
    )
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert '- restriction_source: "browser_visible_text"' in report
    assert '- restriction_marker: "LOGIN_WALL_VISIBLE"' in report
    persisted = "".join(
        artifact.read_text(encoding="utf-8")
        for artifact in out.rglob("*")
        if artifact.is_file()
    )
    assert "PAGE_TEXT_MUST_NOT_PERSIST" not in persisted


def test_workspace_date_intersection_excludes_unknown_rows_when_range_is_explicit():
    import collect

    posts = [
        {"post_id": "unknown", "published_at": None},
        {"post_id": "inside", "published_at": "2023-06-01T10:00:00+08:00"},
    ]

    filtered = collect._filter_by_date(
        posts,
        "2023-01-01T00:00:00+08:00",
        "2023-12-31T23:59:59+08:00",
    )

    assert [post["post_id"] for post in filtered] == ["inside"]


def test_limited_browser_targets_in_range_unique_posts_with_both_bounds():
    from collectors._douyin_browser_transport import collect_account_page

    newer = dict(
        ACCOUNT_AWEME, aweme_id="8001", create_time=1_704_067_200
    )
    unknown = dict(ACCOUNT_AWEME, aweme_id="8002", create_time=None)
    in_range_one = dict(
        ACCOUNT_AWEME, aweme_id="7001", create_time=1_685_577_600
    )
    in_range_two = dict(
        ACCOUNT_AWEME, aweme_id="7002", create_time=1_690_000_000
    )
    browser = FakeBrowser(
        events=[
            _response_event("outside"),
            _loading_event("Network.loadingFinished", "outside"),
            _response_event("inside-one"),
            _loading_event("Network.loadingFinished", "inside-one"),
            _response_event("inside-two"),
            _loading_event("Network.loadingFinished", "inside-two"),
        ],
        bodies={
            "outside": json.dumps({"aweme_list": [newer, unknown]}),
            "inside-one": json.dumps({"aweme_list": [in_range_one]}),
            "inside-two": json.dumps({"aweme_list": [in_range_two]}),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=2,
        date_range=(
            "2023-01-01T00:00:00+08:00",
            "2023-12-31T23:59:59+08:00",
        ),
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001", "7002"]
    assert result.coverage["observed_post_count"] == 4
    assert result.coverage["unknown_date_count"] == 1
    assert result.coverage["range_match_count"] == 2
    assert result.coverage["range_filter_applied"] is True
    assert result.diagnostics["stop_condition"] == "limit"


def test_limited_browser_duplicate_date_enrichment_counts_in_confirmation_round():
    """A duplicate that fills create_time must cancel a pending lower-bound stop."""
    from collectors._douyin_browser_transport import collect_account_page

    old = dict(
        ACCOUNT_AWEME, aweme_id="6001", create_time=1_600_000_000
    )
    unknown = dict(ACCOUNT_AWEME, aweme_id="7001", create_time=None)
    dated_duplicate = {
        "aweme_id": "7001",
        "create_time": 1_685_577_600,
        "video": {"duration": 9_000},
        "author": {"sec_uid": "example"},
    }
    second_match = dict(
        ACCOUNT_AWEME, aweme_id="7002", create_time=1_690_000_000
    )
    browser = FakeBrowser(
        events=[
            _response_event("old"),
            _loading_event("Network.loadingFinished", "old"),
            None,
            _response_event("unknown"),
            _loading_event("Network.loadingFinished", "unknown"),
            _response_event("dated"),
            _loading_event("Network.loadingFinished", "dated"),
            None,
            _response_event("second"),
            _loading_event("Network.loadingFinished", "second"),
        ],
        bodies={
            "old": json.dumps({"aweme_list": [old]}),
            "unknown": json.dumps({"aweme_list": [unknown]}),
            "dated": json.dumps({"aweme_list": [dated_duplicate]}),
            "second": json.dumps({"aweme_list": [second_match]}),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=2,
        date_range=("2023-01-01T00:00:00+08:00", None),
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001", "7002"]
    assert result.coverage["range_match_count"] == 2


def test_browser_profile_extraction_is_allowlisted_and_account_bound():
    from collectors._douyin_browser_transport import extract_profile_raw

    payload = {
        "data": {
            "user_info": {
                "sec_uid": "example",
                "uid": "42",
                "unique_id": "public-id",
                "nickname": "公开昵称",
                "signature": "公开简介",
                "follower_count": 0,
                "aweme_count": 0,
                "total_favorited": 0,
                "verified": False,
                "cookie": "COOKIE_SECRET",
                "cursor": "CURSOR_SECRET",
                "avatar": {"url_list": ["https://signed.example/SECRET"]},
            }
        }
    }

    profile = extract_profile_raw(payload, ACCOUNT_URL)

    assert profile["account_id"] == "public-id"
    assert profile["account_name"] == "公开昵称"
    assert profile["profile_url"] == ACCOUNT_URL
    assert profile["bio"] == "公开简介"
    assert profile["verified"] is False
    assert profile["followers"] == 0
    assert profile["post_count"] == 0
    assert profile["platform_metrics"] == {
        "total_likes": 0,
        "sec_uid": "example",
        "unique_id": "public-id",
        "uid": "42",
    }
    serialized = json.dumps(profile, ensure_ascii=False)
    assert "COOKIE_SECRET" not in serialized
    assert "CURSOR_SECRET" not in serialized
    assert "signed.example" not in serialized

    mismatched = json.loads(json.dumps(payload))
    mismatched["data"]["user_info"]["sec_uid"] = "another-account"
    assert extract_profile_raw(mismatched, ACCOUNT_URL) is None


def test_browser_profile_merge_upgrades_false_to_public_certification_text():
    """Later account-bound positive evidence must beat an earlier weak negative."""
    from collectors._douyin_browser_transport import extract_profile_raw

    profile = extract_profile_raw(
        {
            "candidates": [
                {
                    "sec_uid": "example",
                    "unique_id": "public-id",
                    "verified": False,
                },
                {
                    "sec_uid": "example",
                    "enterprise_verify_reason": "搞笑短视频创作者",
                },
            ]
        },
        ACCOUNT_URL,
    )

    assert profile["verified"] == "搞笑短视频创作者"


def test_browser_profile_merge_upgrades_sec_uid_fallback_to_public_id():
    """A later public Douyin ID is stronger than the URL sec_uid fallback."""
    from collectors._douyin_browser_transport import extract_profile_raw

    profile = extract_profile_raw(
        {
            "candidates": [
                {"sec_uid": "example"},
                {"sec_uid": "example", "unique_id": "public-id"},
            ]
        },
        ACCOUNT_URL,
    )

    assert profile["account_id"] == "public-id"
    assert profile["platform_metrics"]["unique_id"] == "public-id"
    assert profile["field_visibility"]["account_id"] == "visible"


def test_browser_network_profile_updates_upgrade_false_to_certification_text():
    """Separate account-bound responses use the same verification precedence."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _response_event("profile-false"),
            _loading_event("Network.loadingFinished", "profile-false"),
            _response_event("profile-text"),
            _loading_event("Network.loadingFinished", "profile-text"),
        ],
        bodies={
            "profile-false": json.dumps(
                {"user_info": {"sec_uid": "example", "verified": False}}
            ),
            "profile-text": json.dumps(
                {
                    "user_info": {
                        "sec_uid": "example",
                        "enterprise_verify_reason": "搞笑短视频创作者",
                    }
                }
            ),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.profile_raw["verified"] == "搞笑短视频创作者"


def test_browser_network_profile_merge_recomputes_verification_visibility():
    """A later visible badge upgrades an earlier unknown visibility state."""
    from collectors._douyin_browser_transport import collect_account_page

    browser = FakeBrowser(
        events=[
            _response_event("profile-unknown"),
            _loading_event("Network.loadingFinished", "profile-unknown"),
            _response_event("profile-text"),
            _loading_event("Network.loadingFinished", "profile-text"),
        ],
        bodies={
            "profile-unknown": json.dumps(
                {"user_info": {"sec_uid": "example"}}
            ),
            "profile-text": json.dumps(
                {
                    "user_info": {
                        "sec_uid": "example",
                        "enterprise_verify_reason": "搞笑短视频创作者",
                    }
                }
            ),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        max_scrolls=1,
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert result.profile_raw["verified"] == "搞笑短视频创作者"
    assert result.profile_raw["field_visibility"]["verified"] == "visible"


def test_ssr_profile_missing_verification_evidence_remains_unknown():
    """Omitted certification fields are unknown, not an explicit negative."""
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html(
        {
            "user": {
                "user": {
                    "sec_uid": "example",
                    "unique_id": "public-id",
                    "nickname": "公开昵称",
                    "follower_count": 0,
                    "aweme_count": 0,
                    "total_favorited": 0,
                }
            }
        }
    )

    profile = collector.collect_profile(ACCOUNT_URL)

    assert profile["verified"] is None
    assert profile["followers"] == 0
    assert profile["post_count"] == 0
    assert profile["platform_metrics"]["total_likes"] == 0
    assert profile["field_visibility"]["followers"] == "visible"
    assert profile["field_visibility"]["post_count"] == "visible"
    assert profile["field_visibility"]["total_likes"] == "visible"


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ({"verification_type": 0}, False),
        ({"verification_type": -1}, False),
        ({"verification_type": 2}, True),
        ({"verified": False}, False),
        ({"verified": True}, True),
        (
            {
                "verification_type": 2,
                "enterprise_verify_reason": "搞笑短视频创作者",
            },
            "搞笑短视频创作者",
        ),
    ],
)
def test_ssr_profile_uses_only_explicit_verification_evidence(user, expected):
    """Explicit status fields are tri-state while public text stays strongest."""
    from collectors.douyin import DouyinCollector

    assert DouyinCollector._extract_verified(user) == expected


@pytest.mark.parametrize(
    ("verification", "expected"),
    [
        ({}, None),
        ({"verification_type": 0}, False),
        ({"verification_type": -1}, False),
        ({"verification_type": 2}, True),
        ({"custom_verify": "个人认证创作者"}, "个人认证创作者"),
        (
            {"enterprise_verify_reason": "搞笑短视频创作者"},
            "搞笑短视频创作者",
        ),
    ],
)
def test_ies_profile_api_preserves_explicit_verification_tristate(
    monkeypatch, verification, expected
):
    """The public API fallback must not collapse missing evidence into false."""
    from collectors.douyin import DouyinCollector

    payload = {
        "user_info": {
            "sec_uid": "example",
            "unique_id": "public-id",
            "nickname": "公开昵称",
            "follower_count": 0,
            "aweme_count": 0,
            "total_favorited": 0,
            **verification,
        }
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda _request, timeout: Response()
    )
    profile = DouyinCollector()._fetch_profile_via_iesdouyin_api(
        "example", ACCOUNT_URL
    )

    assert profile["verified"] == expected
    assert profile["followers"] == 0
    assert profile["post_count"] == 0
    assert profile["platform_metrics"]["total_likes"] == 0
    assert profile["field_visibility"]["followers"] == "visible"
    assert profile["field_visibility"]["post_count"] == "visible"
    assert profile["field_visibility"]["total_likes"] == "visible"


@pytest.mark.parametrize(
    "conflicting_binding",
    [
        {"sec_uid": "other-account"},
        {
            "sec_uid": "example",
            "profile_url": "https://www.douyin.com/user/other-account",
        },
    ],
)
def test_ies_profile_api_rejects_conflicting_account_binding_without_cache_pollution(
    monkeypatch, conflicting_binding
):
    """An API response must prove the requested account instead of being relabelled."""
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    payload = {
        "user_info": {
            "unique_id": "other-public-id",
            "nickname": "错误账号",
            **conflicting_binding,
        }
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(payload).encode("utf-8")

    collector = DouyinCollector()
    collector._cache_browser_profile(
        ACCOUNT_URL,
        {
            "profile_url": ACCOUNT_URL,
            "sec_uid": "example",
            "nickname": "原缓存账号",
        },
    )
    cache_before = json.dumps(
        collector._browser_profile_cache, ensure_ascii=False, sort_keys=True
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda _request, timeout: Response()
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_profile(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert exc_info.value.raw is None
    assert json.dumps(
        collector._browser_profile_cache, ensure_ascii=False, sort_keys=True
    ) == cache_before


@pytest.mark.parametrize(
    "conflicting_user",
    [
        {
            "sec_uid": "other-account",
            "unique_id": "other-public-id",
            "nickname": "错误账号",
        },
        {
            "sec_uid": "example",
            "unique_id": "other-public-id",
            "nickname": "错误账号",
            "profile_url": "https://www.douyin.com/user/other-account",
        },
    ],
)
def test_ssr_profile_rejects_conflicting_account_without_cache_fallback(
    monkeypatch, conflicting_user
):
    """Explicit SSR account mismatch fails closed and cannot emit cached output."""
    from collectors.douyin import DouyinCollector, DouyinError, STOP_PARSER_FAILED

    collector = DouyinCollector()
    collector._cache_browser_profile(
        ACCOUNT_URL,
        {
            "profile_url": ACCOUNT_URL,
            "sec_uid": "example",
            "nickname": "原缓存账号",
        },
    )
    cache_before = json.dumps(
        collector._browser_profile_cache, ensure_ascii=False, sort_keys=True
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {
                "user": {
                    "user": conflicting_user
                }
            }
        ),
    )

    with pytest.raises(DouyinError) as exc_info:
        collector.collect_profile(ACCOUNT_URL)

    assert exc_info.value.stop_reason == STOP_PARSER_FAILED
    assert exc_info.value.raw is None
    assert json.dumps(
        collector._browser_profile_cache, ensure_ascii=False, sort_keys=True
    ) == cache_before


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ({"verified": "false"}, None),
        ({"verified": "未认证"}, None),
        ({"verified": "机构认证"}, None),
        ({"verification_type": -2}, None),
        ({"verification_type": float("nan")}, None),
        ({"verification_type": float("inf")}, None),
        ({"verification_type": float("-inf")}, None),
        ({"verification_type": True}, None),
        ({"verification_type": False}, None),
        ({"verification_type": "2"}, None),
        ({"verification_type": 0}, False),
        ({"verification_type": -1}, False),
        ({"verification_type": 1.5}, True),
        ({"verification_type": 10**1000}, True),
        ({"verification": {"type": -2}}, None),
        ({"verification": {"type": 2}}, True),
    ],
)
def test_profile_verification_parsers_share_strict_value_domain(evidence, expected):
    """Network/browser and SSR/API parsing use the same finite tri-state rules."""
    from collectors._douyin_browser_transport import sanitize_profile_raw
    from collectors.douyin import DouyinCollector

    browser_profile = sanitize_profile_raw(
        {"sec_uid": "example", **evidence}, ACCOUNT_URL
    )

    assert browser_profile["verified"] == expected
    assert DouyinCollector._extract_verified(evidence) == expected


@pytest.mark.parametrize("label", ["false", "未认证"])
def test_dom_badge_negative_labels_are_not_positive_certification(label):
    from collectors._douyin_browser_transport import sanitize_profile_raw

    untrusted_generic = sanitize_profile_raw(
        {"sec_uid": "example", "verified": label}, ACCOUNT_URL
    )
    bound_badge = sanitize_profile_raw(
        {"sec_uid": "example", "dom_verified_badge": label},
        ACCOUNT_URL,
        allow_dom_badge=True,
    )

    assert untrusted_generic["verified"] is None
    assert bound_badge["verified"] is None


def test_only_account_bound_dom_badge_can_supply_certification_text():
    from collectors._douyin_browser_transport import sanitize_profile_raw

    ignored = sanitize_profile_raw(
        {
            "sec_uid": "example",
            "verified": "搞笑短视频创作者",
            "dom_verified_badge": "搞笑短视频创作者",
        },
        ACCOUNT_URL,
    )
    accepted = sanitize_profile_raw(
        {
            "sec_uid": "example",
            "dom_verified_badge": "搞笑短视频创作者",
        },
        ACCOUNT_URL,
        allow_dom_badge=True,
    )

    assert ignored["verified"] is None
    assert accepted["verified"] == "搞笑短视频创作者"


def test_browser_profile_sanitizer_rejects_nonfinite_public_counts():
    from collectors._douyin_browser_transport import sanitize_profile_raw

    profile = sanitize_profile_raw(
        {
            "sec_uid": "example",
            "nickname": "公开昵称",
            "follower_count": float("inf"),
            "aweme_count": float("nan"),
        },
        ACCOUNT_URL,
    )

    assert profile["followers"] is None
    assert profile["post_count"] is None


def test_browser_profile_visibility_distinguishes_public_zero_and_url_fallback():
    """Visibility must describe evidence strength without treating zero as absent."""
    from collectors._douyin_browser_transport import sanitize_profile_raw

    visible = sanitize_profile_raw(
        {
            "profile_url": ACCOUNT_URL,
            "sec_uid": "example",
            "unique_id": "public-id",
            "verified": False,
            "total_favorited": 0,
        },
        ACCOUNT_URL,
    )
    fallback = sanitize_profile_raw(
        {"profile_url": ACCOUNT_URL, "sec_uid": "example"},
        ACCOUNT_URL,
    )

    assert visible["field_visibility"]["account_id"] == "visible"
    assert visible["field_visibility"]["verified"] == "visible"
    assert visible["field_visibility"]["total_likes"] == "visible"
    assert fallback["field_visibility"]["account_id"] == "partial"
    assert fallback["field_visibility"]["verified"] == "hidden"
    assert fallback["field_visibility"]["total_likes"] == "hidden"


def test_browser_profile_sanitizer_is_idempotent_for_public_verification_text():
    from collectors._douyin_browser_transport import sanitize_profile_raw

    first = sanitize_profile_raw(
        {
            "sec_uid": "example",
            "nickname": "公开昵称",
            "enterprise_verify_reason": "机构认证",
        },
        ACCOUNT_URL,
    )
    second = sanitize_profile_raw(first, ACCOUNT_URL)

    assert first["verified"] == "机构认证"
    assert second["verified"] == "机构认证"


@pytest.mark.parametrize("dom_first", [False, True])
def test_browser_profile_cache_merges_snapshots_without_losing_stronger_fields(
    dom_first,
):
    """Cache updates are commutative for complementary evidence, including zero."""
    from collectors.douyin import DouyinCollector

    network_snapshot = {
        "profile_url": ACCOUNT_URL,
        "sec_uid": "example",
        "unique_id": "public-id",
        "nickname": "公开昵称",
        "total_favorited": 0,
        "follower_count": 0,
        "verified": False,
    }
    dom_snapshot = {
        "profile_url": ACCOUNT_URL,
        "sec_uid": "example",
        "dom_verified_badge": "搞笑短视频创作者",
    }
    ordered = (
        (dom_snapshot, network_snapshot)
        if dom_first
        else (network_snapshot, dom_snapshot)
    )
    collector = DouyinCollector()

    for snapshot in ordered:
        collector._cache_browser_profile(ACCOUNT_URL, snapshot)

    cached = collector._browser_profile_cache[ACCOUNT_URL]
    assert cached["account_id"] == "public-id"
    assert cached["account_name"] == "公开昵称"
    assert cached["followers"] == 0
    assert cached["platform_metrics"]["total_likes"] == 0
    assert cached["verified"] == "搞笑短视频创作者"
    assert cached["field_visibility"]["account_id"] == "visible"
    assert cached["field_visibility"]["verified"] == "visible"
    assert cached["field_visibility"]["total_likes"] == "visible"


def test_limited_browser_nonfinite_date_does_not_satisfy_range_target():
    from collectors._douyin_browser_transport import collect_account_page

    invalid_date = dict(
        ACCOUNT_AWEME, aweme_id="8001", create_time=float("nan")
    )
    valid_date = dict(
        ACCOUNT_AWEME, aweme_id="7001", create_time=1_685_577_600
    )
    browser = FakeBrowser(
        events=[
            _response_event("invalid"),
            _loading_event("Network.loadingFinished", "invalid"),
            _response_event("valid"),
            _loading_event("Network.loadingFinished", "valid"),
        ],
        bodies={
            "invalid": json.dumps({"aweme_list": [invalid_date]}),
            "valid": json.dumps({"aweme_list": [valid_date]}),
        },
    )

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        date_range=("2023-01-01T00:00:00+08:00", None),
        session_factory=lambda: browser,
        sleep=lambda _seconds: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["unknown_date_count"] == 1


def test_browser_profile_cache_falls_back_after_ssr_and_api_profile_fail(monkeypatch):
    from collectors._douyin_browser_transport import DouyinBrowserResult
    from collectors.douyin import DouyinCollector

    browser_profile = {
        "platform": "douyin",
        "account_id": "public-id",
        "account_name": "浏览器公开昵称",
        "profile_url": ACCOUNT_URL + "?signed=SECRET",
        "bio": "公开简介",
        "verified": False,
        "followers": 0,
        "post_count": 0,
        "platform_metrics": {
            "sec_uid": "example",
            "unique_id": "public-id",
            "total_likes": 0,
            "cookie": "NESTED_SECRET",
        },
        "cursor": "TOP_LEVEL_SECRET",
    }
    collector = DouyinCollector(
        browser_collect=lambda **_request: DouyinBrowserResult(
            aweme_items=[AWEME],
            profile_raw=browser_profile,
        )
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")
    monkeypatch.setattr(
        collector,
        "_fetch_profile_via_iesdouyin_api",
        lambda _sec_uid, _url: None,
    )

    collector.collect_post_list(ACCOUNT_URL, limit=1)
    profile = collector.collect_profile(ACCOUNT_URL)

    assert profile["account_name"] == "浏览器公开昵称"
    assert profile["followers"] == 0
    assert profile["verified"] is False
    assert profile["profile_url"] == ACCOUNT_URL
    serialized = json.dumps(profile, ensure_ascii=False)
    assert "SECRET" not in serialized
    assert "cookie" not in serialized
    assert "cursor" not in serialized


def test_live_profile_merges_api_identity_with_visible_browser_certification(
    monkeypatch,
):
    """API identity stays exact while visible account-bound certification wins."""
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    collector._cache_browser_profile(
        ACCOUNT_URL,
        {
            "profile_url": ACCOUNT_URL,
            "sec_uid": "example",
            "nickname": "公开昵称",
            "dom_verified_badge": "搞笑短视频创作者",
        },
    )
    monkeypatch.setattr(collector, "_fetch", lambda _url: "<html>shell</html>")
    monkeypatch.setattr(
        collector,
        "_fetch_profile_via_iesdouyin_api",
        lambda _sec_uid, _url: {
            "platform": "douyin",
            "account_id": "8533800Pt",
            "account_name": "公开昵称",
            "profile_url": ACCOUNT_URL,
            "bio": "公开简介",
            "verified": False,
            "followers": 12_815_000,
            "post_count": 726,
            "platform_metrics": {
                "total_likes": 148_136_347,
                "sec_uid": "example",
                "unique_id": "8533800Pt",
            },
            "field_visibility": {},
        },
    )

    profile = collector.collect_profile(ACCOUNT_URL)

    assert profile["account_id"] == "8533800Pt"
    assert profile["platform_metrics"]["total_likes"] == 148_136_347
    assert profile["verified"] == "搞笑短视频创作者"


def test_ssr_profile_merges_same_account_visible_browser_certification(monkeypatch):
    """An SSR weak negative must not bypass stronger visible browser evidence."""
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    collector._cache_browser_profile(
        ACCOUNT_URL,
        {
            "profile_url": ACCOUNT_URL,
            "sec_uid": "example",
            "dom_verified_badge": "搞笑短视频创作者",
        },
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda _url: _ssr_html(
            {
                "user": {
                    "user": {
                        "sec_uid": "example",
                        "unique_id": "8533800Pt",
                        "nickname": "公开昵称",
                        "verified": False,
                        "total_favorited": 148_136_347,
                    }
                }
            }
        ),
    )

    profile = collector.collect_profile(ACCOUNT_URL)

    assert profile["account_id"] == "8533800Pt"
    assert profile["platform_metrics"]["total_likes"] == 148_136_347
    assert profile["verified"] == "搞笑短视频创作者"


def test_visible_browser_snapshot_can_supply_account_bound_profile():
    from collectors._douyin_browser_transport import collect_account_page

    class SnapshotBrowser(FakeBrowser):
        def evaluate(self, _expression):
            return {
                "cards": [{
                    "href": "https://www.douyin.com/video/7001",
                    "text": "公开作品",
                }],
                "profile": {
                    "profile_url": ACCOUNT_URL + "?signed=SECRET",
                    "sec_uid": "example",
                    "nickname": "可见昵称",
                    "follower_count": "0",
                    "verified": False,
                    "cookie": "COOKIE_SECRET",
                },
            }

    result = collect_account_page(
        ACCOUNT_URL,
        limit=1,
        session_factory=lambda: SnapshotBrowser(),
        sleep=lambda _seconds: None,
    )

    assert result.profile_raw["account_name"] == "可见昵称"
    assert result.profile_raw["followers"] == 0
    assert result.profile_raw["verified"] is False
    assert "SECRET" not in json.dumps(result.profile_raw, ensure_ascii=False)


def test_minimal_browser_rows_are_partial_but_complete_rows_are_success():
    from collectors.douyin import DouyinCollector

    minimal = {
        "aweme_id": "7001",
        "desc": "仅有卡片文案",
        "share_url": "https://www.douyin.com/video/7001",
        "statistics": {"digg_count": 0},
        "_collection_source": "dom",
    }
    complete = dict(AWEME, _collection_source="network")

    minimal_post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, minimal, source="dom")
    )
    complete_post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, complete, source="network")
    )

    assert minimal_post["collection_status"] == "PARTIAL"
    assert complete_post["collection_status"] == "SUCCESS"


@pytest.mark.parametrize("duration", ["not-a-duration", -1])
def test_malformed_browser_detail_fields_remain_partial_without_crashing(duration):
    from collectors.douyin import DouyinCollector

    malformed = {
        "aweme_id": "7001",
        "desc": "公开文案",
        "create_time": True,
        "statistics": ["must-not-persist"],
        "video": {"duration": duration},
        "_collection_source": "network",
    }

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, malformed, source="network")
    )

    assert post["published_at"] is None
    assert post["duration_seconds"] is None
    assert post["likes"] is None
    assert post["collection_status"] == "PARTIAL"
    assert "must-not-persist" not in json.dumps(post, ensure_ascii=False)


def test_successful_detail_enrichment_upgrades_browser_partial_only_when_complete():
    import collect
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    post = collector._normalized_posts_from_items(
        ACCOUNT_URL,
        [{
            "aweme_id": "7001",
            "desc": "",
            "create_time": None,
            "video": {},
            "text_extra": [],
            "_collection_source": "dom",
        }],
        "dom",
    )[0]
    collector.collect_post_detail = lambda _post_url: {
        "post_id": "7001",
        "title": "完整标题",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": 9,
        "hashtags": [],
    }

    unavailable = collect._enrich_douyin_details(
        collector,
        [post],
        [],
        "2026-07-25T10:00:00+08:00",
    )

    assert unavailable == 0
    assert post["collection_status"] == "SUCCESS"
    assert post["platform_metrics"]["detail_status"] == "SUCCESS"


def test_transient_detail_provenance_never_reaches_jsonl_or_csv(
    monkeypatch, tmp_path
):
    import collect
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    collector.check_access = lambda _url: {"accessible": True}
    collector.collect_profile = lambda _url: {
        "platform": "douyin",
        "field_visibility": {},
    }
    collector.collect_post_list = lambda url, limit=30, date_range=None: (
        collector._normalized_posts_from_items(
            url,
            [{
                "aweme_id": "7001",
                "desc": "仅有浏览器卡片",
                "_collection_source": "dom",
            }],
            "dom",
        )[:limit]
    )
    monkeypatch.setattr(collect, "_load_adapters", lambda: [collector])
    out = tmp_path / "task"

    assert collect.run(ACCOUNT_URL, out_dir=str(out), limit=1) == 0

    persisted = (
        (out / "source" / "posts.jsonl").read_text(encoding="utf-8")
        + (out / "normalized-posts.csv").read_text(encoding="utf-8")
    )
    assert "provenance" not in persisted.lower()
    assert "trusted_detail" not in persisted.lower()
    assert collector._detail_provenance == {}


def test_reused_collector_resets_detail_provenance_for_each_top_level_list_call():
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector(browser_fallback=False)
    call_count = 0

    def fetch(_url):
        nonlocal call_count
        call_count += 1
        return _ssr_html({
            "user": {
                "post": {
                    "data": [{
                        "aweme_id": str(7000 + call_count),
                        "author": {"sec_uid": "example"},
                        "desc": "无话题字段的 SSR 作品",
                        "create_time": 1700000000 + call_count,
                        "video": {"duration": 9000},
                    }]
                }
            }
        })

    collector._fetch = fetch
    previous_post = None
    for _ in range(25):
        posts = collector.collect_post_list(ACCOUNT_URL, limit=1)
        assert len(posts) == 1
        assert len(collector._detail_provenance) == 1
        if previous_post is not None:
            assert id(previous_post) not in collector._detail_provenance
        previous_post = posts[0]


def test_failed_top_level_list_call_discards_previous_batch_provenance():
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(browser_fallback=False)
    collector._fetch = lambda _url: _ssr_html({
        "user": {
            "post": {
                "data": [{
                    "aweme_id": "7001",
                    "author": {"sec_uid": "example"},
                    "desc": "无话题字段的 SSR 作品",
                    "create_time": 1700000000,
                    "video": {"duration": 9000},
                }]
            }
        }
    })
    collector.collect_post_list(ACCOUNT_URL, limit=1)
    assert len(collector._detail_provenance) == 1

    collector._fetch = lambda _url: (_ for _ in ()).throw(
        DouyinError("ACCESS_RESTRICTED", "blocked")
    )
    with pytest.raises(DouyinError):
        collector.collect_post_list(ACCOUNT_URL, limit=1)

    assert collector._detail_provenance == {}


def test_incomplete_successful_detail_response_downgrades_row_with_defined_status():
    import collect

    class IncompleteDetailAdapter:
        def collect_post_detail(self, _post_url):
            return {
                "post_id": "7001",
                "title": "仅补标题",
                "published_at": None,
                "duration_seconds": None,
                "hashtags": None,
            }

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "title": None,
        "published_at": None,
        "duration_seconds": None,
        "hashtags": [],
        "collection_status": "SUCCESS",
        "platform_metrics": {"collection_source": "list"},
    }
    errors = []

    unavailable = collect._enrich_douyin_details(
        IncompleteDetailAdapter(),
        [post],
        errors,
        "2026-07-25T10:00:00+08:00",
    )

    assert unavailable == 1
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["detail_status"] == "UNAVAILABLE"
    assert post["platform_metrics"]["partial_reasons"] == ["missing_p0_detail"]
    assert post["platform_metrics"]["missing_detail_fields"] == [
        "published_at",
        "duration_seconds",
    ]
    assert errors[-1]["message"] == "作品详情补充不完整"


def test_detail_enrichment_never_clears_an_independent_partial_reason():
    import collect

    class CompleteDetailAdapter:
        def collect_post_detail(self, _post_url):
            return {
                "post_id": "7001",
                "title": "完整标题",
                "published_at": "2026-07-20T10:00:00+08:00",
                "duration_seconds": 9,
                "hashtags": [],
            }

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": None,
        "published_at": None,
        "duration_seconds": None,
        "hashtags": [],
        "collection_status": "PARTIAL",
        "platform_metrics": {
            "collection_source": "network",
            "partial_reasons": ["missing_p0_detail", "restricted"],
            "missing_detail_fields": [
                "title",
                "published_at",
                "duration_seconds",
                "hashtags",
            ],
        },
    }

    unavailable = collect._enrich_douyin_details(
        CompleteDetailAdapter(),
        [post],
        [],
        "2026-07-25T10:00:00+08:00",
    )

    assert unavailable == 0
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["detail_status"] == "SUCCESS"
    assert post["platform_metrics"]["partial_reasons"] == [
        "restricted",
        "other_partial",
    ]
    assert post["platform_metrics"]["missing_detail_fields"] == []


def test_detail_enrichment_does_not_trust_stale_missing_metadata_over_list_values():
    import collect

    class MustNotRun:
        def collect_post_detail(self, _post_url):
            pytest.fail("complete list evidence must not be overwritten")

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": "列表可靠标题",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": 9,
        "hashtags": ["列表话题"],
        "collection_status": "PARTIAL",
        "platform_metrics": {
            "collection_source": "network",
            "partial_reasons": ["missing_p0_detail"],
            "missing_detail_fields": ["title"],
        },
    }

    unavailable = collect._enrich_douyin_details(
        MustNotRun(),
        [post],
        [],
        "2026-07-25T10:00:00+08:00",
    )

    assert unavailable == 0
    assert post["title"] == "列表可靠标题"
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["detail_status"] == "NOT_NEEDED"
    assert post["platform_metrics"]["partial_reasons"] == ["other_partial"]
    assert post["platform_metrics"]["missing_detail_fields"] == []


def test_legacy_partial_without_transient_provenance_never_upgrades_after_detail():
    import collect

    class CompleteDetailAdapter:
        def collect_post_detail(self, _post_url):
            return {
                "post_id": "7001",
                "title": "补齐标题",
                "published_at": "2026-07-20T10:00:00+08:00",
                "duration_seconds": 0,
                "hashtags": [],
            }

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": None,
        "published_at": None,
        "duration_seconds": None,
        "hashtags": [],
        "collection_status": "PARTIAL",
        "platform_metrics": {"collection_source": "network"},
    }

    unavailable = collect._enrich_douyin_details(
        CompleteDetailAdapter(), [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["detail_status"] == "SUCCESS"
    assert post["platform_metrics"]["partial_reasons"] == ["other_partial"]


@pytest.mark.parametrize("reason_location", ["platform_metrics", "top_level"])
def test_legacy_singular_partial_reason_always_blocks_upgrade(reason_location):
    import collect

    class CompleteDetailAdapter:
        def collect_post_detail(self, _post_url):
            return {
                "post_id": "7001",
                "title": "补齐标题",
                "published_at": "2026-07-20T10:00:00+08:00",
                "duration_seconds": 1,
                "hashtags": [],
            }

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": None,
        "published_at": None,
        "duration_seconds": None,
        "hashtags": [],
        "collection_status": "PARTIAL",
        "platform_metrics": {"collection_source": "network"},
    }
    if reason_location == "platform_metrics":
        post["platform_metrics"]["partial_reason"] = "RESTRICTED"
    else:
        post["partial_reason"] = "RESTRICTED"

    collect._enrich_douyin_details(
        CompleteDetailAdapter(), [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["partial_reasons"] == ["other_partial"]
    assert "partial_reason" not in post
    assert "partial_reason" not in post["platform_metrics"]


def test_persisted_missing_hashtag_metadata_cannot_overwrite_observed_empty_list():
    import collect

    class MustNotRun:
        def collect_post_detail(self, _post_url):
            pytest.fail("persisted diagnostics cannot make observed [] missing")

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": "可靠标题",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": 0,
        "hashtags": [],
        "collection_status": "PARTIAL",
        "platform_metrics": {
            "collection_source": "network",
            "partial_reasons": ["missing_p0_detail"],
            "missing_detail_fields": ["hashtags"],
        },
    }

    unavailable = collect._enrich_douyin_details(
        MustNotRun(), [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post["hashtags"] == []
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["partial_reasons"] == ["other_partial"]
    assert post["platform_metrics"]["missing_detail_fields"] == []


def test_detail_enrichment_does_not_reclassify_terminal_item_status():
    import collect

    class MustNotRun:
        def collect_post_detail(self, _post_url):
            pytest.fail("terminal rows are not eligible for enrichment")

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "title": None,
        "published_at": None,
        "duration_seconds": None,
        "hashtags": [],
        "collection_status": "RESTRICTED",
        "platform_metrics": {"collection_source": "network"},
    }

    assert collect._enrich_douyin_details(
        MustNotRun(), [post], [], "2026-07-25T10:00:00+08:00"
    ) == 0
    assert post["collection_status"] == "RESTRICTED"


def test_browser_p0_completeness_distinguishes_missing_from_known_empty_hashtags():
    from collectors.douyin import DouyinCollector

    empty_title = dict(AWEME, desc="", text_extra=[])
    known_no_hashtags = dict(AWEME, desc="无话题但完整", text_extra=[])
    unknown_hashtags = dict(AWEME, desc="无话题且标签字段缺失")

    empty_title_post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(
            ACCOUNT_URL,
            dict(empty_title, _collection_source="network"),
            source="network",
        )
    )
    known_empty_post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(
            ACCOUNT_URL,
            dict(known_no_hashtags, _collection_source="network"),
            source="network",
        )
    )
    unknown_hashtags_post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(
            ACCOUNT_URL,
            dict(unknown_hashtags, _collection_source="network"),
            source="network",
        )
    )

    assert empty_title_post["collection_status"] == "PARTIAL"
    assert empty_title_post["platform_metrics"]["missing_detail_fields"] == [
        "title"
    ]
    assert known_empty_post["collection_status"] == "SUCCESS"
    assert known_empty_post["hashtags"] == []
    assert known_empty_post["platform_metrics"]["missing_detail_fields"] == []
    assert unknown_hashtags_post["collection_status"] == "PARTIAL"
    assert unknown_hashtags_post["platform_metrics"]["missing_detail_fields"] == [
        "hashtags"
    ]


def test_trusted_raw_image_text_does_not_require_duration_or_detail_request():
    import collect
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    post = collector._normalized_posts_from_items(
        ACCOUNT_URL,
        [{
            "aweme_id": "7001",
            "aweme_type": 68,
            "desc": "完整图文作品",
            "create_time": 1700000000,
            "images": [{"url_list": ["https://p.example/image.jpeg"]}],
            "text_extra": [],
            "_collection_source": "network",
        }],
        "network",
    )[0]
    collector.collect_post_detail = lambda _url: pytest.fail(
        "trusted image-text duration is not applicable"
    )

    unavailable = collect._enrich_douyin_details(
        collector, [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post["content_type"] == "image_text"
    assert post["duration_seconds"] is None
    assert post["collection_status"] == "SUCCESS"
    assert post["platform_metrics"]["detail_status"] == "NOT_NEEDED"
    assert "p.example" not in json.dumps(post, ensure_ascii=False)


@pytest.mark.parametrize(
    "invalid_images",
    [
        [{"junk": "x"}],
        [{"url_list": []}],
        [{"url_list": [""]}],
        [{"url_list": [123]}],
        [{"url_list": ["https://p.example/valid.jpeg", 123]}],
        [
            {"url_list": ["https://p.example/valid.jpeg"]},
            {"junk": "mixed-invalid-item"},
        ],
    ],
)
def test_malformed_image_evidence_cannot_grant_duration_not_applicable(
    invalid_images,
):
    from collectors.douyin import DouyinCollector

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(
            ACCOUNT_URL,
            {
                "aweme_id": "7001",
                "aweme_type": 68,
                "desc": "伪图文证据",
                "create_time": 1700000000,
                "images": invalid_images,
                "text_extra": [],
                "_collection_source": "network",
            },
            source="network",
        )
    )

    assert post["content_type"] == "video"
    assert post["duration_seconds"] is None
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["missing_detail_fields"] == [
        "duration_seconds"
    ]


def test_video_aweme_cannot_claim_image_text_from_images_or_external_content_type():
    import collect
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    post = collector._normalized_posts_from_items(
        ACCOUNT_URL,
        [{
            "aweme_id": "7001",
            "aweme_type": 0,
            "desc": "视频作品",
            "create_time": 1700000000,
            "images": [{"url_list": ["https://p.example/cover.jpeg"]}],
            "text_extra": [],
            "_collection_source": "network",
        }],
        "network",
    )[0]
    assert post["content_type"] == "video"
    post["content_type"] = "image_text"
    collector.collect_post_detail = lambda _url: {
        "post_id": "7001",
        "duration_seconds": 2,
    }

    unavailable = collect._enrich_douyin_details(
        collector, [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post["duration_seconds"] == 2
    assert post["collection_status"] == "SUCCESS"


def test_legacy_image_text_without_transient_evidence_never_upgrades():
    import collect

    class CompleteDetailAdapter:
        def collect_post_detail(self, _url):
            return {"post_id": "7001", "duration_seconds": 2}

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/note/7001",
        "content_type": "image_text",
        "title": "旧图文",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": None,
        "hashtags": [],
        "collection_status": "PARTIAL",
        "platform_metrics": {"collection_source": "network"},
    }

    unavailable = collect._enrich_douyin_details(
        CompleteDetailAdapter(), [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post["duration_seconds"] == 2
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["partial_reasons"] == ["other_partial"]


@pytest.mark.parametrize(
    ("field", "invalid_value", "replacement"),
    [
        ("published_at", "definitely-not-an-iso-date", "2026-07-20T10:00:00+08:00"),
        ("duration_seconds", 1.5, 1),
        ("hashtags", [""], ["有效话题"]),
    ],
)
def test_detail_enrichment_rejects_structurally_invalid_nonempty_p0_values(
    field, invalid_value, replacement
):
    import collect

    class StrictDetailAdapter:
        def collect_post_detail(self, _post_url):
            detail = {
                "post_id": "7001",
                "title": "可靠标题",
                "published_at": "2026-07-20T10:00:00+08:00",
                "duration_seconds": 1,
                "hashtags": ["有效话题"],
            }
            detail[field] = replacement
            return detail

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": "可靠标题",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": 1,
        "hashtags": ["有效话题"],
        "collection_status": "SUCCESS",
        "platform_metrics": {"collection_source": "list"},
    }
    post[field] = invalid_value

    unavailable = collect._enrich_douyin_details(
        StrictDetailAdapter(), [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post[field] == replacement
    assert post["collection_status"] == "SUCCESS"
    assert post["platform_metrics"]["detail_status"] == "SUCCESS"


def test_zero_duration_and_observed_empty_hashtags_are_complete_p0_values():
    import collect

    class MustNotRun:
        def collect_post_detail(self, _post_url):
            pytest.fail("zero duration and [] hashtags are complete evidence")

    post = {
        "platform": "douyin",
        "post_id": "7001",
        "post_url": "https://www.douyin.com/video/7001",
        "content_type": "video",
        "title": "可靠标题",
        "published_at": "2026-07-20T10:00:00+08:00",
        "duration_seconds": 0,
        "hashtags": [],
        "collection_status": "SUCCESS",
        "platform_metrics": {"collection_source": "list"},
    }

    assert collect._enrich_douyin_details(
        MustNotRun(), [post], [], "2026-07-25T10:00:00+08:00"
    ) == 0
    assert post["platform_metrics"]["detail_status"] == "NOT_NEEDED"


def test_ssr_builder_absent_hashtag_evidence_survives_normalization_for_enrichment():
    import collect
    from collectors.douyin import DouyinCollector

    collector = DouyinCollector()
    post = collector._normalized_posts_from_items(
        ACCOUNT_URL,
        [{
            "aweme_id": "7001",
            "desc": "没有话题字段的 SSR 文案",
            "create_time": 1700000000,
            "video": {"duration": 9000},
            "_collection_source": "list",
        }],
        "list",
    )[0]
    collector.collect_post_detail = lambda _post_url: {
        "post_id": "7001",
        "hashtags": ["详情话题"],
    }

    unavailable = collect._enrich_douyin_details(
        collector, [post], [], "2026-07-25T10:00:00+08:00"
    )

    assert unavailable == 0
    assert post["hashtags"] == ["详情话题"]
    assert post["platform_metrics"]["detail_status"] == "SUCCESS"


@pytest.mark.parametrize(
    "invalid_text_extra",
    [[None], ["not-a-structure"], [{}], [{"hashtag_name": ""}]],
)
def test_malformed_text_extra_does_not_prove_an_observed_empty_hashtag_list(
    invalid_text_extra,
):
    from collectors.douyin import DouyinCollector

    aweme = dict(
        AWEME,
        desc="没有话题的公开文案",
        text_extra=invalid_text_extra,
        _collection_source="network",
    )

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, aweme, source="network")
    )

    assert post["hashtags"] == []
    assert post["collection_status"] == "PARTIAL"
    assert post["platform_metrics"]["missing_detail_fields"] == ["hashtags"]


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_post_metrics_become_unknown_without_losing_explicit_zero(nonfinite):
    from collectors.douyin import DouyinCollector

    aweme = dict(
        AWEME,
        text_extra=[],
        statistics={
            "play_count": 0,
            "digg_count": nonfinite,
            "comment_count": nonfinite,
            "collect_count": nonfinite,
            "share_count": nonfinite,
        },
        _collection_source="network",
    )

    post = DouyinCollector().normalize_post(
        DouyinCollector._build_post_raw(ACCOUNT_URL, aweme, source="network")
    )

    assert post["views"] == 0
    assert post["likes"] is None
    assert post["comments"] is None
    assert post["favorites"] is None
    assert post["shares"] is None
