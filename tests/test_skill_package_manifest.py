"""Offline tests for the .skill archive layout — minimal-shippable guard.

Background: 0.9.2 retired `scripts/README.md` (redundant with SKILL.md) and
renamed `scripts/legacy/` (a misleading name) to `scripts/analysis/`. The
analysis engine is the runtime surface that `run_pipeline.py` and `collect.py`
import — it is required in the published archive. These tests assert:

  * `scripts/README.md` is gone from the source tree.
  * `scripts/analysis/` is present (the analysis engine is required).
  * None of the live entry points reach into `scripts/legacy/` (the old
    name) — they must import from `analysis.X`.
  * The `.skill` archive excludes repo-only paths
    (`evals/`, `tests/`, `docs/`, `tools/`, `workspace/`).
  * The archive size is bounded so future regressions get caught.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = REPO_ROOT / "skill"


# Paths that MUST NOT appear in the source tree.
FORBIDDEN_SOURCE_PATHS = (
    SKILL_ROOT / "scripts" / "README.md",
    SKILL_ROOT / "scripts" / "legacy",
)


# Paths that MUST NOT appear inside the published .skill archive.
FORBIDDEN_ARCHIVE_FRAGMENTS = (
    "scripts/README.md",
    "scripts/legacy/",
    "evals/",
    "tests/",
    "docs/",
    "tools/",
    "workspace/",
)


def test_skill_root_no_longer_includes_readme() -> None:
    """`scripts/README.md` was removed in 0.9.2; SKILL.md is the entry point."""
    assert not (SKILL_ROOT / "scripts" / "README.md").exists()


def test_legacy_directory_removed() -> None:
    """`scripts/legacy/` was renamed to `scripts/analysis/` in 0.9.2."""
    legacy = SKILL_ROOT / "scripts" / "legacy"
    assert not legacy.exists(), (
        f"Found {legacy}; rename it to scripts/analysis/ instead."
    )


def test_analysis_engine_present() -> None:
    """`scripts/analysis/` is the analysis engine that runs from run_pipeline.py.

    These three files are imported by `run_pipeline.py` and `collect.py` at
    runtime via `from analysis.X import ...`. The directory name now
    reflects the actual responsibility: the analysis engine.
    """
    engine = SKILL_ROOT / "scripts" / "analysis"
    assert engine.is_dir(), f"Missing analysis engine: {engine}"
    assert (engine / "__init__.py").is_file(), f"Missing {engine}/__init__.py"
    for name in ("analyze.py", "normalize.py", "render_report.py"):
        assert (engine / name).is_file(), f"Missing {name} in {engine}"


def test_collect_entry_points_import_from_analysis_subpackage() -> None:
    """Live entry points must import from `analysis.X`, not from a flat
    top-level module that prevents the engine from being a proper package."""
    expected_imports = {
        SKILL_ROOT / "scripts" / "run_pipeline.py": [
            "from analysis.analyze import",
            "from analysis.normalize import",
            "from analysis.render_report import",
        ],
        SKILL_ROOT / "scripts" / "collect.py": [
            "from analysis.normalize import",
        ],
    }
    for path, needles in expected_imports.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, (
                f"{path.relative_to(REPO_ROOT)} missing {needle!r}"
            )


def test_collect_entry_points_reject_legacy_path_imports() -> None:
    """No entry point should reach into `scripts/legacy/` (the old name)."""
    forbidden_substrings = (
        "scripts.legacy",
        "from legacy",
        "import legacy",
        "legacy.normalize",
        "legacy.analyze",
        "legacy.render_report",
    )
    entry_points = [
        SKILL_ROOT / "scripts" / "collect.py",
        SKILL_ROOT / "scripts" / "run_pipeline.py",
        SKILL_ROOT / "scripts" / "collect_bilibili_complete.py",
        SKILL_ROOT / "scripts" / "collect_douyin_complete.py",
        SKILL_ROOT / "scripts" / "collect_douyin_authorized.py",
        SKILL_ROOT / "scripts" / "import_index_snapshot.py",
    ]
    for path in entry_points:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, (
                f"{path.relative_to(REPO_ROOT)} still references {needle!r}"
            )


@pytest.mark.skipif(
    not (Path("/Users/jack/.agents/skills/skill-creator/scripts/package_skill.py").exists()),
    reason="skill-creator's package_skill.py is not available in this environment",
)
def test_packaged_archive_excludes_repo_only_paths() -> None:
    """Run the actual packager and assert the archive layout is minimal."""
    packager = Path("/Users/jack/.agents/skills/skill-creator/scripts/package_skill.py")
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "skill.skill"
        completed = subprocess.run(
            [
                sys.executable,
                str(packager),
                str(SKILL_ROOT),
                str(tmpdir),
            ],
            cwd=str(packager.parent.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(packager.parent.parent)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()

        # Forbid repo-only fragments.
        for fragment in FORBIDDEN_ARCHIVE_FRAGMENTS:
            offenders = [name for name in names if fragment in name]
            assert not offenders, (
                f"Archive contains forbidden fragment {fragment!r}: {offenders}"
            )

        # 0.9.2 archive: 2 (SKILL.md, VERSION) + 1 agents + 1 assets
        # + 17 references + 16 top-level scripts + 1 analysis/__init__.py
        # + 3 analysis modules + 18 collectors = 59 files.
        # We cap at 70 to leave headroom for hotfixes without allowing
        # silent regressions back to the historical 80+ file range.
        assert 50 <= len(names) <= 70, (
            f"Archive has {len(names)} files; expected 50–70 after 0.9.2 trims"
        )

        # Spot-check that the entry-point files are present.
        required = (
            "skill/SKILL.md",
            "skill/VERSION",
            "skill/scripts/collect.py",
            "skill/scripts/run_pipeline.py",
            "skill/scripts/analysis/__init__.py",
            "skill/scripts/analysis/analyze.py",
            "skill/scripts/collectors/__init__.py",
            "skill/assets/report-template.html",
        )
        for entry in required:
            assert entry in names, f"Archive missing required entry: {entry}"
