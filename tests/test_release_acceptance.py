"""Distribution and executable-document acceptance contracts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ACCEPTANCE_FIXTURE = (
    REPO_ROOT / "skill/evals/fixtures/bilibili-pinned-collection"
)


def _command_fragments(markdown: str) -> list[str]:
    fenced = re.findall(r"```(?:bash|sh|zsh)?\n(.*?)```", markdown, re.DOTALL)
    inline = [
        line
        for line in markdown.splitlines()
        if "run_pipeline.py" in line
    ]
    return fenced + inline


def test_package_discovery_excludes_generated_workspace_namespace():
    """Removing constrained discovery would break a second editable install."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(
        r"\[tool\.setuptools\.packages\.find\]\s+(.*?)(?=\n\[|\Z)",
        pyproject,
        re.DOTALL,
    )

    assert section is not None
    assert re.search(r'^include\s*=\s*\[\s*"skill\*"\s*\]\s*$', section.group(1), re.MULTILINE)


def test_documented_classification_commands_enable_taxonomy_contract():
    """Every executable classification example must satisfy the CLI guard."""
    documents = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "USAGE.md",
        REPO_ROOT / "TESTING.md",
        REPO_ROOT / "skill/SKILL.md",
    ]
    violations = []
    for document in documents:
        for fragment in _command_fragments(document.read_text(encoding="utf-8")):
            if "run_pipeline.py" not in fragment or "--classification-results" not in fragment:
                continue
            if "--with-llm-tax" not in fragment:
                violations.append(document.name)

    assert violations == []


def test_packaged_acceptance_fixture_runs_taxonomy_draft(tmp_path):
    """Dropping the sealed fixture would make ZIP acceptance non-reproducible."""
    output = tmp_path / "taxonomy-draft"
    command = [
        sys.executable,
        str(REPO_ROOT / "skill/scripts/run_pipeline.py"),
        "--input",
        str(ACCEPTANCE_FIXTURE),
        "--output",
        str(output),
        "--with-llm-tax",
    ]

    completed = subprocess.run(command, capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
    assert (output / "taxonomy-prompt.md").is_file()
    assert (output / "taxonomy-input.jsonl").is_file()
    assert (output / "taxonomy-result-template.json").is_file()
    assert (output / "delivery-summary.json").is_file()
    assert (output / "final-response.md").is_file()
