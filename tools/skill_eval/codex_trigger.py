#!/usr/bin/env python3
"""Measure whether Codex loads this Skill for natural user queries.

The harness launches a fresh ephemeral Codex/Terra process for every run and
stops at the first actionable tool event. A run triggers only when that event
reads the target ``SKILL.md``. This measures description-based discovery, not
task quality after a caller has explicitly supplied the Skill path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CODEX = (
    shutil.which("codex")
    or "/Applications/ChatGPT.app/Contents/Resources/codex"
)


def load_eval_set(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("eval set must be a non-empty JSON array")
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("every eval item must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("every eval item needs a non-empty string id")
        if item_id in seen:
            raise ValueError("duplicate id: %s" % item_id)
        seen.add(item_id)
        if not isinstance(item.get("query"), str) or not item["query"].strip():
            raise ValueError("%s has no query" % item_id)
        if not isinstance(item.get("should_trigger"), bool):
            raise ValueError("%s should_trigger must be boolean" % item_id)
    return payload


def event_reads_skill(
    event: Dict[str, Any], skill_path: Path, project_root: Path
) -> bool:
    item = event.get("item")
    if not isinstance(item, dict):
        return False
    absolute = str(skill_path.resolve())
    try:
        relative = str(skill_path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        relative = ""

    def strings(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for nested in value.values():
                yield from strings(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from strings(nested)

    # A plain substring check would treat
    # ``/tmp/other-skill/SKILL.md`` as this repository's ``skill/SKILL.md``.
    # Match each raw event field and require a shell-style path boundary.
    pattern = None
    if relative:
        pattern = re.compile(
            r"(?:^|[\s'\"=])(?:\./)?%s(?:$|[\s'\";,])"
            % re.escape(relative)
        )
    for value in strings(item):
        if absolute in value or (pattern and pattern.search(value)):
            return True
    return False


def _is_actionable_event(event: Dict[str, Any]) -> bool:
    if event.get("type") not in {"item.started", "item.completed"}:
        return False
    item = event.get("item")
    if not isinstance(item, dict):
        return False
    return item.get("type") not in {
        None,
        "agent_message",
        "reasoning",
        "plan",
    }


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run_single(
    query: str,
    skill_path: Path,
    project_root: Path,
    codex_bin: str,
    model: str,
    reasoning_effort: str,
    timeout: int,
) -> Dict[str, Any]:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "-m",
        model,
        "-c",
        "model_reasoning_effort=%s" % json.dumps(reasoning_effort),
        "-s",
        "read-only",
        "-C",
        str(project_root),
        query,
    ]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(project_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    triggered = False
    reason = "timeout"
    observed_action = None
    try:
        while time.monotonic() - started < timeout:
            if process.poll() is not None:
                reason = "process_exit"
                break
            events = selector.select(timeout=0.5)
            for key, _ in events:
                line = key.fileobj.readline()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event_reads_skill(event, skill_path, project_root):
                    triggered = True
                    reason = "target_skill_read"
                    observed_action = event.get("item")
                    return {
                        "triggered": triggered,
                        "reason": reason,
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "observed_action": observed_action,
                    }
                if _is_actionable_event(event):
                    reason = "other_first_action"
                    observed_action = event.get("item")
                    return {
                        "triggered": False,
                        "reason": reason,
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "observed_action": observed_action,
                    }
                if event.get("type") in {"turn.completed", "turn.failed"}:
                    reason = event.get("type")
                    break
        return {
            "triggered": triggered,
            "reason": reason,
            "duration_seconds": round(time.monotonic() - started, 3),
            "observed_action": observed_action,
        }
    finally:
        selector.close()
        _stop_process(process)


def summarize_results(
    eval_set: List[Dict[str, Any]],
    observations: Dict[str, List[bool]],
    threshold: float,
) -> Dict[str, Any]:
    results = []
    correct_runs = 0
    total_runs = 0
    for item in eval_set:
        values = observations[item["id"]]
        trigger_rate = sum(values) / len(values)
        should_trigger = item["should_trigger"]
        passed = (
            trigger_rate >= threshold
            if should_trigger
            else trigger_rate < threshold
        )
        correct_runs += sum(
            value == should_trigger for value in values
        )
        total_runs += len(values)
        results.append({
            "id": item["id"],
            "query": item["query"],
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": sum(values),
            "runs": len(values),
            "pass": passed,
        })
    passed_queries = sum(item["pass"] for item in results)
    return {
        "results": results,
        "summary": {
            "queries": len(results),
            "passed": passed_queries,
            "failed": len(results) - passed_queries,
            "runs": total_runs,
            "correct_runs": correct_runs,
            "accuracy": correct_runs / total_runs,
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--skill-path", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--codex-bin", default=DEFAULT_CODEX)
    args = parser.parse_args(argv)

    eval_set = load_eval_set(Path(args.eval_set))
    skill_path = Path(args.skill_path).resolve()
    project_root = Path(args.project_root).resolve()
    if not skill_path.is_file():
        raise SystemExit("skill path does not exist: %s" % skill_path)
    if args.runs < 1 or args.workers < 1:
        raise SystemExit("runs and workers must be positive")

    details = []
    observations = {item["id"]: [] for item in eval_set}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for item in eval_set:
            for run_number in range(1, args.runs + 1):
                future = executor.submit(
                    run_single,
                    item["query"],
                    skill_path,
                    project_root,
                    args.codex_bin,
                    args.model,
                    args.reasoning_effort,
                    args.timeout,
                )
                futures[future] = (item, run_number)
        for future in as_completed(futures):
            item, run_number = futures[future]
            result = future.result()
            observations[item["id"]].append(result["triggered"])
            details.append({
                "id": item["id"],
                "run": run_number,
                **result,
            })
            print(
                "[%s] run=%d triggered=%s reason=%s"
                % (item["id"], run_number, result["triggered"], result["reason"]),
                flush=True,
            )

    summary = summarize_results(eval_set, observations, args.threshold)
    payload = {
        "protocol": {
            "executor": "codex exec --json --ephemeral",
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "runs_per_query": args.runs,
            "trigger_threshold": args.threshold,
            "skill_path": str(skill_path),
            "detection": "target SKILL.md read before any other actionable event",
        },
        **summary,
        "run_details": sorted(details, key=lambda row: (row["id"], row["run"])),
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
