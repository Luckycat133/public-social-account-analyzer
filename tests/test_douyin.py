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

    assert collect.run(
        "https://v.douyin.com/AbC123/?token=SHORT_SECRET#SHORT_FRAGMENT_SECRET",
        out_dir=str(tmp_path),
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
    roadmap = (root / "TODO.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    module_text = (
        root / "skill/scripts/collectors/douyin.py"
    ).read_text(encoding="utf-8")
    docs = "\n".join((readme, usage, platform, skill, roadmap, changelog))

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
    assert "同时禁止 B站和抖音" in usage
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
        "desc": "列表页可靠标题 #列表话题",
        "create_time": None,
        "video": {},
    }
    duplicate = {
        "aweme_id": "7001",
        "desc": "后出现的冲突标题",
        "create_time": 1_700_000_000,
        "video": {"duration": 9_000},
    }
    invalid = {"desc": "没有 ID，不能以主页充当作品证据"}
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

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(tmp_path),
        enrich_details=True,
    ) == 0

    assert adapter.detail_calls == [
        "https://www.douyin.com/video/7001",
        "https://www.douyin.com/video/7003",
    ]
    posts = [
        json.loads(line)
        for line in (tmp_path / "source" / "posts.jsonl")
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
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert task["enrich_details"] is True
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] is None
    report = (tmp_path / "collection-report.md").read_text(encoding="utf-8")
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

    rc = collect.run(ACCOUNT_URL, limit=30, out_dir=str(tmp_path))

    assert rc == 0
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == "VERIFICATION_REQUIRED"
    rows = (tmp_path / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["post_id"] == "7001"
    report = (tmp_path / "collection-report.md").read_text(encoding="utf-8")
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


def test_all_rejects_non_douyin_urls_before_writing(monkeypatch, tmp_path):
    import collect

    class OtherAdapter(_AllDouyinAdapter):
        platform = "bilibili"

    monkeypatch.setattr(collect, "_load_adapters", lambda: [OtherAdapter()])

    rc = collect.run(
        "https://space.bilibili.com/1",
        out_dir=str(tmp_path),
        collect_all=True,
    )

    assert rc == 2
    assert not (tmp_path / "task.json").exists()


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

    monkeypatch.setattr(collect, "run", lambda *args, **kwargs: pytest.fail("must reject"))
    monkeypatch.setattr("sys.argv", ["collect.py", ACCOUNT_URL, "--all", flag, value])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


def test_all_terminal_page_writes_exhaustive_coverage(monkeypatch, tmp_path):
    import collect

    adapter = _AllDouyinAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    rc = collect.run(ACCOUNT_URL, out_dir=str(tmp_path), collect_all=True)

    assert rc == 0
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "COMPLETED"
    assert task["collection_coverage"]["is_exhaustive"] is True
    assert "raw_cursor" not in task["collection_coverage"]
    report = (tmp_path / "collection-report.md").read_text(encoding="utf-8")
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

    rc = collect.run(ACCOUNT_URL, out_dir=str(tmp_path), collect_all=True)

    assert rc == 0
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["collection_coverage"]["is_exhaustive"] is False
    assert task["collection_coverage"]["stop_condition"] == stop_condition
    rows = (tmp_path / "source" / "posts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1


def test_standard_limit_thirty_keeps_existing_collection_path(monkeypatch, tmp_path):
    import collect

    adapter = _AllDouyinAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(ACCOUNT_URL, limit=30, out_dir=str(tmp_path)) == 0
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

    assert collect.run(ACCOUNT_URL, out_dir=str(tmp_path), collect_all=True) == 0
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
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
            {"desc": "missing id"},
            {"aweme_id": "not-numeric", "desc": "invalid id"},
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
    monkeypatch, tmp_path
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

    assert collect.run(ACCOUNT_URL, out_dir=str(tmp_path), collect_all=True) == 3
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["stop_reason"] == STOP_NO_PUBLIC_CONTENT
    assert task["collection_coverage"]["is_exhaustive"] is True


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

    assert collect.run(
        ACCOUNT_URL,
        out_dir=str(tmp_path),
        collect_all=True,
        date_from="2030-01-01",
    ) == 0
    task = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
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
                        AWEME,
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


def test_collect_post_list_maps_recognized_empty_ssr_to_no_public_content(monkeypatch):
    """A real empty list is not a parser failure and does not start Chrome."""
    from collectors.douyin import DouyinCollector, DouyinError

    collector = DouyinCollector(
        browser_collect=lambda **kwargs: pytest.fail("recognized [] must not fallback")
    )
    monkeypatch.setattr(
        collector,
        "_fetch",
        lambda url: _ssr_html({"user": {"post": {"data": []}}}),
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
        "aweme_list": [AWEME],
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
        },
    },
}


def _response_event(request_id, *, host="www.douyin.com"):
    event = json.loads(json.dumps(RESPONSE_EVENT))
    event["params"]["requestId"] = request_id
    event["params"]["response"]["url"] = (
        f"https://{host}/aweme/v1/web/aweme/post/?signed=secret"
    )
    return event


def _loading_event(method, request_id):
    return {"method": method, "params": {"requestId": request_id}}


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

    listed = dict(AWEME, desc="列表文案", video={})
    enriched = dict(AWEME, desc="不同文案", video={"duration": 9000})
    payload = {
        "first": {"aweme_list": [listed], "has_more": True, "cursor": "alpha"},
        "second": {
            "post_list": [enriched],
            "has_more": False,
            "max_cursor": "secret-cursor",
        },
    }

    pages = extract_post_page_observations(payload)
    assert len(pages) == 2
    assert pages[1].items[0]["video"] == {"duration": 9000}

    browser = FakeBrowser(
        events=[_response_event("r1")],
        bodies={"r1": json.dumps(payload)},
    )
    result = collect_account_page(
        ACCOUNT_URL,
        limit=100,
        all_posts=True,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert [item["aweme_id"] for item in result.aweme_items] == ["7001"]
    assert result.coverage["is_exhaustive"] is True
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
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
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
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
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
            "aweme_list": [AWEME],
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

    browser = FakeBrowser(
        cards=[{"href": "https://www.douyin.com/video/7002?token=secret", "text": "作品二"}],
    )

    result = collect_account_page(
        "https://www.douyin.com/user/example",
        limit=1,
        session_factory=lambda: browser,
        sleep=lambda _: None,
    )

    assert result.source == "dom"
    assert result.aweme_items[0]["aweme_id"] == "7002"
    assert result.aweme_items[0]["share_url"] == "https://www.douyin.com/video/7002"


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
            },
        },
    }
    browser = FakeBrowser(
        events=[RESPONSE_EVENT, later_event],
        bodies={"r2": json.dumps({"aweme_list": [AWEME]})},
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
                bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
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
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
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
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
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
                "aweme_list": [AWEME],
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
                "aweme_list": [AWEME],
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
                        "aweme_list": [AWEME],
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

    old = dict(AWEME, aweme_id="6999", create_time=1_600_000_000)
    recent = dict(AWEME, aweme_id="7001", create_time=1_700_000_000)
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
        dict(AWEME, aweme_id="6998", create_time=1_600_000_000, is_top=True),
        dict(AWEME, aweme_id="6997", create_time=None),
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
        bodies={"r1": json.dumps({"aweme_list": [AWEME]})},
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
