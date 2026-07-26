"""Task 3C-B immutable derived-analysis pipeline contracts."""

from __future__ import annotations

import importlib
import hashlib
import json
import os
from pathlib import Path

import pytest

import analyze
import immutable_workspace as workspace
import normalize
import render_report


COLLECTION_ARTIFACTS = frozenset(
    {
        "source/profile.json",
        "source/posts.jsonl",
        "source/comments.jsonl",
        "source/index-evidence.json",
        "normalized-posts.csv",
        "task.json",
        "collection-report.md",
    }
)


def _sample_profile() -> dict:
    return {
        "platform": "douyin",
        "account_id": "account-1",
        "account_name": "示例账号",
        "profile_url": "https://www.douyin.com/user/example",
        "followers": 100,
    }


def _sample_post(post_id: str = "1") -> dict:
    return {
        "platform": "douyin",
        "post_id": post_id,
        "post_url": f"https://www.douyin.com/video/{post_id}",
        "published_at": "2026-01-01T08:00:00+08:00",
        "content_type": "video",
        "title": f"作品 {post_id}",
        "collection_status": "SUCCESS",
        "likes": 10,
        "comments": 2,
        "favorites": 1,
        "shares": 1,
        "views": 100,
    }


def _collection(
    tmp_path: Path,
    *,
    name: str = "collection",
    task_status: str = "COMPLETED",
    posts: list[dict] | None = None,
    include_posts: bool = True,
    extra_artifacts: dict[str, bytes] | None = None,
) -> tuple[Path, str]:
    target = tmp_path / name
    source_posts = [_sample_post()] if posts is None else posts
    artifacts = {
        "source/profile.json": json.dumps(
            _sample_profile(), ensure_ascii=False
        ).encode("utf-8"),
        "task.json": json.dumps(
            {
                "task_id": "douyin-source-task",
                "platform": "douyin",
                "task_status": task_status,
                "requested_limit": 1,
                "collected_count": len(source_posts),
                "analysis_goal": None,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        "collection-report.md": b"# collection\n",
    }
    if include_posts:
        artifacts["source/posts.jsonl"] = "".join(
            json.dumps(post, ensure_ascii=False) + "\n" for post in source_posts
        ).encode("utf-8")
    artifacts.update(extra_artifacts or {})
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts=COLLECTION_ARTIFACTS
    )
    try:
        for relative, payload in artifacts.items():
            with reservation.open_text(relative) as handle:
                handle.write(payload.decode("utf-8"))
        digest = reservation.commit()
    finally:
        reservation.close()
    return target, digest


def _normalized_rows() -> list[dict]:
    return [normalize.normalize_post(_sample_post())[0]]


def _minimal_template() -> str:
    return "<!doctype html><html><body>" + "".join(
        "{{" + name + "}}" for name in render_report.PLACEHOLDERS
    ) + "</body></html>"


def _classification(post_id: str = "1", **overrides) -> dict:
    result = {
        "post_id": post_id,
        "topic": "示例主题",
        "format": "tutorial",
        "funnel_stage": "education",
        "hook_type": "result_first",
        "series_name": None,
        "is_original": True,
        "has_product_placement": False,
        "analysis_labels": ["示例"],
        "classification_confidence": 0.9,
    }
    result.update(overrides)
    return result


def _pipeline_module():
    return importlib.import_module("run_pipeline")


def _tree_snapshot(path: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _legacy_analysis_dir(tmp_path: Path, *, bad_link: bool = False) -> Path:
    target = tmp_path / "legacy"
    (target / "source").mkdir(parents=True)
    rows = _normalized_rows()
    normalized = normalize.normalize_in_memory(
        _sample_profile(),
        (json.dumps(_sample_post(), ensure_ascii=False) + "\n").encode(),
    )
    analysis_result = analyze.analyze_in_memory(
        _sample_profile(), rows, {"task_id": "legacy", "platform": "douyin"}
    )
    if bad_link:
        analysis_result.analysis["posts"][0]["post_url"] = (
            "https://www.douyin.com/video/not-in-csv"
        )
    (target / "source" / "profile.json").write_text(
        json.dumps(_sample_profile(), ensure_ascii=False), encoding="utf-8"
    )
    (target / "normalized-posts.csv").write_text(
        normalized.csv_text, encoding="utf-8"
    )
    (target / "analysis.json").write_text(
        json.dumps(analysis_result.analysis, ensure_ascii=False), encoding="utf-8"
    )
    return target


def test_binary_writer_is_create_only_and_manifested(tmp_path):
    target = tmp_path / "analysis"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"dashboard.html"}
    )
    try:
        with reservation.open_binary("dashboard.html") as handle:
            handle.write(b"<!doctype html>\x00binary-safe")
        with pytest.raises(workspace.WorkspaceExistsError):
            with reservation.open_binary("dashboard.html"):
                pass
        reservation.commit()
    finally:
        reservation.close()

    verified = workspace.verify_committed_workspace(
        str(target), allowed_artifacts={"dashboard.html"}
    )
    assert verified["artifacts"][0]["sha256"]
    assert (target / "dashboard.html").read_bytes().endswith(b"\x00binary-safe")


def test_verified_reader_reports_one_commit_digest_for_every_read(tmp_path):
    collection, digest = _collection(tmp_path)

    with workspace.VerifiedWorkspaceReader.open(
        str(collection), allowed_artifacts=COLLECTION_ARTIFACTS
    ) as reader:
        profile = reader.read("source/profile.json")
        posts = reader.read("source/posts.jsonl")

    assert profile.source_digest == posts.source_digest == digest
    assert profile.source_format == posts.source_format == workspace.FORMAT
    assert json.loads(profile.payload)["account_id"] == "account-1"


def test_verified_reader_rejects_workspace_path_identity_change(tmp_path):
    collection, _ = _collection(tmp_path)
    displaced = tmp_path / "displaced"

    with workspace.VerifiedWorkspaceReader.open(
        str(collection), allowed_artifacts=COLLECTION_ARTIFACTS
    ) as reader:
        collection.rename(displaced)
        (collection / "source").mkdir(parents=True)
        with pytest.raises(workspace.WorkspaceVerificationError):
            reader.read("source/posts.jsonl")


def test_verified_reader_rejects_artifact_digest_change(tmp_path):
    collection, _ = _collection(tmp_path)

    with workspace.VerifiedWorkspaceReader.open(
        str(collection), allowed_artifacts=COLLECTION_ARTIFACTS
    ) as reader:
        (collection / "source" / "posts.jsonl").write_bytes(b"{}\n")
        with pytest.raises(workspace.WorkspaceVerificationError):
            reader.read("source/posts.jsonl")


def test_windows_reader_does_not_compare_native_identity_to_posix_fstat(tmp_path):
    artifact = tmp_path / "artifact"
    payload = b"windows-native-identity"
    artifact.write_bytes(payload)
    descriptor = os.open(artifact, os.O_RDONLY)
    leaf = workspace._VerifiedReaderLeaf(
        relative_path="task.json",
        descriptor=descriptor,
        identity=(7, 11),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        max_bytes=1024,
    )
    reader = workspace.VerifiedWorkspaceReader(
        str(tmp_path),
        allowed_artifacts=frozenset({"task.json"}),
        backend="windows",
        manifest={"artifacts": []},
        source_digest="0" * 64,
        leaves={"task.json": leaf},
        marker_leaf=leaf,
        manifest_leaf=leaf,
        windows_handles=(),
    )
    try:
        assert reader._read_leaf(leaf) == payload
    finally:
        os.close(descriptor)


def test_windows_reader_post_validation_checks_use_only_held_handles(
    monkeypatch, tmp_path
):
    identities = ((7, 1), (7, 2), (7, 3))
    handles = (101, 102, 103, *identities)
    reader = workspace.VerifiedWorkspaceReader(
        str(tmp_path),
        allowed_artifacts=frozenset(),
        backend="windows",
        manifest={"artifacts": []},
        source_digest="0" * 64,
        leaves={},
        marker_leaf=None,
        manifest_leaf=None,
        windows_handles=handles,
    )
    monkeypatch.setattr(
        workspace,
        "_windows_handle_metadata",
        lambda handle: {
            "identity": identities[handle - 101],
            "directory": True,
            "reparse": False,
            "links": 1,
            "size": 0,
        },
    )
    monkeypatch.setattr(
        workspace,
        "_verify_windows_workspace_identity",
        lambda *args, **kwargs: pytest.fail("reopened a Windows directory path"),
    )
    monkeypatch.setattr(
        workspace.os,
        "listdir",
        lambda *args, **kwargs: pytest.fail("listed a Windows pathname"),
    )
    monkeypatch.setattr(
        workspace,
        "_windows_directory_names",
        lambda handle: (
            {"source", workspace.MANIFEST_NAME, workspace.COMPLETE_NAME}
            if handle == 102
            else set()
        ),
        raising=False,
    )

    reader._validate_identity()
    reader._validate_inventory()


def test_windows_reader_rejects_inventory_added_after_validation(
    monkeypatch, tmp_path
):
    root_names = {
        "source",
        workspace.MANIFEST_NAME,
        workspace.COMPLETE_NAME,
        "task.json",
    }
    source_names: set[str] = set()
    reader = workspace.VerifiedWorkspaceReader(
        str(tmp_path),
        allowed_artifacts=frozenset({"task.json"}),
        backend="windows",
        manifest={"artifacts": [{"path": "task.json"}]},
        source_digest="0" * 64,
        leaves={"task.json": object()},
        marker_leaf=None,
        manifest_leaf=None,
        windows_handles=(101, 102, 103, (7, 1), (7, 2), (7, 3)),
    )
    monkeypatch.setattr(
        workspace,
        "_windows_directory_names",
        lambda handle: set(root_names if handle == 102 else source_names),
        raising=False,
    )

    reader._validate_inventory()
    root_names.add("concurrent-extra")
    with pytest.raises(workspace.WorkspaceVerificationError, match="inventory"):
        reader._validate_inventory()


def test_windows_directory_buffer_parser_uses_native_record_offsets():
    def record(name: str, *, final: bool) -> bytes:
        encoded = name.encode("utf-16-le")
        length = 104 + len(encoded)
        padded_length = (length + 7) & ~7
        payload = bytearray(padded_length)
        payload[0:4] = (0 if final else padded_length).to_bytes(4, "little")
        payload[60:64] = len(encoded).to_bytes(4, "little")
        payload[104 : 104 + len(encoded)] = encoded
        return bytes(payload)

    payload = (
        record(".", final=False)
        + record("task.json", final=False)
        + record("source", final=True)
    )

    assert workspace._parse_windows_directory_buffer(payload) == {
        "task.json",
        "source",
    }


def test_windows_directory_buffer_rejects_name_crossing_record_boundary():
    payload = bytearray(208)
    payload[0:4] = (104).to_bytes(4, "little")
    payload[60:64] = (2).to_bytes(4, "little")

    with pytest.raises(workspace.WorkspaceVerificationError, match="malformed"):
        workspace._parse_windows_directory_buffer(bytes(payload))


def test_windows_directory_enumeration_restarts_then_continues_by_handle(
    monkeypatch,
):
    def payload(name: str) -> bytes:
        encoded = name.encode("utf-16-le")
        result = bytearray(104 + len(encoded))
        result[60:64] = len(encoded).to_bytes(4, "little")
        result[104:] = encoded
        return bytes(result)

    error_number = [0]

    class FakeFunction:
        argtypes = None
        restype = None

        def __init__(self):
            self.calls = []
            self.pages = [payload("task.json"), payload("source")]

        def __call__(self, handle, information_class, buffer, buffer_size):
            self.calls.append((handle.value, information_class, buffer_size))
            if self.pages:
                page = self.pages.pop(0)
                workspace.ctypes.memmove(buffer, page, len(page))
                return 1
            error_number[0] = workspace._ERROR_NO_MORE_FILES
            return 0

    function = FakeFunction()

    class Kernel32:
        GetFileInformationByHandleEx = function

    monkeypatch.setattr(workspace, "_windows_kernel32", lambda: Kernel32())
    monkeypatch.setattr(
        workspace.ctypes,
        "get_last_error",
        lambda: error_number[0],
        raising=False,
    )

    assert workspace._windows_directory_names(77) == {"task.json", "source"}
    assert [call[1] for call in function.calls] == [
        workspace._FILE_ID_BOTH_DIRECTORY_RESTART_INFO,
        workspace._FILE_ID_BOTH_DIRECTORY_INFO,
        workspace._FILE_ID_BOTH_DIRECTORY_INFO,
    ]
    assert all(call[0] == 77 for call in function.calls)


def test_windows_directory_enumeration_fails_closed_on_nonterminal_error(
    monkeypatch,
):
    class FakeFunction:
        argtypes = None
        restype = None

        def __call__(self, *args):
            return 0

    class Kernel32:
        GetFileInformationByHandleEx = FakeFunction()

    monkeypatch.setattr(workspace, "_windows_kernel32", lambda: Kernel32())
    monkeypatch.setattr(
        workspace.ctypes, "get_last_error", lambda: 5, raising=False
    )

    with pytest.raises(OSError, match="inventory"):
        workspace._windows_directory_names(77)


def test_normalize_in_memory_has_no_filesystem_side_effects(tmp_path):
    before = list(tmp_path.iterdir())
    payload = (json.dumps(_sample_post(), ensure_ascii=False) + "\n").encode()

    result = normalize.normalize_in_memory(_sample_profile(), payload)

    assert result.coverage["raw_count"] == 1
    assert result.coverage["valid_count"] == 1
    assert "post_id" in result.csv_text
    assert list(tmp_path.iterdir()) == before


def test_analyze_in_memory_has_no_filesystem_side_effects(tmp_path):
    before = list(tmp_path.iterdir())

    result = analyze.analyze_in_memory(
        _sample_profile(),
        _normalized_rows(),
        {
            "task_id": "douyin-source-task",
            "platform": "douyin",
            "task_status": "COMPLETED",
            "requested_limit": 1,
        },
    )

    assert result.analysis["sample_boundary"]["valid"] == 1
    assert result.analysis["classification_status"] == "pending-model"
    assert list(tmp_path.iterdir()) == before


def test_analyzer_reads_historical_collection_python_repr_cells():
    posts = analyze.build_posts(
        [
            {
                "platform": "bilibili",
                "post_id": "BVlegacy",
                "hashtags": "['甲', '乙']",
                "platform_metrics": "{'a': 1}",
                "field_visibility": "{'views': 'visible'}",
                "collection_status": "SUCCESS",
                "collection_status_source": "declared",
            }
        ]
    )

    assert posts[0]["hashtags"] == ["甲", "乙"]
    assert posts[0]["platform_metrics"] == {"a": 1}
    assert posts[0]["field_visibility"] == {"views": "visible"}
    assert analyze.parse_json_object("{'tuple': (1, True, None)}") == {
        "tuple": [1, True, None]
    }


@pytest.mark.parametrize(
    "cell",
    [
        "{'a': {1}}",
        "{'a': b'bytes'}",
        "{'a': 1e999}",
        "{1: 'non-string-key'}",
        "{'a': __import__('os')}",
    ],
)
def test_analyzer_rejects_unsafe_or_non_json_legacy_structured_cells(cell):
    assert analyze.parse_json_object(cell) == {}


def test_analyzer_rejects_oversized_or_non_scalar_legacy_hashtag_cells():
    assert analyze.parse_hashtags("[b'bytes']") == []
    assert analyze.parse_hashtags("[__import__('os')]") == []
    assert analyze.parse_hashtags("['" + ("x" * 16_385) + "']") == []


def test_analyzer_rejects_deeply_nested_canonical_json_cells_without_crashing():
    deeply_nested_array = ("[" * 1_200) + '"tag"' + ("]" * 1_200)
    deeply_nested_object = ('{"a":' * 1_200) + "1" + ("}" * 1_200)

    assert analyze.parse_hashtags(deeply_nested_array) == []
    assert analyze.parse_json_object(deeply_nested_object) == {}


def test_sample_boundary_has_fixed_zero_filled_collection_status_counts():
    result = analyze.analyze_in_memory(
        _sample_profile(),
        _normalized_rows(),
        {"task_id": "status-counts", "platform": "douyin"},
    )

    assert result.analysis["sample_boundary"]["status_counts"] == {
        "SUCCESS": 1,
        "PARTIAL": 0,
        "FAILED": 0,
        "DELETED": 0,
        "RESTRICTED": 0,
    }


def test_collection_status_counts_keep_compatibility_totals_and_flag_exclusion():
    specs = [
        ("success", "SUCCESS", None),
        ("pinned-success", "SUCCESS", True),
        ("partial", "PARTIAL", None),
        ("failed", "FAILED", None),
        ("deleted", "DELETED", None),
        ("restricted", "RESTRICTED", None),
    ]
    rows = []
    for post_id, status, pinned in specs:
        raw = _sample_post(post_id)
        raw["collection_status"] = status
        raw["is_pinned"] = pinned
        rows.append(normalize.normalize_post(raw)[0])

    result = analyze.analyze_in_memory(
        _sample_profile(),
        rows,
        {"task_id": "status-counts", "platform": "douyin"},
    )
    boundary = result.analysis["sample_boundary"]

    assert boundary["status_counts"] == {
        "SUCCESS": 2,
        "PARTIAL": 1,
        "FAILED": 1,
        "DELETED": 1,
        "RESTRICTED": 1,
    }
    assert boundary["collected"] == 6
    assert boundary["valid"] == 2
    assert boundary["missing"] == 2
    assert boundary["restricted"] == 1
    assert boundary["excluded_flagged"] == 1
    assert boundary["excluded_flagged_post_ids"] == ["pinned-success"]


def test_render_in_memory_rejects_missing_required_input():
    with pytest.raises(render_report.RenderError, match="profile"):
        render_report.render_in_memory(
            profile=None,
            posts_csv=_normalized_rows(),
            analysis={"meta": {}},
            template=_minimal_template(),
        )


def test_render_in_memory_fails_closed_on_section_exception(monkeypatch):
    analysis_result = analyze.analyze_in_memory(
        _sample_profile(), _normalized_rows(), {"task_id": "source", "platform": "douyin"}
    )
    monkeypatch.setattr(
        render_report,
        "build_quality_summary",
        lambda analysis: (_ for _ in ()).throw(RuntimeError("SECTION_SENTINEL")),
    )

    with pytest.raises(render_report.RenderError, match="quality_summary"):
        render_report.render_in_memory(
            profile=_sample_profile(),
            posts_csv=_normalized_rows(),
            analysis=analysis_result.analysis,
            template=_minimal_template(),
        )


def test_render_in_memory_fails_closed_on_bad_post_link():
    rows = _normalized_rows()
    analysis_result = analyze.analyze_in_memory(
        _sample_profile(), rows, {"task_id": "source", "platform": "douyin"}
    )
    analysis_result.analysis["posts"][0]["post_url"] = (
        "https://www.douyin.com/video/not-in-csv"
    )

    with pytest.raises(render_report.RenderError, match="bad_link"):
        render_report.render_in_memory(
            profile=_sample_profile(),
            posts_csv=rows,
            analysis=analysis_result.analysis,
            template=_minimal_template(),
        )


def test_render_diagnostics_are_reset_between_calls():
    rows = _normalized_rows()
    analysis_result = analyze.analyze_in_memory(
        _sample_profile(), rows, {"task_id": "source", "platform": "douyin"}
    )
    bad = json.loads(json.dumps(analysis_result.analysis))
    bad["posts"][0]["post_url"] = "https://www.douyin.com/video/bad"
    with pytest.raises(render_report.RenderError):
        render_report.render_in_memory(
            profile=_sample_profile(),
            posts_csv=rows,
            analysis=bad,
            template=_minimal_template(),
        )

    good = render_report.render_in_memory(
        profile=_sample_profile(),
        posts_csv=rows,
        analysis=analysis_result.analysis,
        template=_minimal_template(),
    )
    assert good.diagnostics == ()


def test_render_in_memory_rejects_template_without_exact_section_inventory():
    analysis_result = analyze.analyze_in_memory(
        _sample_profile(), _normalized_rows(), {"task_id": "source", "platform": "douyin"}
    )

    with pytest.raises(render_report.RenderError, match="placeholder"):
        render_report.render_in_memory(
            profile=_sample_profile(),
            posts_csv=_normalized_rows(),
            analysis=analysis_result.analysis,
            template="<html><body>no report sections</body></html>",
        )


def test_render_in_memory_does_not_mutate_performance_module_state(monkeypatch):
    sentinel = "PERF_STATE_SENTINEL"
    monkeypatch.setattr(render_report, "_PERF_MAIN_METRIC", sentinel, raising=False)
    analysis_result = analyze.analyze_in_memory(
        _sample_profile(), _normalized_rows(), {"task_id": "source", "platform": "douyin"}
    )

    render_report.render_in_memory(
        profile=_sample_profile(),
        posts_csv=_normalized_rows(),
        analysis=analysis_result.analysis,
        template=_minimal_template(),
    )

    assert render_report._PERF_MAIN_METRIC == sentinel


def test_render_does_not_interpret_public_text_as_template_syntax():
    profile = _sample_profile()
    profile["account_name"] = "literal {{quality_summary}} and {{foo}}"
    analysis_result = analyze.analyze_in_memory(
        profile, _normalized_rows(), {"task_id": "source", "platform": "douyin"}
    )

    result = render_report.render_in_memory(
        profile=profile,
        posts_csv=_normalized_rows(),
        analysis=analysis_result.analysis,
        template=_minimal_template(),
    )

    assert "literal {{quality_summary}} and {{foo}}" in result.html


def test_pipeline_commits_exact_inventory_once_and_never_mutates_collection(
    monkeypatch, tmp_path
):
    pipeline = _pipeline_module()
    collection, source_digest = _collection(
        tmp_path,
        extra_artifacts={"normalized-posts.csv": b"STALE,COLLECTION,CSV\n"},
    )
    before = _tree_snapshot(collection)
    commit_calls = 0
    original_commit = workspace.ImmutableWorkspace.commit

    def counted_commit(reservation):
        nonlocal commit_calls
        commit_calls += 1
        return original_commit(reservation)

    monkeypatch.setattr(workspace.ImmutableWorkspace, "commit", counted_commit)
    output = tmp_path / "analysis"
    result = pipeline.run_pipeline(
        str(collection), str(output), template_text=_minimal_template()
    )

    assert commit_calls == 1
    assert result.commit_sha256
    assert _tree_snapshot(collection) == before
    assert workspace.verify_committed_workspace(
        str(collection), allowed_artifacts=COLLECTION_ARTIFACTS
    )["commit_sha256"] == source_digest
    verified = workspace.verify_committed_workspace(
        str(output), allowed_artifacts=pipeline.ANALYSIS_ARTIFACTS
    )
    assert {item["path"] for item in verified["artifacts"]} == set(
        pipeline.ANALYSIS_REQUIRED_ARTIFACTS
    )
    assert b"STALE,COLLECTION,CSV" not in (output / "normalized-posts.csv").read_bytes()
    provenance_text = (output / "source" / "collection-provenance.json").read_text()
    provenance = json.loads(provenance_text)
    assert provenance["collection_commit_sha256"] == source_digest
    assert provenance["source_task_id"] == "douyin-source-task"
    assert str(collection) not in provenance_text


def test_limited_upstream_commits_partial_analysis(tmp_path):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path, task_status="PARTIAL")
    output = tmp_path / "analysis"

    result = pipeline.run_pipeline(
        str(collection), str(output), template_text=_minimal_template()
    )

    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    assert result.task_status == task["task_status"] == "PARTIAL"
    assert task["phase_results"] == {
        "collection_input": "VERIFIED",
        "normalization": "COMPLETED",
        "analysis": "PARTIAL",
        "render": "COMPLETED",
        "validation": "COMPLETED",
    }
    assert (output / ".complete").is_file()


@pytest.mark.parametrize("raw_status", [None, "NOT_A_STATUS"])
def test_inferred_collection_status_makes_pipeline_normalization_partial(
    tmp_path, raw_status
):
    pipeline = _pipeline_module()
    post = _sample_post()
    if raw_status is None:
        post.pop("collection_status")
    else:
        post["collection_status"] = raw_status
    collection, _ = _collection(
        tmp_path, task_status="COMPLETED", posts=[post]
    )
    output = tmp_path / "analysis"
    classification_path = tmp_path / "classification-results.json"
    classification_path.write_text(
        json.dumps([_classification()], ensure_ascii=False), encoding="utf-8"
    )

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        classification_results_path=str(classification_path),
    )

    task = json.loads((output / "task.json").read_text(encoding="utf-8"))
    coverage = json.loads(
        (output / "normalized-coverage.json").read_text(encoding="utf-8")
    )
    analysis_payload = json.loads(
        (output / "analysis.json").read_text(encoding="utf-8")
    )
    assert result.task_status == task["task_status"] == "PARTIAL"
    assert task["partial_reasons"] == ["NORMALIZATION_PARTIAL"]
    assert task["phase_results"]["normalization"] == "PARTIAL"
    assert task["phase_results"]["analysis"] == "COMPLETED"
    assert coverage["warning_count"] == 1
    assert coverage["warnings"][0]["warning_code"] == (
        "COLLECTION_STATUS_INFERRED"
    )
    assert analysis_payload["sample_boundary"]["status_counts"]["PARTIAL"] == 1


def test_pending_classification_status_is_consistent_in_analysis_and_reports(
    tmp_path,
):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path, task_status="COMPLETED")
    output = tmp_path / "analysis"

    result = pipeline.run_pipeline(
        str(collection), str(output), template_text=_minimal_template()
    )

    analysis_payload = json.loads(
        (output / "analysis.json").read_text(encoding="utf-8")
    )
    task_payload = json.loads((output / "task.json").read_text(encoding="utf-8"))
    markdown = (output / "account-analysis-report.md").read_text(encoding="utf-8")
    html = (output / "dashboard.html").read_text(encoding="utf-8")
    pipeline_report = (output / "pipeline-report.md").read_text(encoding="utf-8")
    assert result.task_status == "PARTIAL"
    assert task_payload["task_status"] == "PARTIAL"
    assert task_payload["partial_reasons"] == ["PENDING_CLASSIFICATION"]
    assert analysis_payload["meta"]["task_status"] == "PARTIAL"
    assert analysis_payload["classification_status"] == "pending-model"
    assert "- partial_reasons: PENDING_CLASSIFICATION" in pipeline_report
    assert "\nPENDING_CLASSIFICATION\n" not in pipeline_report
    assert "PARTIAL" in markdown
    assert "PARTIAL" in html
    assert "PENDING_CLASSIFICATION" in markdown
    assert "PENDING_CLASSIFICATION" in html
    assert "COMPLETED" not in markdown
    assert "COMPLETED" not in html


def test_complete_classification_is_validated_applied_and_copied_exactly(tmp_path):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path, task_status="COMPLETED")
    output = tmp_path / "analysis"
    classification_path = tmp_path / "classification-results.json"
    classification_payload = (
        json.dumps([_classification()], ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    classification_path.write_bytes(classification_payload)

    result = pipeline.run_pipeline(
        str(collection),
        str(output),
        template_text=_minimal_template(),
        classification_results_path=str(classification_path),
    )

    task_payload = json.loads((output / "task.json").read_text(encoding="utf-8"))
    analysis_payload = json.loads(
        (output / "analysis.json").read_text(encoding="utf-8")
    )
    assert result.task_status == task_payload["task_status"] == "COMPLETED"
    assert task_payload["partial_reasons"] == []
    assert task_payload["phase_results"]["analysis"] == "COMPLETED"
    assert analysis_payload["classification_status"] == "llm-1"
    assert analysis_payload["posts"][0]["topic"] == "示例主题"
    assert "pending-model" not in json.dumps(
        analysis_payload, ensure_ascii=False
    )
    pipeline_report = (output / "pipeline-report.md").read_text(encoding="utf-8")
    assert "- partial_reasons: none" in pipeline_report
    assert "\nnone\n" not in pipeline_report
    assert (
        output / "source" / "classification-results.json"
    ).read_bytes() == classification_payload
    verified = workspace.verify_committed_workspace(
        str(output), allowed_artifacts=pipeline.ANALYSIS_ARTIFACTS
    )
    assert {item["path"] for item in verified["artifacts"]} == set(
        pipeline.ANALYSIS_REQUIRED_ARTIFACTS
    ) | {"source/classification-results.json"}


@pytest.mark.parametrize(
    "classification_results",
    [
        [],
        [_classification("not-a-parent-post")],
        [_classification(format="unsupported-format")],
        [_classification(), _classification()],
        [_classification(analysis_labels=[1])],
    ],
)
def test_invalid_or_incomplete_classification_creates_no_output(
    tmp_path, classification_results
):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path)
    output = tmp_path / "analysis"
    classification_path = tmp_path / "classification-results.json"
    classification_path.write_text(
        json.dumps(classification_results, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(pipeline.PipelineError, match="classification"):
        pipeline.run_pipeline(
            str(collection),
            str(output),
            template_text=_minimal_template(),
            classification_results_path=str(classification_path),
        )

    assert not output.exists()


def test_cli_accepts_classification_results_file(tmp_path):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path)
    output = tmp_path / "analysis"
    classification_path = tmp_path / "classification-results.json"
    classification_path.write_text(
        json.dumps([_classification()], ensure_ascii=False), encoding="utf-8"
    )
    template_path = tmp_path / "template.html"
    template_path.write_text(_minimal_template(), encoding="utf-8")

    code = pipeline.main(
        [
            "--input",
            str(collection),
            "--output",
            str(output),
            "--template",
            str(template_path),
            "--classification-results",
            str(classification_path),
        ]
    )

    assert code == 0
    assert (output / ".complete").is_file()


def test_pipeline_copies_only_verified_optional_source_evidence(tmp_path):
    pipeline = _pipeline_module()
    comments = b'{"comment_id":"c1","text":"ok"}\n'
    index = b'{"schema_version":1}\n'
    collection, _ = _collection(
        tmp_path,
        extra_artifacts={
            "source/comments.jsonl": comments,
            "source/index-evidence.json": index,
        },
    )
    output = tmp_path / "analysis"

    pipeline.run_pipeline(
        str(collection), str(output), template_text=_minimal_template()
    )

    assert (output / "source" / "comments.jsonl").read_bytes() == comments
    assert (output / "source" / "index-evidence.json").read_bytes() == index
    assert not (output / "collection-report.md").exists()


@pytest.mark.parametrize(
    "stage_name", ["normalize_in_memory", "analyze_in_memory", "render_in_memory"]
)
def test_in_memory_phase_failure_creates_no_output(monkeypatch, tmp_path, stage_name):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path)
    output = tmp_path / "analysis"

    def fail(*args, **kwargs):
        raise RuntimeError("PHASE_SENTINEL")

    monkeypatch.setattr(pipeline, stage_name, fail)
    with pytest.raises(pipeline.PipelineError, match="PHASE_SENTINEL"):
        pipeline.run_pipeline(
            str(collection), str(output), template_text=_minimal_template()
        )
    assert not output.exists()


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_existing_output_fails_before_processing(monkeypatch, tmp_path, kind):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path)
    output = tmp_path / "analysis"
    victim = tmp_path / "victim"
    victim.mkdir()
    if kind == "directory":
        output.mkdir()
    else:
        output.symlink_to(victim, target_is_directory=True)

    monkeypatch.setattr(
        pipeline,
        "normalize_in_memory",
        lambda *args, **kwargs: pytest.fail("processing started before preflight"),
    )
    with pytest.raises(workspace.WorkspaceExistsError):
        pipeline.run_pipeline(
            str(collection), str(output), template_text=_minimal_template()
        )
    assert output.exists()
    assert list(victim.iterdir()) == []


@pytest.mark.parametrize("missing_kind", ["posts", "analyzable_rows"])
def test_invalid_collection_input_creates_no_output(tmp_path, missing_kind):
    pipeline = _pipeline_module()
    collection, _ = _collection(
        tmp_path,
        include_posts=missing_kind != "posts",
        posts=[] if missing_kind == "analyzable_rows" else None,
    )
    output = tmp_path / "analysis"

    with pytest.raises(pipeline.PipelineError):
        pipeline.run_pipeline(
            str(collection), str(output), template_text=_minimal_template()
        )
    assert not output.exists()


def test_missing_template_creates_no_output(tmp_path):
    pipeline = _pipeline_module()
    collection, _ = _collection(tmp_path)
    output = tmp_path / "analysis"

    with pytest.raises(pipeline.PipelineError, match="template"):
        pipeline.run_pipeline(str(collection), str(output), template_text="")
    assert not output.exists()


@pytest.mark.parametrize("legacy_cli", ["normalize", "analyze", "render"])
def test_legacy_clis_refuse_sealed_workspace_without_mutation(
    tmp_path, legacy_cli
):
    collection, _ = _collection(tmp_path)
    before = _tree_snapshot(collection)

    if legacy_cli == "normalize":
        code = normalize.main(["--input", str(collection)])
    elif legacy_cli == "analyze":
        code = analyze.main(["--input", str(collection)])
    else:
        code = render_report.main(["--input", str(collection)])

    assert isinstance(code, int) and code != 0
    assert _tree_snapshot(collection) == before


def test_legacy_renderer_missing_input_is_fatal_before_output(tmp_path):
    input_dir = tmp_path / "empty-input"
    input_dir.mkdir()
    output = tmp_path / "rendered"

    code = render_report.main(
        ["--input", str(input_dir), "--output", str(output)]
    )

    assert code != 0
    assert not output.exists()


def test_legacy_renderer_section_exception_is_fatal_before_output(
    monkeypatch, tmp_path
):
    input_dir = _legacy_analysis_dir(tmp_path)
    output = tmp_path / "rendered"
    template = tmp_path / "template.html"
    template.write_text(_minimal_template(), encoding="utf-8")
    monkeypatch.setattr(
        render_report,
        "build_quality_summary",
        lambda analysis: (_ for _ in ()).throw(RuntimeError("SECTION_SENTINEL")),
    )

    code = render_report.main(
        [
            "--input",
            str(input_dir),
            "--output",
            str(output),
            "--template",
            str(template),
        ]
    )

    assert code != 0
    assert not output.exists()


def test_legacy_renderer_bad_link_is_fatal_and_diagnostics_reset(tmp_path):
    bad_input = _legacy_analysis_dir(tmp_path, bad_link=True)
    bad_output = tmp_path / "bad-output"
    template = tmp_path / "template.html"
    template.write_text(_minimal_template(), encoding="utf-8")
    render_report.WARNINGS.clear()
    render_report.KNOWN_POST_URLS.clear()
    render_report.REFERENCED_POST_URLS.clear()

    bad_code = render_report.main(
        [
            "--input",
            str(bad_input),
            "--output",
            str(bad_output),
            "--template",
            str(template),
        ]
    )
    good_input = _legacy_analysis_dir(tmp_path / "good")
    good_output = tmp_path / "good-output"
    good_code = render_report.main(
        [
            "--input",
            str(good_input),
            "--output",
            str(good_output),
            "--template",
            str(template),
        ]
    )

    assert bad_code != 0
    assert not bad_output.exists()
    assert good_code == 0
    assert (good_output / "dashboard.html").is_file()
    assert render_report.WARNINGS == []
