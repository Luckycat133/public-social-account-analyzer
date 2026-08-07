"""Offline tests for tools/check_markdown_links.py — packaging-time link guard."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "tools" / "check_markdown_links.py"


def _run_checker(tmp_workdir: Path, *md_paths: str) -> tuple[int, str]:
    """Invoke the checker with a custom working directory so we can stage files
    without polluting the source tree.
    """
    import subprocess

    targets = [str((tmp_workdir / p).resolve()) for p in md_paths]
    completed = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--repo-root",
            str(tmp_workdir.resolve()),
            "--paths",
            *targets,
        ],
        cwd=tmp_workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stderr + completed.stdout


def test_checker_passes_for_self_contained_markdown(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "link to [intro](intro.md)\n",
        encoding="utf-8",
    )
    (tmp_path / "intro.md").write_text("hello\n", encoding="utf-8")
    rc, output = _run_checker(tmp_path, "README.md", "intro.md")
    assert rc == 0, output
    assert "PASS" in output


def test_checker_flags_missing_relative_target(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "see [removed](data-schema.md) and [mod](artifact-contract.md)\n",
        encoding="utf-8",
    )
    (tmp_path / "artifact-contract.md").write_text("ok\n", encoding="utf-8")
    rc, output = _run_checker(tmp_path, "README.md")
    assert rc == 1
    assert "data-schema.md" in output
    assert "artifact-contract.md" not in output


def test_checker_skips_external_and_anchor_links(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "see [home](https://example.com)",
                "and [anchor](#section)",
                "and [mailto](mailto:hi@example.com)",
                "real link [good](present.md)",
                "```",
                "[broken-inside-fence](never.md)",
                "```",
                "after fence [again](present.md)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "present.md").write_text("ok\n", encoding="utf-8")
    rc, output = _run_checker(tmp_path, "README.md")
    assert rc == 0, output


def test_checker_walks_subdirectories(tmp_path: Path) -> None:
    nested = tmp_path / "skill" / "references"
    nested.mkdir(parents=True)
    (tmp_path / "skill" / "SKILL.md").write_text(
        "see [rf](references/artifact-contract.md)\n",
        encoding="utf-8",
    )
    (nested / "artifact-contract.md").write_text("ok\n", encoding="utf-8")
    rc, output = _run_checker(tmp_path, "skill")
    assert rc == 0, output


def test_checker_rejects_path_outside_repo_root(tmp_path: Path) -> None:
    """If a path resolves outside --repo-root, the check refuses to scan it."""
    inside = tmp_path / "inside.md"
    inside.write_text("ok\n", encoding="utf-8")
    outside_dir = tmp_path.parent / "outside-link-target"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "outside.md"
    outside_file.write_text("ok\n", encoding="utf-8")
    rc, output = _run_checker(tmp_path, str(outside_file))
    assert rc == 2
    assert "escapes" in output or "not found" in output


def test_repo_markdown_link_check_passes() -> None:
    """Integration: running the checker over the actual repo (skill/ + docs/ +
    release-facing root docs) must currently pass. This is the contract that
    protects the 0.9.1 release from shipping with broken SKILL.md links.
    """
    import subprocess

    completed = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--paths",
            "skill",
            "docs",
            "README.md",
            "USAGE.md",
            "ROADMAP.md",
            "CHANGELOG.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "PASS" in completed.stdout


def test_main_function_rejects_missing_path(tmp_path: Path) -> None:
    """`main()` should return 2 when a configured path does not exist."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_markdown_links", CHECK_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)

    rc = module.main(
        [
            "--repo-root",
            str(tmp_path.resolve()),
            "--paths",
            "definitely-not-a-real-path-xyz",
        ]
    )
    assert rc == 2
