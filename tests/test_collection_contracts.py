"""Collection CLI, budget, and workspace boundary contracts."""

from __future__ import annotations

import json
import hashlib
import os
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import collect
import collect_douyin_authorized as authorized
import immutable_workspace as immutable
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


def test_direct_run_rejects_resume_out_without_resume_before_any_mutation(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)
    out = tmp_path / "task"

    assert collect.run(
        BILIBILI_URL, resume_out=str(out)
    ) == 2
    assert not out.exists()


def test_resume_rejects_same_source_and_destination_before_adapters(
    monkeypatch, tmp_path
):
    old = tmp_path / "old"
    (old / "source").mkdir(parents=True)
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(old),
        resume=True,
        resume_out=str(old),
    ) == 2
    assert list(old.iterdir()) == [old / "source"]


def test_resume_rejects_occupied_explicit_destination_before_adapters(
    monkeypatch, tmp_path
):
    old = tmp_path / "old"
    (old / "source").mkdir(parents=True)
    destination = tmp_path / "destination"
    destination.mkdir()
    marker = destination / "keep.bin"
    marker.write_bytes(b"keep\x00bytes")
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(old),
        resume=True,
        resume_out=str(destination),
    ) == 2
    assert marker.read_bytes() == b"keep\x00bytes"


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


def test_resume_out_requires_resume_at_cli(monkeypatch):
    monkeypatch.setattr(collect, "run", _must_not_run)
    monkeypatch.setattr(
        "sys.argv",
        ["collect.py", BILIBILI_URL, "--resume-out", "new-task"],
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


def test_public_leaf_conflict_is_create_only_and_preserves_concurrent_bytes(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    concurrent_bytes = b"concurrent profile\x00must-survive"

    class ConflictingAdapter(RecordingBilibiliAdapter):
        def collect_profile(self, url):
            (out / "source" / "profile.json").write_bytes(concurrent_bytes)
            return super().collect_profile(url)

    monkeypatch.setattr(collect, "_load_adapters", lambda: [ConflictingAdapter()])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert (out / "source" / "profile.json").read_bytes() == concurrent_bytes
    assert not (out / ".complete").exists()


def test_public_workspace_swap_preserves_replacement_and_leaves_it_uncommitted(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    displaced = tmp_path / "displaced-task"
    replacement_bytes = b"replacement\x00must-survive"

    class SwappingAdapter(RecordingBilibiliAdapter):
        def collect_profile(self, url):
            out.rename(displaced)
            out.mkdir()
            (out / "replacement.bin").write_bytes(replacement_bytes)
            return super().collect_profile(url)

    monkeypatch.setattr(collect, "_load_adapters", lambda: [SwappingAdapter()])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert (out / "replacement.bin").read_bytes() == replacement_bytes
    assert not (out / ".complete").exists()
    assert not (displaced / ".complete").exists()


def test_public_preexisting_complete_marker_is_never_overwritten(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    marker_bytes = b"concurrent marker\x00must-survive"

    class MarkerAdapter(RecordingBilibiliAdapter):
        def collect_profile(self, url):
            (out / ".complete").write_bytes(marker_bytes)
            return super().collect_profile(url)

    monkeypatch.setattr(collect, "_load_adapters", lambda: [MarkerAdapter()])

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert (out / ".complete").read_bytes() == marker_bytes


def test_public_missing_backend_fails_before_workspace_or_network(
    monkeypatch, tmp_path
):
    adapter = RecordingBilibiliAdapter()
    out = tmp_path / "task"
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    monkeypatch.setattr(immutable, "_backend_kind", lambda: "unsupported")

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 2
    assert not out.exists()
    assert adapter.network_calls == []


def test_resume_rejects_symlinked_posts_before_adapter_loading(
    monkeypatch, tmp_path
):
    out = tmp_path / "task"
    source = out / "source"
    source.mkdir(parents=True)
    victim = tmp_path / "victim.jsonl"
    victim_bytes = b'{"post_id":"OUTSIDE"}\n'
    victim.write_bytes(victim_bytes)
    (source / "posts.jsonl").symlink_to(victim)
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)

    assert collect.run(BILIBILI_URL, out_dir=str(out), resume=True) == 2
    assert victim.read_bytes() == victim_bytes


@pytest.mark.skipif(not Path("/dev/fd").is_dir(), reason="requires /dev/fd")
@pytest.mark.parametrize("exception_type", [TypeError, RuntimeError])
def test_serialization_failures_are_sanitized_and_do_not_leak_reservation_fds(
    monkeypatch, tmp_path, capsys, exception_type
):
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    original_dump = collect.json.dump

    def fail_profile_dump(value, handle, *args, **kwargs):
        if isinstance(value, dict) and value.get("platform") == "bilibili":
            raise exception_type("SECRET_SERIALIZATION_FAILURE")
        return original_dump(value, handle, *args, **kwargs)

    monkeypatch.setattr(collect.json, "dump", fail_profile_dump)
    before = len(list(Path("/dev/fd").iterdir()))

    results = [
        collect.run(BILIBILI_URL, out_dir=str(tmp_path / f"task-{index}"))
        for index in range(20)
    ]

    after = len(list(Path("/dev/fd").iterdir()))
    captured = capsys.readouterr()
    assert all(result in {2, 3} for result in results)
    assert after <= before + 2
    assert list(tmp_path.rglob(".*.tmp")) == []
    assert "SECRET_SERIALIZATION_FAILURE" not in captured.out + captured.err


@pytest.mark.parametrize("access_failure", [False, True])
def test_public_indeterminate_commit_has_dedicated_sanitized_exit_and_closes_handles(
    monkeypatch, tmp_path, capsys, access_failure
):
    class Adapter(RecordingBilibiliAdapter):
        def check_access(self, url):
            if access_failure:
                return {
                    "accessible": False,
                    "stop_reason": "ACCESS_RESTRICTED",
                }
            return super().check_access(url)

    secret = "SECRET_PUBLIC_INDETERMINATE_CAUSE"
    held_descriptors = []

    def fail_indeterminate(self):
        held_descriptors.extend(
            owned.descriptor for owned in self._leaves.values()
        )
        if self.posix_chain is not None:
            held_descriptors.extend(
                entry.descriptor for entry in self.posix_chain.entries
            )
        try:
            raise OSError(secret)
        except OSError as cause:
            raise immutable.WorkspaceCommitIndeterminate() from cause

    monkeypatch.setattr(collect, "_load_adapters", lambda: [Adapter()])
    monkeypatch.setattr(immutable.ImmutableWorkspace, "commit", fail_indeterminate)
    out = tmp_path / "task"

    rc = collect.run(BILIBILI_URL, out_dir=str(out))

    assert rc == 4
    assert held_descriptors
    for descriptor in held_descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    captured = capsys.readouterr()
    assert captured.err == (
        "[INDETERMINATE] 输出目录可能已有可见提交，但持久化或最终验证未确认；"
        "请保留目录并重新核验\n"
    )
    assert secret not in captured.out + captured.err
    assert out.is_dir()


@pytest.mark.parametrize("control_flow", [KeyboardInterrupt, SystemExit])
def test_public_serialization_preserves_base_exception_control_flow(
    monkeypatch, tmp_path, control_flow
):
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    def interrupt_profile_dump(value, handle, *args, **kwargs):
        raise control_flow("CONTROL_FLOW_SENTINEL")

    monkeypatch.setattr(collect.json, "dump", interrupt_profile_dump)

    with pytest.raises(control_flow, match="CONTROL_FLOW_SENTINEL"):
        collect.run(BILIBILI_URL, out_dir=str(tmp_path / "task"))

    assert list(tmp_path.rglob(".*.tmp")) == []


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


def test_public_task_persists_unique_task_id_and_analysis_goal(
    monkeypatch, tmp_path
):
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert collect.run(
        BILIBILI_URL, out_dir=str(first), analysis_goal="分析选题节奏"
    ) == 0
    assert collect.run(
        BILIBILI_URL, out_dir=str(second), analysis_goal="分析选题节奏"
    ) == 0

    first_task = json.loads((first / "task.json").read_text(encoding="utf-8"))
    second_task = json.loads((second / "task.json").read_text(encoding="utf-8"))
    assert first_task["analysis_goal"] == "分析选题节奏"
    assert isinstance(first_task["task_id"], str) and first_task["task_id"]
    assert first_task["task_id"] != second_task["task_id"]


def test_public_persistence_deduplicates_before_limit_and_keeps_counts_aligned(
    monkeypatch, tmp_path
):
    class BoundaryDuplicateAdapter(RecordingBilibiliAdapter):
        def collect_post_list(self, url, limit=30, date_range=None):
            posts = []
            for index in range(30):
                post_id = f"BVboundary{index:02d}"
                posts.append({
                    "platform": "bilibili",
                    "post_id": post_id,
                    "post_url": f"https://www.bilibili.com/video/{post_id}",
                    "source_url": f"https://www.bilibili.com/video/{post_id}",
                    "collection_status": "SUCCESS",
                })
            posts.insert(20, dict(posts[19]))
            return posts

    adapter = BoundaryDuplicateAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "deduplicated-task"

    assert collect.run(BILIBILI_URL, limit=30, out_dir=str(out)) == 0

    jsonl_rows = [
        json.loads(line)
        for line in (out / "source" / "posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    with (out / "normalized-posts.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        csv_rows = list(csv.DictReader(handle))
    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    report = (out / "collection-report.md").read_text(encoding="utf-8")

    assert len(jsonl_rows) == 30
    assert len({(row["platform"], row["post_id"]) for row in jsonl_rows}) == 30
    assert len(csv_rows) == 30
    assert task["collected_count"] == 30
    assert "- 内容条数: 30" in report
    assert "- 成功采集内容数: 30" in report


def test_collection_coverage_preserves_bilibili_substage_ledger_only():
    clean = collect._sanitize_collection_coverage({
        "regular_source": "medialist",
        "regular_observed_count": 29,
        "dynamic_status": "ACCESS_RESTRICTED",
        "dynamic_observed_count": 0,
        "raw_response": "must-not-persist",
        "offset": "must-not-persist",
    })

    assert clean["regular_source"] == "medialist"
    assert clean["regular_observed_count"] == 29
    assert clean["dynamic_status"] == "ACCESS_RESTRICTED"
    assert clean["dynamic_observed_count"] == 0
    assert "raw_response" not in clean
    assert "offset" not in clean


def test_public_task_persists_structured_execution_timing(monkeypatch, tmp_path):
    adapter = RecordingBilibiliAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "timed-task"

    assert collect.run(BILIBILI_URL, out_dir=str(out)) == 0

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    started_at = datetime.fromisoformat(task["started_at"])
    ended_at = datetime.fromisoformat(task["ended_at"])
    assert started_at.tzinfo is not None
    assert ended_at.tzinfo is not None
    assert ended_at >= started_at
    assert isinstance(task["duration_ms"], int)
    assert task["duration_ms"] >= 0
    assert {
        "check_access",
        "collect_post_list",
        "collect_profile",
        "persist",
    }.issubset(task["phase_durations_ms"])
    assert all(
        isinstance(duration_ms, int) and duration_ms >= 0
        for duration_ms in task["phase_durations_ms"].values()
    )


def test_access_failure_still_persists_structured_execution_timing(
    monkeypatch, tmp_path
):
    class RestrictedAdapter(RecordingDouyinAdapter):
        def check_access(self, url):
            return {"accessible": False, "stop_reason": "ACCESS_RESTRICTED"}

    monkeypatch.setattr(collect, "_load_adapters", lambda: [RestrictedAdapter()])
    out = tmp_path / "timed-access-failure"

    assert collect.run(DOUYIN_URL, out_dir=str(out)) == 3

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "FAILED"
    assert task["phase_durations_ms"].keys() >= {"check_access", "persist"}
    assert task["duration_ms"] >= 0


@pytest.mark.parametrize(
    "goal",
    [123, "", "   ", "x" * 501, "分析\n注入", "分析\x00注入"],
)
def test_public_rejects_invalid_analysis_goal_before_network_or_output(
    monkeypatch, tmp_path, goal
):
    monkeypatch.setattr(collect, "_load_adapters", _must_not_load_adapters)
    out = tmp_path / "task"

    assert collect.run(BILIBILI_URL, out_dir=str(out), analysis_goal=goal) == 2
    assert not out.exists()


def test_public_cli_forwards_analysis_goal(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(collect, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["collect.py", BILIBILI_URL, "--analysis-goal", "分析互动表现"],
    )

    with pytest.raises(SystemExit) as exc_info:
        collect.main()

    assert exc_info.value.code == 0
    assert captured["analysis_goal"] == "分析互动表现"


def test_default_douyin_output_hashes_the_canonical_sec_uid(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = RecordingDouyinAdapter()
    sec_uid = "MS4wLjABAAAAstable123"
    url = f"https://www.douyin.com/user/{sec_uid}"
    expected = hashlib.sha256(sec_uid.encode("utf-8")).hexdigest()[:12]
    monkeypatch.setattr(collect, "_HERE", str(repo / "skill" / "scripts"))
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])

    assert collect.run(url) == 0

    tasks = list((repo / "workspace").glob(f"douyin-{expected}-*"))
    assert len(tasks) == 1
    assert not list((repo / "workspace").glob("douyin-4-*"))


def test_public_task_preserves_comment_platform_protection_reason(
    monkeypatch, tmp_path
):
    from collectors.bilibili import BilibiliError, STOP_VERIFICATION

    class VerificationCommentAdapter(RecordingBilibiliAdapter):
        def __init__(self):
            super().__init__()
            self.comment_calls = 0

        def collect_comments(self, post_url, limit=20):
            self.comment_calls += 1
            raise BilibiliError(STOP_VERIFICATION, "verification required")

    adapter = VerificationCommentAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "comment-protection"

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(out),
        include_comments=True,
    ) == 0

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == STOP_VERIFICATION
    assert adapter.comment_calls == 1


@pytest.mark.parametrize(
    ("existing", "candidate", "expected"),
    [
        (None, "VERIFICATION_REQUIRED", "VERIFICATION_REQUIRED"),
        ("PARSER_FAILED", "VERIFICATION_REQUIRED", "VERIFICATION_REQUIRED"),
        ("NO_PUBLIC_CONTENT", "ACCESS_RESTRICTED", "ACCESS_RESTRICTED"),
        ("LOGIN_REQUIRED", "VERIFICATION_REQUIRED", "LOGIN_REQUIRED"),
        ("PARSER_FAILED", "COMMENTS_UNAVAILABLE", "PARSER_FAILED"),
        (None, "COMMENTS_UNAVAILABLE", "COMMENTS_UNAVAILABLE"),
    ],
)
def test_dominant_stop_reason_prioritizes_task_protection(
    existing, candidate, expected
):
    assert collect._dominant_stop_reason(existing, candidate) == expected


def test_comment_protection_dominates_earlier_parser_failure(
    monkeypatch, tmp_path
):
    from collectors.bilibili import (
        BilibiliError,
        STOP_PARSER_FAILED,
        STOP_VERIFICATION,
    )

    class ParserThenVerificationAdapter(RecordingBilibiliAdapter):
        def collect_profile(self, url):
            self.network_calls.append(("collect_profile", url))
            raise BilibiliError(STOP_PARSER_FAILED, "profile parser failed")

        def collect_comments(self, post_url, limit=20):
            raise BilibiliError(STOP_VERIFICATION, "verification required")

    adapter = ParserThenVerificationAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    out = tmp_path / "parser-then-comment-protection"

    assert collect.run(
        BILIBILI_URL,
        out_dir=str(out),
        include_comments=True,
    ) == 0

    task = json.loads((out / "task.json").read_text(encoding="utf-8"))
    report = (out / "collection-report.md").read_text(encoding="utf-8")
    assert task["task_status"] == "PARTIAL"
    assert task["stop_reason"] == STOP_VERIFICATION
    assert task["comment_collection"]["stop_reason"] == STOP_VERIFICATION
    assert "error_code=PARSER_FAILED" in report
    assert "error_code=VERIFICATION_REQUIRED" in report


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
            "account_id": "test-open-id",
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
    monkeypatch.setattr(
        authorized,
        "DouyinOpenAPIClient",
        lambda access_token, open_id, transport=None: AuthorizedClient(),
    )

    assert authorized.run(
        environ={
            "DOUYIN_OPENAPI_ACCESS_TOKEN": "test-token",
            "DOUYIN_OPENAPI_OPEN_ID": "test-open-id",
        },
    ) == 0

    tasks = list((repo / "workspace").glob("douyin-authorized-*"))
    assert len(tasks) == 1
    assert (tasks[0] / "task.json").is_file()
    assert not (repo / "skill" / "workspace").exists()


def test_schema_states_exact_budget_and_output_contracts():
    root = Path(__file__).resolve().parents[1]
    schema = (root / "skill/references/data-schema.md").read_text(encoding="utf-8")

    for value in ("50,000", "14,400", "20,000"):
        assert value in schema
    assert "仓库根目录" in schema
    assert "非空" in schema
    assert "原子" in schema
    assert "max_items" in schema
