"""Collection CLI, budget, and workspace boundary contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import collect
import collect_douyin_authorized as authorized
from collectors import _constants
from collectors.base import BaseCollector


DOUYIN_URL = "https://www.douyin.com/user/example"
BILIBILI_URL = "https://space.bilibili.com/123"


class RecordingDouyinAdapter(BaseCollector):
    platform = "douyin"

    def __init__(self) -> None:
        self.network_calls: list[tuple] = []
        self.all_request: dict | None = None

    def supports(self, url):
        return True

    def check_access(self, url):
        self.network_calls.append(("check_access", url))
        return {"accessible": True}

    def collect_profile(self, url):
        self.network_calls.append(("collect_profile", url))
        return {"platform": "douyin", "field_visibility": {}}

    def collect_post_list(self, url, limit=30, date_range=None):
        self.network_calls.append(("collect_post_list", url, limit, date_range))
        return [self._post()]

    def collect_all_post_list(
        self,
        url,
        date_range=None,
        max_items=10_000,
        max_seconds=1_800.0,
        max_scrolls=2_000,
    ):
        self.network_calls.append(("collect_all_post_list", url))
        self.all_request = {
            "max_items": max_items,
            "max_seconds": max_seconds,
            "max_scrolls": max_scrolls,
        }
        return [self._post()]

    def get_collection_coverage(self):
        return {
            "requested_all": True,
            "is_exhaustive": True,
            "terminal_page_observed": True,
            "observed_page_count": 1,
            "observed_post_count": 1,
            "stop_condition": "terminal_page",
            "max_items": (self.all_request or {}).get("max_items"),
        }

    def collect_post_detail(self, post_url):
        return {}

    @staticmethod
    def _post():
        return {
            "platform": "douyin",
            "post_id": "7001",
            "post_url": "https://www.douyin.com/video/7001",
            "source_url": "https://www.douyin.com/video/7001",
            "collection_status": "SUCCESS",
        }


class RecordingBilibiliAdapter(BaseCollector):
    platform = "bilibili"

    def __init__(self) -> None:
        self.network_calls: list[tuple] = []

    def supports(self, url):
        return True

    def check_access(self, url):
        self.network_calls.append(("check_access", url))
        return {"accessible": True}

    def collect_profile(self, url):
        self.network_calls.append(("collect_profile", url))
        return {"platform": "bilibili", "field_visibility": {}}

    def collect_post_list(self, url, limit=30, date_range=None):
        self.network_calls.append(("collect_post_list", url, limit, date_range))
        return [{
            "platform": "bilibili",
            "post_id": "BV1Contract",
            "bvid": "BV1Contract",
            "post_url": "https://www.bilibili.com/video/BV1Contract",
            "source_url": "https://www.bilibili.com/video/BV1Contract",
            "collection_status": "SUCCESS",
        }]

    def collect_post_detail(self, post_url):
        return {}


def _must_not_run(*args, **kwargs):
    pytest.fail("run must not be called for an argparse contract error")


def _must_not_load_adapters(*args, **kwargs):
    pytest.fail("adapter loading must not happen before argument validation")


def test_shared_public_budget_defaults_and_hard_caps_are_exact():
    assert _constants.PUBLIC_ALL_DEFAULT_MAX_ITEMS == 10_000
    assert _constants.PUBLIC_ALL_DEFAULT_MAX_SECONDS == 1_800.0
    assert _constants.PUBLIC_ALL_DEFAULT_MAX_SCROLLS == 2_000
    assert _constants.PUBLIC_ALL_HARD_MAX_ITEMS == 50_000
    assert _constants.PUBLIC_ALL_HARD_MAX_SECONDS == 14_400.0
    assert _constants.PUBLIC_ALL_HARD_MAX_SCROLLS == 20_000


def test_all_accepts_exact_hard_caps_and_persists_one_effective_item_budget(
    monkeypatch, tmp_path
):
    adapter = RecordingDouyinAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    rc = collect.run(
        DOUYIN_URL,
        out_dir=str(out),
        collect_all=True,
        max_items=50_000,
        max_seconds=14_400.0,
        max_scrolls=20_000,
    )

    assert rc == 0
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert adapter.all_request == {
        "max_items": 50_000,
        "max_seconds": 14_400.0,
        "max_scrolls": 20_000,
    }
    assert task["requested_limit"] == 50_000
    assert task["collection_coverage"]["max_items"] == 50_000


def test_all_access_failure_still_persists_the_accepted_item_budget(
    monkeypatch, tmp_path
):
    class RestrictedAdapter(RecordingDouyinAdapter):
        def check_access(self, url):
            self.network_calls.append(("check_access", url))
            return {"accessible": False, "stop_reason": "ACCESS_RESTRICTED"}

    adapter = RestrictedAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(DOUYIN_URL, out_dir=str(out), collect_all=True) == 3

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["requested_limit"] == 10_000
    assert task["collection_coverage"]["requested_all"] is True
    assert task["collection_coverage"]["max_items"] == 10_000
    assert adapter.all_request is None


def test_all_collection_failure_cannot_drop_the_accepted_item_budget(
    monkeypatch, tmp_path
):
    from collectors.douyin import DouyinError

    class FailedAdapter(RecordingDouyinAdapter):
        def collect_all_post_list(self, url, **kwargs):
            self.all_request = dict(kwargs)
            raise DouyinError("PARSER_FAILED", "bounded failure")

        def get_collection_coverage(self):
            return {}

    adapter = FailedAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        DOUYIN_URL,
        out_dir=str(out),
        collect_all=True,
        max_items=50_000,
    ) == 3

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["requested_limit"] == 50_000
    assert task["collection_coverage"]["requested_all"] is True
    assert task["collection_coverage"]["max_items"] == 50_000
    assert adapter.all_request["max_items"] == 50_000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": 0},
        {"max_items": -1},
        {"max_items": 50_001},
        {"max_items": 1.5},
        {"max_seconds": 0},
        {"max_seconds": -1},
        {"max_seconds": float("nan")},
        {"max_seconds": float("inf")},
        {"max_seconds": 14_400.1},
        {"max_scrolls": 0},
        {"max_scrolls": -1},
        {"max_scrolls": 20_001},
        {"max_scrolls": 1.5},
    ],
)
def test_direct_run_rejects_invalid_all_budgets_before_adapters_or_output(
    monkeypatch, tmp_path, kwargs
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)
    out = tmp_path / "task"

    assert collect.run(
        DOUYIN_URL,
        out_dir=str(out),
        collect_all=True,
        **kwargs,
    ) == 2
    assert not out.exists()


@pytest.mark.parametrize("limit", [0, -1, 101, 1.5, True])
def test_direct_run_rejects_invalid_limited_limits_before_adapters_or_output(
    monkeypatch, tmp_path, limit
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)
    out = tmp_path / "task"

    assert collect.run(BILIBILI_URL, limit=limit, out_dir=str(out)) == 2
    assert not out.exists()


def test_direct_run_rejects_nondefault_limit_with_all_before_adapters(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(
        DOUYIN_URL,
        limit=31,
        out_dir=str(tmp_path / "task"),
        collect_all=True,
    ) == 2


def test_direct_run_rejects_since_without_resume_before_adapters_or_output(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)
    out = tmp_path / "task"

    assert collect.run(BILIBILI_URL, out_dir=str(out), since="2026-07-01") == 2
    assert not out.exists()


def test_direct_run_rejects_invalid_since_before_adapters_or_workspace_mutation(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)
    out = tmp_path / "resume-target"
    out.mkdir()

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(out),
        resume=True,
        since="not-a-date",
    ) == 2
    assert list(out.iterdir()) == []


def test_direct_run_rejects_custom_all_budget_without_all_before_adapters(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(tmp_path / "task"),
        max_items=10_000,
    ) == 2


def test_all_and_explicit_limit_are_mutually_exclusive_at_cli(monkeypatch):
    monkeypatch.setattr(collect, "run", _must_not_run)
    monkeypatch.setattr(
        "sys.argv", ["collect.py", DOUYIN_URL, "--all", "--limit", "30"]
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "101"])
def test_limited_cli_rejects_out_of_range_limit_without_clamping(
    monkeypatch, value
):
    monkeypatch.setattr(collect, "run", _must_not_run)
    monkeypatch.setattr("sys.argv", ["collect.py", BILIBILI_URL, "--limit", value])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


def test_since_requires_resume_at_cli(monkeypatch):
    monkeypatch.setattr(collect, "run", _must_not_run)
    monkeypatch.setattr(
        "sys.argv", ["collect.py", BILIBILI_URL, "--since", "2026-07-01"]
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-items", "10000"),
        ("--max-seconds", "1800"),
        ("--max-scrolls", "2000"),
    ],
)
def test_custom_all_budget_requires_all_at_cli(monkeypatch, flag, value):
    monkeypatch.setattr(collect, "run", _must_not_run)
    monkeypatch.setattr("sys.argv", ["collect.py", BILIBILI_URL, flag, value])

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-items", "50001"),
        ("--max-seconds", "14400.1"),
        ("--max-seconds", "inf"),
        ("--max-scrolls", "20001"),
    ],
)
def test_all_cli_rejects_values_above_hard_caps(monkeypatch, flag, value):
    monkeypatch.setattr(collect, "run", _must_not_run)
    monkeypatch.setattr(
        "sys.argv", ["collect.py", DOUYIN_URL, "--all", flag, value]
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 2


def test_enrich_details_rejects_non_douyin_before_network_or_output(
    monkeypatch, tmp_path
):
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "task"

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(out),
        enrich_details=True,
    ) == 2
    assert adapter.network_calls == []
    assert not out.exists()


def test_new_public_task_rejects_nonempty_explicit_output_before_adapters(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    out.mkdir()
    marker = out / "keep.bin"
    marker.write_bytes(b"keep\x00this")
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert marker.read_bytes() == b"keep\x00this"
    assert [path.name for path in out.iterdir()] == ["keep.bin"]


def test_new_public_task_rejects_empty_explicit_output_before_adapters(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    out.mkdir()
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert out.is_dir()
    assert list(out.iterdir()) == []


def test_resume_requires_existing_source_without_adapter_or_mutation(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    out.mkdir()
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(BILIBILI_URL, out_dir=str(out), resume=True) == 2
    assert out.is_dir()
    assert list(out.iterdir()) == []


def test_resume_validates_existing_target_and_source_without_ownership(tmp_path):
    out = tmp_path / "task"
    (out / "source").mkdir(parents=True)

    reservation = collect._prepare_explicit_workspace(str(out), resume=True)
    try:
        assert reservation.owned_target is False
        assert reservation.owned_source is False
        reservation.verify()
    finally:
        reservation.close()


def test_explicit_reservation_source_failure_removes_empty_owned_target(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    adapter = RecordingBilibiliAdapter()
    original_mkdir = collect.os.mkdir

    def fail_source_mkdir(path, *args, **kwargs):
        if os.fspath(path) == "source" or Path(path).name == "source":
            raise OSError("injected source setup failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(collect.os, "mkdir", fail_source_mkdir)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert not out.exists()
    assert adapter.network_calls == []


def test_explicit_reservation_source_failure_preserves_concurrent_marker(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    marker_bytes = b"concurrent owner\x00must survive"
    adapter = RecordingBilibiliAdapter()
    original_mkdir = collect.os.mkdir

    def fail_source_after_marker(path, *args, **kwargs):
        if os.fspath(path) == "source" or Path(path).name == "source":
            (out / "marker.bin").write_bytes(marker_bytes)
            raise OSError("injected source setup failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(collect.os, "mkdir", fail_source_after_marker)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert (out / "marker.bin").read_bytes() == marker_bytes
    assert [path.name for path in out.iterdir()] == ["marker.bin"]
    assert adapter.network_calls == []


def test_explicit_reservation_stat_failure_removes_empty_owned_target(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    adapter = RecordingBilibiliAdapter()
    original_stat = collect.os.stat
    failed = False

    def fail_first_target_stat(path, *args, **kwargs):
        nonlocal failed
        if (
            not failed
            and os.fspath(path) == out.name
            and kwargs.get("dir_fd") is not None
            and kwargs.get("follow_symlinks") is False
        ):
            failed = True
            raise OSError("injected target stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(collect.os, "stat", fail_first_target_stat)
    monkeypatch.setattr(collect, "_dir_fd_reservations_available", lambda: True)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert failed is True
    assert not out.exists()
    assert adapter.network_calls == []


def test_public_setup_identity_replacement_is_left_untouched(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    displaced = tmp_path / "displaced-owned-task"
    adapter = RecordingBilibiliAdapter()
    original_mkdir = collect.os.mkdir
    swapped = False

    def swap_target_after_source_mkdir(path, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(path, *args, **kwargs)
        if not swapped and (os.fspath(path) == "source" or Path(path).name == "source"):
            swapped = True
            out.rename(displaced)
            original_mkdir(str(out))
        return result

    monkeypatch.setattr(collect.os, "mkdir", swap_target_after_source_mkdir)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert swapped is True
    assert out.is_dir()
    assert list(out.iterdir()) == []
    assert displaced.is_dir()
    assert adapter.network_calls == []


def test_public_reservation_identity_swap_aborts_before_artifact_mutation(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    displaced = tmp_path / "displaced-owned-task"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.bin"
    marker.write_bytes(b"outside\x00must survive")

    class SwappingAdapter(RecordingBilibiliAdapter):
        def collect_profile(self, url):
            self.network_calls.append(("collect_profile", url))
            (out / "source").rename(displaced)
            (out / "source").symlink_to(outside, target_is_directory=True)
            return {"platform": "bilibili", "field_visibility": {}}

    adapter = SwappingAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert marker.read_bytes() == b"outside\x00must survive"
    assert sorted(path.name for path in outside.iterdir()) == ["keep.bin"]
    assert displaced.is_dir()


def test_public_reservation_falls_back_when_dir_fd_operations_are_unsupported(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = RecordingBilibiliAdapter()
    original_mkdir = collect.os.mkdir
    original_open = collect.os.open

    def mkdir_without_dir_fd(path, *args, **kwargs):
        if "dir_fd" in kwargs:
            raise TypeError("dir_fd unsupported")
        return original_mkdir(path, *args, **kwargs)

    def open_without_dir_fd(path, *args, **kwargs):
        if "dir_fd" in kwargs:
            raise NotImplementedError("openat unsupported")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))
    monkeypatch.setattr(collect.os, "mkdir", mkdir_without_dir_fd)
    monkeypatch.setattr(collect.os, "open", open_without_dir_fd)
    monkeypatch.setattr(collect, "_dir_fd_reservations_available", lambda: True)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL) == 0
    tasks = list((repo / "workspace").glob("bilibili-123-*"))
    assert len(tasks) == 1
    assert (tasks[0] / "source" / "posts.jsonl").is_file()


def test_public_reservation_without_no_follow_fails_closed_on_workspace_symlink(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.bin"
    marker.write_bytes(b"outside\x00must survive")
    (repo / "workspace").symlink_to(outside, target_is_directory=True)
    adapter = RecordingBilibiliAdapter()

    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))
    monkeypatch.delattr(collect.os, "O_NOFOLLOW", raising=False)
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL) == 2
    assert marker.read_bytes() == b"outside\x00must survive"
    assert sorted(path.name for path in outside.iterdir()) == ["keep.bin"]
    assert adapter.network_calls == []


def test_default_public_output_uses_repository_workspace(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL) == 0

    tasks = list((repo / "workspace").glob("bilibili-123-*"))
    assert len(tasks) == 1
    assert (tasks[0] / "task.json").is_file()
    assert not (repo / "skill" / "workspace").exists()


def test_default_reservation_creates_source_before_returning(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))

    reservation = collect._reserve_default_workspace("account-20260725")
    try:
        reserved_path = Path(os.fspath(reservation))
        assert reserved_path.is_dir()
        assert (reserved_path / "source").is_dir()
    finally:
        close = getattr(reservation, "close", None)
        if close is not None:
            close()


def test_default_public_tasks_for_same_account_and_day_are_independent(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL) == 0
    assert collect.run(BILIBILI_URL) == 0

    tasks = sorted((repo / "workspace").glob("bilibili-123-*"))
    assert len(tasks) == 2
    assert tasks[0] != tasks[1]
    assert all((task / "task.json").is_file() for task in tasks)


def test_default_public_output_skips_symlink_collision_without_following_it(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    workspace = repo / "workspace"
    workspace.mkdir(parents=True)
    date = collect.datetime.now(collect._BEIJING).strftime("%Y%m%d")
    base = workspace / f"bilibili-123-{date}"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    base.symlink_to(outside, target_is_directory=True)
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(BILIBILI_URL) == 0

    assert marker.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in outside.iterdir()) == ["keep.txt"]
    suffixes = [path for path in workspace.glob(f"{base.name}-*") if path.is_dir()]
    assert len(suffixes) == 1
    assert (suffixes[0] / "task.json").is_file()


class AuthorizedClient:
    def collect_profile(self):
        return {
            "platform": "douyin",
            "profile_url": "https://open.douyin.com/oauth/userinfo/",
            "field_visibility": {},
        }

    def collect_video_pages(self, *, limit, page_size):
        return [], {
            "requested_all": limit is None,
            "is_exhaustive": True,
            "terminal_page_observed": True,
            "observed_page_count": 1,
            "observed_post_count": 0,
            "repeated_cursor_count": 0,
            "zero_new_page_count": 0,
            "stop_condition": "terminal_page",
        }


def test_authorized_default_output_uses_repository_workspace(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    fake_file = repo / "skill" / "scripts" / "collect_douyin_authorized.py"
    monkeypatch.setattr(authorized, "__file__", str(fake_file))

    assert authorized.run(
        environ={"DOUYIN_OPENAPI_ACCESS_TOKEN": "test-token"},
        client=AuthorizedClient(),
    ) == 0

    tasks = list((repo / "workspace").glob("douyin-authorized-*"))
    assert len(tasks) == 1
    assert (tasks[0] / "task.json").is_file()
    assert not (repo / "skill" / "workspace").exists()


def test_schema_and_design_state_exact_budget_and_output_contracts():
    root = Path(__file__).resolve().parents[1]
    schema = (root / "skill/references/data-schema.md").read_text(encoding="utf-8")
    design = (
        root / "docs/superpowers/specs/2026-07-24-douyin-complete-collection-design.md"
    ).read_text(encoding="utf-8")
    contract = schema + "\n" + design

    for value in ("50,000", "14,400", "20,000"):
        assert value in contract
    assert "仓库根目录" in schema
    assert "非空" in schema
    assert "原子" in schema
    assert "max_items" in schema
