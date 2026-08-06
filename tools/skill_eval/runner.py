#!/usr/bin/env python3
"""Skill 评估隔离 runner（Claude Code 无头模式）。

解决 iteration-1 的两个协议缺陷：

1. **物理隔离**：新建 Skill 时，without_skill 基线在一个不含任何 Skill 文件/元数据的
   全新临时工作区中运行，并叠加 ``--disable-slash-commands``（禁用全部
   Skill）与 ``--setting-sources project``（不加载用户级设置，杜绝
   ``~/.claude/skills`` 泄漏）。改进已有 Skill 时，``--baseline-skill-dir``
   把旧快照安装到同一个基线配置。with_skill 侧安装候选版本；两侧使用同一模型。
2. **标准目录结构与版本指纹**：产物固定写入
   ``<iteration>/eval-<name>/<config>/run-<n>/``，包含 run.json、
   response.md、timing.json（数值墙钟秒 + 可用时的 token 用量）与
   grading-input.json（断言清单，供独立 grader 填写 grading.json）；根元数据
   保存实际复制的 `SKILL.md` SHA-256，防止旧安装包被误当成当前版本。

token 说明：使用 ``--output-format json`` 时从 Claude Code 返回的
usage 字段读取；不可用时写 null，绝不估算。

前置条件：``claude`` CLI 已配置可用的 Anthropic 或 Ollama 兼容端点。runner
启动时做 preflight 冒烟；端点、认证或本地模型不可用时立即以 BLOCKED 退出，
不产出半成品目录。

用法::

    python tools/skill_eval/runner.py \
        --evals skill/evals/evals.json --ids vague-bilibili-strategy,user-data-no-recollection \
        --iteration workspace/skill-evals/claude-isolated/iteration-2 \
        --skill-dir skill --runs 3 [--model sonnet] [--timeout 900]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILL_NAME = "public-social-account-analyzer"
CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in name).strip("-")


def load_evals(path: Path, ids: Optional[List[str]]) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    evals = data.get("evals", [])
    if ids:
        evals = [e for e in evals if str(e.get("id")) in ids]
    if not evals:
        raise SystemExit("error: no evals selected")
    return evals


def preflight(model: str) -> None:
    """确认 claude CLI 可无头运行；失败即 BLOCKED 退出。"""
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "reply with exactly: OK", "--model", model,
             "--setting-sources", "project"],
            capture_output=True, text=True, timeout=120, cwd="/tmp",
        )
    except FileNotFoundError:
        raise SystemExit("BLOCKED: claude CLI not found")
    except subprocess.TimeoutExpired:
        raise SystemExit("BLOCKED: claude preflight timed out")
    combined = (proc.stdout + proc.stderr).lower()
    if "not logged in" in combined or "please run /login" in combined:
        raise SystemExit(
            "BLOCKED: claude CLI has no usable authentication/endpoint. "
            "Configure `claude /login` or an Ollama Anthropic-compatible "
            "endpoint first; the runner refuses to start half-runs."
        )
    if proc.returncode != 0:
        raise SystemExit(f"BLOCKED: claude preflight failed: {combined[:400]}")


def build_workspace(
    run_dir: Path, config: str, skill_dir: Optional[Path],
) -> Path:
    ws = run_dir / "workspace"
    ws.mkdir(parents=True)
    if skill_dir is not None:
        target = ws / ".claude" / "skills" / SKILL_NAME
        target.parent.mkdir(parents=True)
        shutil.copytree(
            skill_dir, target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    return ws


def claude_command(
    config: str, prompt: str, model: str, *, has_skill: bool,
) -> List[str]:
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--setting-sources", "project",
        "--dangerously-skip-permissions",
    ]
    if not has_skill:
        cmd.append("--disable-slash-commands")
    return cmd


def extract_usage(payload: Dict[str, Any]) -> Dict[str, Optional[int]]:
    usage = payload.get("usage")
    result: Dict[str, Optional[int]] = {
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
    }
    if isinstance(usage, dict):
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
        if isinstance(in_tok, int):
            result["input_tokens"] = in_tok
        if isinstance(out_tok, int):
            result["output_tokens"] = out_tok
        if isinstance(in_tok, int) and isinstance(out_tok, int):
            result["total_tokens"] = in_tok + out_tok
    return result


def execute_run(
    eval_def: Dict[str, Any], config: str, run_dir: Path,
    skill_dir: Optional[Path], model: str, timeout: int,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    ws = build_workspace(run_dir, config, skill_dir)
    cmd = claude_command(
        config, eval_def["prompt"], model, has_skill=skill_dir is not None
    )

    started = time.monotonic()
    status = "completed"
    stdout, stderr = "", ""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=ws,
        )
        stdout, stderr = proc.stdout, proc.stderr
        if proc.returncode != 0:
            status = f"exit_{proc.returncode}"
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        stdout = exc.stdout or "" if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr or "" if isinstance(exc.stderr, str) else ""
    duration = time.monotonic() - started

    response_text, usage = stdout, extract_usage({})
    try:
        payload = json.loads(stdout)
        if isinstance(payload, dict):
            response_text = payload.get("result", stdout)
            usage = extract_usage(payload)
    except json.JSONDecodeError:
        pass

    response_body = (
        response_text
        if isinstance(response_text, str)
        else json.dumps(response_text, ensure_ascii=False)
    )
    (run_dir / "response.md").write_text(response_body, encoding="utf-8")
    viewer_outputs = run_dir / "outputs"
    viewer_outputs.mkdir()
    (viewer_outputs / "response.md").write_text(
        response_body, encoding="utf-8"
    )
    (run_dir / "eval_metadata.json").write_text(json.dumps({
        "eval_id": eval_def.get("id"),
        "eval_name": eval_def.get("name"),
        "prompt": eval_def.get("prompt"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if stderr.strip():
        (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")

    (run_dir / "run.json").write_text(json.dumps({
        "eval_id": eval_def.get("id"),
        "eval_name": eval_def.get("name"),
        "config": config,
        "model": model,
        "isolation": {
            "kind": "physical",
            "bare_workspace": skill_dir is None,
            "skills_disabled_flag": skill_dir is None,
            "baseline_skill_installed": (
                config == "without_skill" and skill_dir is not None
            ),
            "setting_sources": "project",
        },
        "command_flags": cmd[3:],  # 不含 prompt 本体
        "status": status,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (run_dir / "timing.json").write_text(json.dumps({
        "total_duration_seconds": round(duration, 3),
        "timing_source": "runner_monotonic_wall_clock",
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "token_source": ("claude_output_json_usage"
                          if usage["total_tokens"] is not None else None),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (run_dir / "grading-input.json").write_text(json.dumps({
        "eval_id": eval_def.get("id"),
        "eval_name": eval_def.get("name"),
        "expected_output": eval_def.get("expected_output"),
        "assertions": eval_def.get("assertions", []),
        "grading_contract": (
            "逐条断言给出 passed(bool) 与 evidence；条件式断言未触发时"
            "写 na=true 且不计入分母；不得凭空补 timing/token。"
        ),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evals", required=True)
    parser.add_argument("--ids", default=None,
                        help="逗号分隔的 eval id 列表，缺省=全部")
    parser.add_argument("--iteration", required=True)
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument(
        "--baseline-skill-dir",
        default=None,
        help="已有 Skill 的旧快照；省略时使用无 Skill 基线",
    )
    parser.add_argument("--configs", default="with_skill,without_skill")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args(argv)

    ids = (
        [value.strip() for value in args.ids.split(",") if value.strip()]
        if args.ids
        else None
    )
    evals = load_evals(Path(args.evals), ids)
    skill_dir = Path(args.skill_dir).resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise SystemExit(f"error: {skill_dir} is not a skill directory")
    baseline_skill_dir = (
        Path(args.baseline_skill_dir).resolve()
        if args.baseline_skill_dir
        else None
    )
    if (
        baseline_skill_dir is not None
        and not (baseline_skill_dir / "SKILL.md").is_file()
    ):
        raise SystemExit(
            f"error: {baseline_skill_dir} is not a skill directory"
        )
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    if args.runs < 1:
        raise SystemExit("error: --runs must be >= 1")
    unsupported_configs = [c for c in configs if c not in {
        "with_skill", "without_skill",
    }]
    if unsupported_configs:
        raise SystemExit(
            "error: unsupported config(s): " + ", ".join(unsupported_configs)
        )

    if not args.skip_preflight:
        preflight(args.model)

    iteration = Path(args.iteration)
    iteration.mkdir(parents=True, exist_ok=True)
    skill_contract_sha256 = hashlib.sha256(
        (skill_dir / "SKILL.md").read_bytes()
    ).hexdigest()
    baseline_kind = (
        "previous_skill_snapshot"
        if baseline_skill_dir is not None
        else "physically_isolated_without_skill"
    )
    run_metadata = {
        "skill_name": SKILL_NAME,
        "skill_contract_sha256": skill_contract_sha256,
        "executor_model": args.model,
        "runs_per_configuration": args.runs,
        "configurations": configs,
        "baseline_kind": baseline_kind,
    }
    if baseline_skill_dir is not None:
        run_metadata["baseline_skill_contract_sha256"] = hashlib.sha256(
            (baseline_skill_dir / "SKILL.md").read_bytes()
        ).hexdigest()
    (iteration / "run-metadata.json").write_text(
        json.dumps(run_metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for eval_def in evals:
        eval_dir = iteration / f"eval-{slugify(eval_def['name'])}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "eval_metadata.json").write_text(json.dumps({
            "eval_id": eval_def.get("id"),
            "eval_name": eval_def.get("name"),
            "prompt": eval_def.get("prompt"),
            "model": args.model,
            "baseline_kind": baseline_kind,
            "assertions": eval_def.get("assertions", []),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for config in configs:
            for n in range(1, args.runs + 1):
                run_dir = eval_dir / config / f"run-{n}"
                if (run_dir / "run.json").exists():
                    print(f"skip existing {run_dir}")
                    continue
                print(f"run: eval={eval_def['name']} config={config} n={n}")
                config_skill_dir = (
                    skill_dir if config == "with_skill" else baseline_skill_dir
                )
                execute_run(
                    eval_def, config, run_dir, config_skill_dir,
                    args.model, args.timeout,
                )
    print(f"done. next: fill grading.json per run, then aggregate with "
          f"tools/skill_eval/aggregate.py {iteration}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
