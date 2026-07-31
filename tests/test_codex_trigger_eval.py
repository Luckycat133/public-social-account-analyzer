"""Contracts for the Codex/Terra Skill-trigger evaluation harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "skill_eval"))

import codex_trigger  # noqa: E402


SKILL_PATH = REPO_ROOT / "skill" / "SKILL.md"


def test_event_reads_skill_from_command_execution():
    event = {
        "type": "item.started",
        "item": {
            "type": "command_execution",
            "command": "/bin/zsh -lc \"sed -n '1,240p' skill/SKILL.md\"",
        },
    }

    assert codex_trigger.event_reads_skill(event, SKILL_PATH, REPO_ROOT)


def test_event_does_not_match_other_skill_or_plain_message():
    other = {
        "type": "item.started",
        "item": {
            "type": "command_execution",
            "command": "cat /tmp/other-skill/SKILL.md",
        },
    }
    message = {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "I will use a skill."},
    }

    assert not codex_trigger.event_reads_skill(other, SKILL_PATH, REPO_ROOT)
    assert not codex_trigger.event_reads_skill(message, SKILL_PATH, REPO_ROOT)


def test_summarize_uses_majority_threshold_for_positive_and_negative_queries():
    eval_set = [
        {"id": "pos", "query": "analyze account", "should_trigger": True},
        {"id": "neg", "query": "download video", "should_trigger": False},
    ]
    observations = {
        "pos": [True, True, False],
        "neg": [False, False, True],
    }

    result = codex_trigger.summarize_results(
        eval_set, observations, threshold=0.5
    )

    assert result["summary"] == {
        "queries": 2,
        "passed": 2,
        "failed": 0,
        "runs": 6,
        "correct_runs": 4,
        "accuracy": 2 / 3,
    }
    by_id = {item["id"]: item for item in result["results"]}
    assert by_id["pos"]["trigger_rate"] == 2 / 3
    assert by_id["pos"]["pass"] is True
    assert by_id["neg"]["trigger_rate"] == 1 / 3
    assert by_id["neg"]["pass"] is True


def test_load_eval_set_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "queries.json"
    path.write_text(json.dumps([
        {"id": "same", "query": "one", "should_trigger": True},
        {"id": "same", "query": "two", "should_trigger": False},
    ]), encoding="utf-8")

    try:
        codex_trigger.load_eval_set(path)
    except ValueError as exc:
        assert "duplicate id" in str(exc)
    else:
        raise AssertionError("duplicate IDs must be rejected")
