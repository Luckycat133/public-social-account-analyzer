#!/usr/bin/env python3
"""Skill 评估标准聚合器（容错版）。

输入目录约定（标准布局）::

    <iteration-dir>/
      eval-<name>/
        eval_metadata.json                # 可选
        with_skill/
          run-1/grading.json              # 必需（至少一个 run-N）
          run-1/timing.json               # 可选
          run-2/...
        without_skill/
          run-1/grading.json
          ...

兼容旧布局：config 目录下直接放 grading.json / timing.json 时，
视作单次 run（run-1）。

grading.json 兼容字段：
- summary.passed / summary.failed / summary.total / summary.pass_rate
- 或 expectations: [{passed: bool, na: bool(optional), ...}] 自行统计。
  na=true 的断言不计入分母（条件式断言未触发时按 N/A 处理）。

timing 容错：total_duration_seconds 允许为 int/float/数字字符串；
null、非数字字符串、缺失、对象等一律归一化为 None，绝不抛异常。

输出：benchmark.json（结构化）与 benchmark.md（可读表格），含
宏平均/微平均通过率、逐题 delta、可用 timing 聚合，以及每题每配置
多次 run 的通过率均值/标准差（run 数 >= 2 时）。

用法::

    python tools/skill_eval/aggregate.py <iteration-dir> [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_NAMES = ("with_skill", "without_skill")


# ---------------------------------------------------------------------------
# 容错解析
# ---------------------------------------------------------------------------

def coerce_duration_seconds(value: Any) -> Optional[float]:
    """把任意形态的耗时值归一化为非负 float 或 None。"""
    if isinstance(value, bool):  # bool 是 int 子类，显式排除
        return None
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)) and float(value) >= 0:
            return float(value)
        return None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except (ValueError, AttributeError):
            return None
        if math.isfinite(parsed) and parsed >= 0:
            return parsed
        return None
    return None  # None / dict / list / 其他一律视为不可用


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def parse_grading(grading: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 grading.json 提取 passed/failed/na/total。返回 None 表示不可用。"""
    summary = grading.get("summary")
    if isinstance(summary, dict):
        passed = summary.get("passed")
        total = summary.get("total")
        if isinstance(passed, int) and isinstance(total, int) and total >= 0:
            na = summary.get("na")
            na = na if isinstance(na, int) and na >= 0 else 0
            effective_total = total - na
            if effective_total < 0:
                return None
            return {
                "passed": passed,
                "failed": effective_total - passed,
                "na": na,
                "total": effective_total,
            }
    expectations = grading.get("expectations")
    if isinstance(expectations, list) and expectations:
        passed = failed = na = 0
        for item in expectations:
            if not isinstance(item, dict):
                return None
            if item.get("na") is True:
                na += 1
            elif item.get("passed") is True:
                passed += 1
            else:
                failed += 1
        return {"passed": passed, "failed": failed, "na": na,
                "total": passed + failed}
    return None


def extract_timing(run_dir: Path, grading: Optional[Dict[str, Any]]) -> Optional[float]:
    """优先 timing.json，其次 grading.timing；全部容错。"""
    timing = load_json(run_dir / "timing.json")
    if timing is not None:
        for key in ("total_duration_seconds", "duration_seconds"):
            got = coerce_duration_seconds(timing.get(key))
            if got is not None:
                return got
        got = coerce_duration_seconds(timing.get("duration_ms"))
        if got is not None:
            return got / 1000.0
    if grading is not None:
        tblock = grading.get("timing")
        if isinstance(tblock, dict):
            got = coerce_duration_seconds(tblock.get("total_duration_seconds"))
            if got is not None:
                return got
    return None


# ---------------------------------------------------------------------------
# 目录扫描
# ---------------------------------------------------------------------------

def discover_runs(config_dir: Path) -> List[Path]:
    """返回 run 目录列表；兼容旧布局（config 根即单 run）。"""
    runs = sorted(
        (p for p in config_dir.iterdir() if p.is_dir() and p.name.startswith("run-")),
        key=lambda p: p.name,
    ) if config_dir.is_dir() else []
    if runs:
        return runs
    if (config_dir / "grading.json").is_file():
        return [config_dir]  # 旧布局：config 目录本身是唯一 run
    return []


def mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def stdev(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mu = sum(values) / len(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (len(values) - 1))


def aggregate_config(config_dir: Path) -> Dict[str, Any]:
    run_dirs = discover_runs(config_dir)
    runs: List[Dict[str, Any]] = []
    for run_dir in run_dirs:
        grading = load_json(run_dir / "grading.json")
        parsed = parse_grading(grading) if grading else None
        duration = extract_timing(run_dir, grading)
        entry: Dict[str, Any] = {
            "run": run_dir.name if run_dir != config_dir else "run-1",
            "grading_available": parsed is not None,
            "total_duration_seconds": duration,
        }
        if parsed:
            entry.update(parsed)
            entry["pass_rate"] = (
                parsed["passed"] / parsed["total"] if parsed["total"] else None
            )
        runs.append(entry)

    rates = [r["pass_rate"] for r in runs
             if r.get("pass_rate") is not None]
    durations = [r["total_duration_seconds"] for r in runs
                 if r.get("total_duration_seconds") is not None]
    graded = [r for r in runs if r["grading_available"]]
    return {
        "runs": runs,
        "run_count": len(runs),
        "graded_run_count": len(graded),
        "passed": sum(r.get("passed", 0) for r in graded),
        "total": sum(r.get("total", 0) for r in graded),
        "na": sum(r.get("na", 0) for r in graded),
        "pass_rate_mean": mean(rates),
        "pass_rate_stdev": stdev(rates),
        "duration_seconds_mean": mean(durations),
        "duration_available_runs": len(durations),
    }


def aggregate_iteration(iteration_dir: Path) -> Dict[str, Any]:
    evals: List[Dict[str, Any]] = []
    for eval_dir in sorted(iteration_dir.iterdir()):
        if not eval_dir.is_dir() or not eval_dir.name.startswith("eval-"):
            continue
        meta = load_json(eval_dir / "eval_metadata.json") or {}
        entry: Dict[str, Any] = {
            "eval": eval_dir.name.removeprefix("eval-"),
            "metadata": {k: meta.get(k) for k in
                         ("eval_id", "model", "reasoning_effort", "baseline_kind")
                         if k in meta},
            "configs": {},
        }
        for config in CONFIG_NAMES:
            entry["configs"][config] = aggregate_config(eval_dir / config)
        ws = entry["configs"]["with_skill"]
        wos = entry["configs"]["without_skill"]
        if ws["pass_rate_mean"] is not None and wos["pass_rate_mean"] is not None:
            entry["delta_pp"] = round(
                (ws["pass_rate_mean"] - wos["pass_rate_mean"]) * 100, 1
            )
        else:
            entry["delta_pp"] = None
        evals.append(entry)

    summary: Dict[str, Any] = {"evals_counted": len(evals)}
    for config in CONFIG_NAMES:
        rates = [e["configs"][config]["pass_rate_mean"] for e in evals
                 if e["configs"][config]["pass_rate_mean"] is not None]
        passed = sum(e["configs"][config]["passed"] for e in evals)
        total = sum(e["configs"][config]["total"] for e in evals)
        summary[config] = {
            "macro_pass_rate": mean(rates),
            "micro_passed": passed,
            "micro_total": total,
            "micro_pass_rate": (passed / total) if total else None,
        }
    return {"iteration": iteration_dir.name, "evals": evals, "summary": summary}


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def fmt_rate(value: Optional[float]) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def fmt_num(value: Optional[float], suffix: str = "") -> str:
    return f"{value:.1f}{suffix}" if value is not None else "n/a"


def render_markdown(result: Dict[str, Any]) -> str:
    lines = [f"# Skill Eval Benchmark — {result['iteration']}", ""]
    lines.append(
        "| Eval | With Skill | runs | σ | Without Skill | runs | σ | Delta |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for entry in result["evals"]:
        ws = entry["configs"]["with_skill"]
        wos = entry["configs"]["without_skill"]
        delta = (f"{entry['delta_pp']:+.1f}pp"
                 if entry["delta_pp"] is not None else "n/a")
        lines.append(
            f"| {entry['eval']} | {fmt_rate(ws['pass_rate_mean'])}"
            f" | {ws['graded_run_count']} | {fmt_num(ws['pass_rate_stdev'])}"
            f" | {fmt_rate(wos['pass_rate_mean'])}"
            f" | {wos['graded_run_count']} | {fmt_num(wos['pass_rate_stdev'])}"
            f" | {delta} |"
        )
    lines.append("")
    summary = result["summary"]
    for config in CONFIG_NAMES:
        block = summary[config]
        lines.append(
            f"- **{config}**：宏平均 {fmt_rate(block['macro_pass_rate'])}，"
            f"微平均 {block['micro_passed']}/{block['micro_total']}"
            f"（{fmt_rate(block['micro_pass_rate'])}）"
        )
    lines.append("")
    lines.append("> N/A 断言（条件未触发）不计入分母。"
                 "耗时缺失的 run 不参与耗时聚合，绝不以 0 回填。")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iteration_dir", help="iteration 目录路径")
    parser.add_argument("--out", default=None,
                        help="输出目录（默认写回 iteration 目录）")
    args = parser.parse_args(argv)

    iteration_dir = Path(args.iteration_dir)
    if not iteration_dir.is_dir():
        print(f"error: not a directory: {iteration_dir}", file=sys.stderr)
        return 2
    result = aggregate_iteration(iteration_dir)
    if not result["evals"]:
        print("error: no eval-* directories found", file=sys.stderr)
        return 3

    out_dir = Path(args.out) if args.out else iteration_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "benchmark.md").write_text(
        render_markdown(result), encoding="utf-8"
    )
    print(f"benchmark written to {out_dir}/benchmark.json and benchmark.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
