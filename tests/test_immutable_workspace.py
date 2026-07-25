"""Security contracts for create-only, immutable collection workspaces."""

from __future__ import annotations

import os
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
