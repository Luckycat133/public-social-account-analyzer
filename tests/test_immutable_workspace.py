"""Security contracts for create-only, immutable collection workspaces."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import immutable_workspace as workspace


ARTIFACTS = frozenset(
    {
        "source/profile.json",
        "source/posts.jsonl",
        "normalized-posts.csv",
        "task.json",
        "collection-report.md",
    }
)


def _committed(tmp_path: Path, name: str = "task") -> Path:
    target = tmp_path / name
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts=ARTIFACTS
    )
    try:
        for relative in sorted(ARTIFACTS):
            with reservation.open_text(relative) as handle:
                handle.write(f"payload:{relative}\n")
        reservation.commit()
    finally:
        reservation.close()
    return target


@pytest.mark.parametrize("kind", ["empty-directory", "file", "symlink"])
def test_final_workspace_reservation_is_create_only_and_preserves_existing_node(
    tmp_path, kind
):
    target = tmp_path / "task"
    victim = tmp_path / "victim"
    victim.write_bytes(b"victim\x00bytes")
    if kind == "empty-directory":
        target.mkdir()
    elif kind == "file":
        target.write_bytes(b"existing\x00bytes")
    else:
        target.symlink_to(victim)

    with pytest.raises(workspace.WorkspaceExistsError):
        workspace.ImmutableWorkspace.reserve(
            str(target), allowed_artifacts=ARTIFACTS
        )

    assert victim.read_bytes() == b"victim\x00bytes"
    if kind == "empty-directory":
        assert target.is_dir() and list(target.iterdir()) == []
    elif kind == "file":
        assert target.read_bytes() == b"existing\x00bytes"
    else:
        assert target.is_symlink()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX")
@pytest.mark.parametrize("kind", ["regular", "symlink", "fifo", "hardlink"])
def test_artifact_open_is_create_only_and_never_truncates_existing_leaf(
    tmp_path, kind
):
    target = tmp_path / "task"
    victim = tmp_path / "victim"
    victim_bytes = b"victim\x00must-survive"
    victim.write_bytes(victim_bytes)
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts=ARTIFACTS
    )
    leaf = target / "task.json"
    if kind == "regular":
        leaf.write_bytes(b"concurrent\x00bytes")
    elif kind == "symlink":
        leaf.symlink_to(victim)
    elif kind == "fifo":
        os.mkfifo(leaf)
    else:
        os.link(victim, leaf)

    try:
        with pytest.raises(workspace.WorkspaceExistsError):
            with reservation.open_text("task.json") as handle:
                handle.write("must-not-run")
    finally:
        reservation.close()

    assert victim.read_bytes() == victim_bytes
    if kind == "regular":
        assert leaf.read_bytes() == b"concurrent\x00bytes"


def test_leaf_swap_writes_only_held_object_and_causes_commit_failure(tmp_path):
    target = tmp_path / "task"
    displaced = tmp_path / "displaced-task-json"
    replacement_bytes = b"replacement\x00must-survive"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    context = reservation.open_text("task.json")
    handle = context.__enter__()
    (target / "task.json").rename(displaced)
    (target / "task.json").write_bytes(replacement_bytes)
    handle.write("owned-object")
    context.__exit__(None, None, None)

    try:
        with pytest.raises(workspace.WorkspaceIdentityError):
            reservation.commit()
    finally:
        reservation.close()

    assert displaced.read_text(encoding="utf-8") == "owned-object"
    assert (target / "task.json").read_bytes() == replacement_bytes
    assert not (target / ".complete").exists()


def test_workspace_swap_preserves_replacement_and_never_commits_it(tmp_path):
    target = tmp_path / "task"
    displaced = tmp_path / "displaced-task"
    replacement_bytes = b"replacement\x00must-survive"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("owned-object")
    target.rename(displaced)
    target.mkdir()
    (target / "replacement.bin").write_bytes(replacement_bytes)

    try:
        with pytest.raises(workspace.WorkspaceIdentityError):
            reservation.commit()
    finally:
        reservation.close()

    assert (target / "replacement.bin").read_bytes() == replacement_bytes
    assert not (target / ".complete").exists()
    assert not (displaced / ".complete").exists()


def test_preexisting_complete_marker_is_not_overwritten(tmp_path):
    target = tmp_path / "task"
    marker_bytes = b"concurrent marker\x00must-survive"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    (target / ".complete").write_bytes(marker_bytes)

    try:
        with pytest.raises(workspace.WorkspaceExistsError):
            reservation.commit()
    finally:
        reservation.close()

    assert (target / ".complete").read_bytes() == marker_bytes


@pytest.mark.parametrize("exception_type", [RuntimeError, OSError])
def test_ordinary_serialization_failure_leaves_incomplete_workspace_without_cleanup(
    monkeypatch, tmp_path, exception_type
):
    for name in ("replace", "rename", "unlink", "rmdir"):
        monkeypatch.setattr(
            workspace.os,
            name,
            lambda *args, _name=name, **kwargs: pytest.fail(
                f"failure path called os.{_name}"
            ),
        )
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    try:
        with pytest.raises(exception_type):
            with reservation.open_text("task.json") as handle:
                handle.write("partial")
                raise exception_type("SECRET_FAILURE")
    finally:
        reservation.close()

    assert target.is_dir()
    assert (target / "task.json").read_text(encoding="utf-8") == "partial"
    assert not (target / ".complete").exists()


@pytest.mark.parametrize("control_flow", [KeyboardInterrupt, SystemExit])
def test_serialization_control_flow_propagates_after_handles_close(
    tmp_path, control_flow
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )

    with pytest.raises(control_flow, match="CONTROL_FLOW_SENTINEL"):
        try:
            with reservation.open_text("task.json") as handle:
                handle.write("partial")
                raise control_flow("CONTROL_FLOW_SENTINEL")
        finally:
            reservation.close()

    assert reservation.closed is True
    assert not (target / ".complete").exists()


def test_manifest_is_deterministic_and_verifier_accepts_exact_inventory(tmp_path):
    first = _committed(tmp_path, "first")
    second = _committed(tmp_path, "second")

    assert (first / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()
    assert (first / ".complete").read_bytes() == (
        second / ".complete"
    ).read_bytes()
    verified = workspace.verify_committed_workspace(
        str(first), allowed_artifacts=ARTIFACTS
    )
    assert set(item["path"] for item in verified["artifacts"]) == ARTIFACTS


@pytest.mark.parametrize("corruption", ["artifact", "manifest", "marker"])
def test_verifier_rejects_truncated_artifact_manifest_or_marker(
    tmp_path, corruption
):
    target = _committed(tmp_path)
    path = {
        "artifact": target / "task.json",
        "manifest": target / "manifest.json",
        "marker": target / ".complete",
    }[corruption]
    payload = path.read_bytes()
    path.write_bytes(payload[: max(0, len(payload) // 2)])

    with pytest.raises(workspace.WorkspaceVerificationError):
        workspace.verify_committed_workspace(
            str(target), allowed_artifacts=ARTIFACTS
        )


def test_missing_backend_primitives_fail_before_workspace_creation(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    monkeypatch.setattr(workspace, "_backend_kind", lambda: "unsupported")

    with pytest.raises(workspace.WorkspaceCapabilityError):
        workspace.ImmutableWorkspace.reserve(
            str(target), allowed_artifacts=ARTIFACTS
        )

    assert not target.exists()


def test_windows_native_leaf_open_uses_create_new_without_delete_sharing(
    monkeypatch, tmp_path
):
    calls = []

    class FakeCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args):
            calls.append(args)
            return 41

    class FakeKernel32:
        CreateFileW = FakeCreateFile()

    monkeypatch.setattr(workspace, "_windows_kernel32", lambda: FakeKernel32())
    monkeypatch.setattr(
        workspace,
        "_windows_handle_metadata",
        lambda handle: {
            "identity": (7, 11),
            "directory": False,
            "reparse": False,
            "links": 1,
            "size": 0,
        },
    )

    handle, _ = workspace._open_windows_path(
        str(tmp_path / "leaf"), create_new=True, directory=False
    )

    assert handle == 41
    assert calls[0][2] == 0x00000001 | 0x00000002
    assert calls[0][4] == 1
    assert calls[0][5] & 0x00200000


def test_windows_directory_handle_requests_list_directory_access(
    monkeypatch, tmp_path
):
    calls = []

    class FakeCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args):
            calls.append(args)
            return 42

    class FakeKernel32:
        CreateFileW = FakeCreateFile()

    monkeypatch.setattr(workspace, "_windows_kernel32", lambda: FakeKernel32())
    monkeypatch.setattr(
        workspace,
        "_windows_handle_metadata",
        lambda handle: {
            "identity": (7, 12),
            "directory": True,
            "reparse": False,
            "links": 1,
            "size": 0,
        },
    )

    workspace._open_windows_path(
        str(tmp_path), create_new=False, directory=True
    )

    assert calls[0][1] & 0x00000001


def test_simulated_windows_backend_builds_and_verifies_create_only_workspace(
    monkeypatch, tmp_path
):
    handles = {}
    next_handle = iter(range(100, 10_000))
    closed = []

    def metadata_for(path):
        metadata = os.lstat(path)
        return {
            "identity": (metadata.st_dev, metadata.st_ino),
            "directory": path.is_dir(),
            "reparse": path.is_symlink(),
            "links": metadata.st_nlink,
            "size": metadata.st_size,
        }

    def open_path(path, *, create_new, directory):
        assert create_new is False
        item = Path(path)
        info = metadata_for(item)
        assert info["directory"] is directory
        handle = next(next_handle)
        handles[handle] = item
        return handle, info

    def handle_metadata(handle):
        return metadata_for(handles[handle])

    def close_handle(handle):
        closed.append(int(handle))
        handles.pop(int(handle), None)

    def open_regular(path, *, create_new):
        flags = os.O_RDWR
        if create_new:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        return descriptor, (metadata.st_dev, metadata.st_ino)

    monkeypatch.setattr(workspace, "_backend_kind", lambda: "windows")
    monkeypatch.setattr(workspace, "_preflight_windows", lambda: None)
    monkeypatch.setattr(workspace, "_open_windows_path", open_path)
    monkeypatch.setattr(workspace, "_windows_handle_metadata", handle_metadata)
    monkeypatch.setattr(workspace, "_close_windows_handle", close_handle)
    monkeypatch.setattr(workspace, "_open_windows_regular_fd", open_regular)
    target = tmp_path / "windows-task"

    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    try:
        with reservation.open_text("task.json") as handle:
            handle.write("windows-create-new")
        reservation.commit()
    finally:
        reservation.close()

    verified = workspace.verify_committed_workspace(
        str(target), allowed_artifacts={"task.json"}
    )
    assert verified["artifacts"][0]["path"] == "task.json"
    assert (target / ".complete").is_file()
    assert closed


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX rename semantics")
@pytest.mark.parametrize("mutation_stage", ["manifest-fsync", "marker-fsync"])
def test_commit_rehashes_artifacts_after_evidence_and_before_success(
    monkeypatch, tmp_path, mutation_stage
):
    target = tmp_path / "task"
    artifact = target / "task.json"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("AAAA")
    original_fsync = workspace.os.fsync
    injected = False

    def fsync_with_in_place_rewrite(descriptor):
        nonlocal injected
        result = original_fsync(descriptor)
        metadata = os.fstat(descriptor)
        candidate = target / (
            workspace.MANIFEST_NAME
            if mutation_stage == "manifest-fsync"
            else workspace.COMPLETE_NAME
        )
        if candidate.exists():
            named = os.lstat(candidate)
            is_candidate = (metadata.st_dev, metadata.st_ino) == (
                named.st_dev,
                named.st_ino,
            )
        else:
            is_candidate = False
        if (
            not injected
            and is_candidate
            and (
                mutation_stage == "manifest-fsync"
                or metadata.st_size > 0
            )
        ):
            injected = True
            artifact.write_bytes(b"BBBB")
        return result

    monkeypatch.setattr(workspace.os, "fsync", fsync_with_in_place_rewrite)
    try:
        with pytest.raises(workspace.WorkspaceIdentityError):
            reservation.commit()
    finally:
        reservation.close()

    assert injected is True
    with pytest.raises(workspace.WorkspaceVerificationError):
        workspace.verify_committed_workspace(
            str(target), allowed_artifacts={"task.json"}
        )


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX rename semantics")
@pytest.mark.parametrize("metadata_name", [workspace.MANIFEST_NAME, workspace.COMPLETE_NAME])
def test_commit_rejects_metadata_pathname_swap(
    monkeypatch, tmp_path, metadata_name
):
    target = tmp_path / "task"
    displaced = tmp_path / f"displaced-{metadata_name.lstrip('.')}"
    replacement = b"replacement metadata\x00must-survive"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_verify_tree = reservation._verify_committing_tree
    swapped = False

    def verify_tree_with_swap(manifest, manifest_digest, *, marker):
        nonlocal swapped
        should_swap = (
            metadata_name == workspace.MANIFEST_NAME and not marker
        ) or (
            metadata_name == workspace.COMPLETE_NAME and marker
        )
        if should_swap and not swapped:
            swapped = True
            path = target / metadata_name
            path.rename(displaced)
            path.write_bytes(replacement)
        return original_verify_tree(manifest, manifest_digest, marker=marker)

    monkeypatch.setattr(reservation, "_verify_committing_tree", verify_tree_with_swap)
    try:
        with pytest.raises(workspace.WorkspaceIdentityError):
            reservation.commit()
    finally:
        reservation.close()

    assert swapped is True
    assert (target / metadata_name).read_bytes() == replacement
    with pytest.raises(workspace.WorkspaceVerificationError):
        workspace.verify_committed_workspace(
            str(target), allowed_artifacts={"task.json"}
        )


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX rename semantics")
def test_identical_valid_marker_replacement_is_never_converged_to_success(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    displaced = tmp_path / "owned-complete"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_verify_tree = reservation._verify_committing_tree
    swapped = False

    def verify_tree_with_identical_final_marker_swap(
        manifest, manifest_digest, *, marker
    ):
        nonlocal swapped
        if marker and reservation._marker_finalized and not swapped:
            swapped = True
            marker_path = target / workspace.COMPLETE_NAME
            valid_marker = marker_path.read_bytes()
            marker_path.rename(displaced)
            marker_path.write_bytes(valid_marker)
        return original_verify_tree(manifest, manifest_digest, marker=marker)

    monkeypatch.setattr(
        reservation,
        "_verify_committing_tree",
        verify_tree_with_identical_final_marker_swap,
    )
    try:
        with pytest.raises(workspace.WorkspaceIdentityError):
            reservation.commit()
    finally:
        reservation.close()

    assert swapped is True
    assert displaced.read_bytes() == (
        target / workspace.COMPLETE_NAME
    ).read_bytes()
    verified = workspace.verify_committed_workspace(
        str(target), allowed_artifacts={"task.json"}
    )
    assert verified["commit_sha256"]


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX rename semantics")
def test_writer_rejects_complete_ancestor_chain_swap(tmp_path):
    visible_parent = tmp_path / "P"
    displaced_parent = tmp_path / "P-old"
    visible_parent.mkdir()
    target = visible_parent / "task"
    replacement_bytes = b"replacement\x00must-survive"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("owned")
    visible_parent.rename(displaced_parent)
    (visible_parent / "task" / "source").mkdir(parents=True)
    (visible_parent / "task" / "replacement.bin").write_bytes(replacement_bytes)

    try:
        with pytest.raises(workspace.WorkspaceIdentityError):
            reservation.commit()
    finally:
        reservation.close()

    assert (visible_parent / "task" / "replacement.bin").read_bytes() == replacement_bytes
    assert not (visible_parent / "task" / workspace.COMPLETE_NAME).exists()
    assert not (displaced_parent / "task" / workspace.COMPLETE_NAME).exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX rename semantics")
@pytest.mark.parametrize("reader", ["verify", "resume"])
def test_reader_rejects_complete_ancestor_chain_swap(monkeypatch, tmp_path, reader):
    visible_parent = tmp_path / "P"
    displaced_parent = tmp_path / "P-old"
    visible_parent.mkdir()
    target = _committed(visible_parent)
    replacement_bytes = b"replacement\x00must-survive"
    original_verify = workspace._verify_posix_handles
    swapped = False

    def verify_after_parent_swap(handles, allowed, *, capture_path=None):
        nonlocal swapped
        if not swapped:
            swapped = True
            visible_parent.rename(displaced_parent)
            (visible_parent / "task" / "source").mkdir(parents=True)
            (visible_parent / "task" / "replacement.bin").write_bytes(
                replacement_bytes
            )
        return original_verify(
            handles, allowed, capture_path=capture_path
        )

    monkeypatch.setattr(workspace, "_verify_posix_handles", verify_after_parent_swap)
    with pytest.raises(workspace.WorkspaceVerificationError):
        if reader == "verify":
            workspace.verify_committed_workspace(
                str(target), allowed_artifacts=ARTIFACTS
            )
        else:
            workspace.read_resume_artifact(
                str(target),
                "task.json",
                allowed_artifacts=ARTIFACTS,
            )

    assert swapped is True
    assert (visible_parent / "task" / "replacement.bin").read_bytes() == replacement_bytes


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX directory fsync")
def test_directory_fsync_failure_leaves_only_an_invalid_marker(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_fsync = workspace.os.fsync
    injected = False

    def fail_first_directory_fsync_after_marker_creation(descriptor):
        nonlocal injected
        if (
            not injected
            and (target / workspace.COMPLETE_NAME).exists()
            and stat.S_ISDIR(os.fstat(descriptor).st_mode)
        ):
            injected = True
            raise OSError("DIRECTORY_FSYNC_SENTINEL")
        return original_fsync(descriptor)

    monkeypatch.setattr(
        workspace.os,
        "fsync",
        fail_first_directory_fsync_after_marker_creation,
    )
    try:
        with pytest.raises(workspace.WorkspaceWriteError):
            reservation.commit()
    finally:
        reservation.close()

    assert injected is True
    assert (target / workspace.COMPLETE_NAME).read_bytes() == b""
    with pytest.raises(workspace.WorkspaceVerificationError):
        workspace.verify_committed_workspace(
            str(target), allowed_artifacts={"task.json"}
        )


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX fsync injection")
def test_final_marker_fsync_retries_before_verified_success(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_fsync = workspace.os.fsync
    final_marker_fsync_calls = 0

    def fail_final_marker_fsync_once(descriptor):
        nonlocal final_marker_fsync_calls
        marker = target / workspace.COMPLETE_NAME
        metadata = os.fstat(descriptor)
        if marker.exists():
            named = os.lstat(marker)
            is_marker = (metadata.st_dev, metadata.st_ino) == (
                named.st_dev,
                named.st_ino,
            )
        else:
            is_marker = False
        if is_marker and metadata.st_size > 0:
            final_marker_fsync_calls += 1
            if final_marker_fsync_calls == 1:
                raise OSError("MARKER_FSYNC_SENTINEL")
        return original_fsync(descriptor)

    monkeypatch.setattr(workspace.os, "fsync", fail_final_marker_fsync_once)
    try:
        digest = reservation.commit()
    finally:
        reservation.close()

    assert final_marker_fsync_calls == 2
    verified = workspace.verify_committed_workspace(
        str(target), allowed_artifacts={"task.json"}
    )
    assert digest == verified["commit_sha256"]


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX fsync injection")
def test_persistent_final_marker_fsync_is_indeterminate_and_bounded(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_fsync = workspace.os.fsync
    final_marker_fsync_calls = 0
    secret = "SECRET_PERSISTENT_MARKER_FSYNC"

    def fail_final_marker_fsync(descriptor):
        nonlocal final_marker_fsync_calls
        marker = target / workspace.COMPLETE_NAME
        metadata = os.fstat(descriptor)
        if marker.exists():
            named = os.lstat(marker)
            is_marker = (metadata.st_dev, metadata.st_ino) == (
                named.st_dev,
                named.st_ino,
            )
        else:
            is_marker = False
        if is_marker and metadata.st_size > 0:
            final_marker_fsync_calls += 1
            raise OSError(secret)
        return original_fsync(descriptor)

    monkeypatch.setattr(workspace.os, "fsync", fail_final_marker_fsync)
    try:
        with pytest.raises(workspace.WorkspaceCommitIndeterminate) as exc_info:
            reservation.commit()
    finally:
        reservation.close()

    assert final_marker_fsync_calls == 3
    assert str(exc_info.value) == (
        "workspace commit durability or final verification is indeterminate"
    )
    assert exc_info.value.__cause__ is None
    assert secret not in str(exc_info.value)
    verified = workspace.verify_committed_workspace(
        str(target), allowed_artifacts={"task.json"}
    )
    assert verified["commit_sha256"]


def test_commit_uses_user_visible_verifier_and_retries_transient_final_error(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_verify = workspace.verify_committed_workspace
    calls = 0

    def transient_then_verify(path, *, allowed_artifacts):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("TRANSIENT_FINAL_VERIFY")
        return original_verify(path, allowed_artifacts=allowed_artifacts)

    monkeypatch.setattr(
        workspace,
        "verify_committed_workspace",
        transient_then_verify,
    )
    try:
        digest = reservation.commit()
    finally:
        reservation.close()

    assert calls == 2
    assert digest == original_verify(
        str(target), allowed_artifacts={"task.json"}
    )["commit_sha256"]


def test_persistent_post_marker_verifier_io_error_is_indeterminate(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    original_verify = workspace.verify_committed_workspace

    calls = 0
    secret = "SECRET_PERSISTENT_FINAL_VERIFY"

    def persistent_error(path, *, allowed_artifacts):
        nonlocal calls
        calls += 1
        raise OSError(secret)

    monkeypatch.setattr(workspace, "verify_committed_workspace", persistent_error)
    try:
        with pytest.raises(workspace.WorkspaceCommitIndeterminate) as exc_info:
            reservation.commit()
    finally:
        reservation.close()
    monkeypatch.setattr(workspace, "verify_committed_workspace", original_verify)

    assert calls == 3
    assert str(exc_info.value) == (
        "workspace commit durability or final verification is indeterminate"
    )
    assert exc_info.value.__cause__ is None
    assert secret not in str(exc_info.value)
    assert original_verify(
        str(target), allowed_artifacts={"task.json"}
    )["commit_sha256"]


def test_final_workspace_verification_error_is_not_retried_or_converged(
    monkeypatch, tmp_path
):
    target = tmp_path / "task"
    reservation = workspace.ImmutableWorkspace.reserve(
        str(target), allowed_artifacts={"task.json"}
    )
    with reservation.open_text("task.json") as handle:
        handle.write("payload")
    calls = 0

    def reject_content(path, *, allowed_artifacts):
        nonlocal calls
        calls += 1
        raise workspace.WorkspaceVerificationError("CONTENT_REJECTED")

    monkeypatch.setattr(workspace, "verify_committed_workspace", reject_content)
    try:
        with pytest.raises(
            workspace.WorkspaceVerificationError, match="CONTENT_REJECTED"
        ):
            reservation.commit()
    finally:
        reservation.close()

    assert calls == 1
