"""Behavioral tests for the isolated Skill benchmark runner."""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "skill_eval"))

import runner  # noqa: E402


def _prepare_inputs(tmp_path: Path) -> tuple[Path, Path]:
    evals = tmp_path / "evals.json"
    evals.write_text(json.dumps({
        "evals": [{
            "id": 1,
            "name": "paired-probe",
            "prompt": "Run the probe",
            "expected_output": "A bounded response",
            "assertions": ["The response is bounded"],
        }],
    }), encoding="utf-8")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: probe\ndescription: Use this skill for the probe.\n---\n",
        encoding="utf-8",
    )
    return evals, skill


def test_runner_defaults_to_three_paired_repetitions(
    tmp_path: Path, monkeypatch,
):
    """Omitting --runs still produces three runs for both configurations."""
    evals, skill = _prepare_inputs(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_execute(eval_def, config, run_dir, skill_dir, model, timeout):
        calls.append((config, run_dir.name))

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    iteration = tmp_path / "iteration-1"

    assert runner.main([
        "--evals", str(evals),
        "--iteration", str(iteration),
        "--skill-dir", str(skill),
        "--skip-preflight",
    ]) == 0
    assert calls == [
        ("with_skill", "run-1"),
        ("with_skill", "run-2"),
        ("with_skill", "run-3"),
        ("without_skill", "run-1"),
        ("without_skill", "run-2"),
        ("without_skill", "run-3"),
    ]


def test_runner_records_declared_protocol_before_execution(
    tmp_path: Path, monkeypatch,
):
    """The aggregator can compare declared repetitions with observed runs."""
    evals, skill = _prepare_inputs(tmp_path)
    monkeypatch.setattr(runner, "execute_run", lambda *args, **kwargs: None)
    iteration = tmp_path / "iteration-2"

    assert runner.main([
        "--evals", str(evals),
        "--iteration", str(iteration),
        "--skill-dir", str(skill),
        "--runs", "2",
        "--model", "local-model",
        "--skip-preflight",
    ]) == 0

    metadata = json.loads(
        (iteration / "run-metadata.json").read_text(encoding="utf-8")
    )
    contract_sha = hashlib.sha256(
        (skill / "SKILL.md").read_bytes()
    ).hexdigest()
    assert metadata == {
        "skill_name": "public-social-account-analyzer",
        "skill_contract_sha256": contract_sha,
        "executor_model": "local-model",
        "runs_per_configuration": 2,
        "configurations": ["with_skill", "without_skill"],
        "baseline_kind": "physically_isolated_without_skill",
    }


def test_runner_selects_string_eval_ids(tmp_path: Path, monkeypatch):
    evals, skill = _prepare_inputs(tmp_path)
    evals.write_text(
        json.dumps(
            {
                "evals": [
                    {
                        "id": "real-user-task",
                        "name": "selected",
                        "prompt": "Selected prompt",
                        "expected_output": "Selected output",
                        "assertions": ["Selected assertion"],
                    },
                    {
                        "id": "other-task",
                        "name": "other",
                        "prompt": "Other prompt",
                        "expected_output": "Other output",
                        "assertions": ["Other assertion"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    selected = []

    def fake_execute(eval_def, *args, **kwargs):
        selected.append(eval_def["id"])

    monkeypatch.setattr(runner, "execute_run", fake_execute)

    assert runner.main(
        [
            "--evals",
            str(evals),
            "--ids",
            "real-user-task",
            "--iteration",
            str(tmp_path / "iteration-strings"),
            "--skill-dir",
            str(skill),
            "--runs",
            "1",
            "--skip-preflight",
        ]
    ) == 0
    assert selected == ["real-user-task", "real-user-task"]


def test_runner_can_install_previous_skill_as_the_baseline(
    tmp_path: Path, monkeypatch,
):
    evals, skill = _prepare_inputs(tmp_path)
    previous = tmp_path / "previous-skill"
    previous.mkdir()
    (previous / "SKILL.md").write_text(
        "---\nname: probe\ndescription: Old probe.\n---\n",
        encoding="utf-8",
    )
    calls = []

    def fake_execute(eval_def, config, run_dir, skill_dir, model, timeout):
        calls.append((config, skill_dir))

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    iteration = tmp_path / "iteration-old-baseline"

    assert runner.main([
        "--evals", str(evals),
        "--iteration", str(iteration),
        "--skill-dir", str(skill),
        "--baseline-skill-dir", str(previous),
        "--runs", "1",
        "--skip-preflight",
    ]) == 0
    assert calls == [
        ("with_skill", skill.resolve()),
        ("without_skill", previous.resolve()),
    ]
    metadata = json.loads(
        (iteration / "run-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["baseline_kind"] == "previous_skill_snapshot"
    assert metadata["baseline_skill_contract_sha256"] == hashlib.sha256(
        (previous / "SKILL.md").read_bytes()
    ).hexdigest()


def test_execute_run_emits_skill_creator_viewer_layout(
    tmp_path: Path, monkeypatch,
):
    """Each run is directly discoverable by skill-creator's eval viewer."""
    _, skill = _prepare_inputs(tmp_path)
    eval_def = {
        "id": 7,
        "name": "viewer-probe",
        "prompt": "Render the viewer probe",
        "expected_output": "A visible response",
        "assertions": ["The response is visible"],
    }

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps({
                "result": "viewer response",
                "usage": {"input_tokens": 2, "output_tokens": 3},
            }),
            stderr="",
            returncode=0,
        ),
    )
    run_dir = tmp_path / "iteration" / "eval-viewer" / "with_skill" / "run-1"

    runner.execute_run(
        eval_def,
        "with_skill",
        run_dir,
        skill,
        "local-model",
        30,
    )

    assert (run_dir / "response.md").read_text(encoding="utf-8") == (
        "viewer response"
    )
    assert (run_dir / "outputs" / "response.md").read_text(
        encoding="utf-8"
    ) == "viewer response"
    metadata = json.loads(
        (run_dir / "eval_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata == {
        "eval_id": 7,
        "eval_name": "viewer-probe",
        "prompt": "Render the viewer probe",
    }
