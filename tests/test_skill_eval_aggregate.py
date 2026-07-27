"""tools/skill_eval/aggregate.py 的容错与聚合契约测试。

覆盖 iteration-1 暴露的兼容性问题：
- run-N 层缺失（旧布局：grading.json 直接在 config 目录下）
- timing 以 null / 字符串 / 缺失 / 对象等异构形态出现
- 条件式断言 na=true 不计入分母
- 多次 run 的均值与标准差
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "skill_eval"))

import aggregate  # noqa: E402


# ---------------------------------------------------------------------------
# coerce_duration_seconds：异构 timing 归一化
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        (12.5, 12.5),
        (0, 0.0),
        ("34.2", 34.2),
        (" 7 ", 7.0),
        (None, None),
        ("unavailable", None),
        ("", None),
        ({"seconds": 3}, None),
        ([3], None),
        (True, None),
        (False, None),
        (-1, None),
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_coerce_duration_handles_heterogeneous_values(raw, expected):
    assert aggregate.coerce_duration_seconds(raw) == expected


# ---------------------------------------------------------------------------
# 目录构造辅助
# ---------------------------------------------------------------------------

def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _grading(passed: int, failed: int, na: int = 0) -> dict:
    expectations = (
        [{"text": f"p{i}", "passed": True} for i in range(passed)]
        + [{"text": f"f{i}", "passed": False} for i in range(failed)]
        + [{"text": f"n{i}", "passed": False, "na": True} for i in range(na)]
    )
    return {"expectations": expectations}


# ---------------------------------------------------------------------------
# 布局兼容
# ---------------------------------------------------------------------------

def test_standard_run_layout_is_aggregated(tmp_path: Path):
    it = tmp_path / "iteration-x"
    _write(it / "eval-a/with_skill/run-1/grading.json", _grading(3, 1))
    _write(it / "eval-a/with_skill/run-1/timing.json",
           {"total_duration_seconds": 60.0})
    _write(it / "eval-a/without_skill/run-1/grading.json", _grading(1, 3))
    result = aggregate.aggregate_iteration(it)
    entry = result["evals"][0]
    assert entry["configs"]["with_skill"]["pass_rate_mean"] == 0.75
    assert entry["configs"]["with_skill"]["duration_seconds_mean"] == 60.0
    assert entry["configs"]["without_skill"]["pass_rate_mean"] == 0.25
    assert entry["delta_pp"] == 50.0


def test_legacy_layout_without_run_dir_is_treated_as_single_run(tmp_path: Path):
    it = tmp_path / "iteration-legacy"
    _write(it / "eval-a/with_skill/grading.json", _grading(2, 0))
    _write(it / "eval-a/without_skill/grading.json", _grading(0, 2))
    result = aggregate.aggregate_iteration(it)
    entry = result["evals"][0]
    assert entry["configs"]["with_skill"]["graded_run_count"] == 1
    assert entry["configs"]["with_skill"]["pass_rate_mean"] == 1.0
    assert entry["delta_pp"] == 100.0


def test_missing_config_dir_yields_empty_not_crash(tmp_path: Path):
    it = tmp_path / "iteration-partial"
    _write(it / "eval-a/with_skill/run-1/grading.json", _grading(1, 0))
    result = aggregate.aggregate_iteration(it)
    entry = result["evals"][0]
    assert entry["configs"]["without_skill"]["run_count"] == 0
    assert entry["configs"]["without_skill"]["pass_rate_mean"] is None
    assert entry["delta_pp"] is None


# ---------------------------------------------------------------------------
# timing 缺失值兼容（iteration-1 实际出现的四种形态）
# ---------------------------------------------------------------------------

def test_timing_null_string_missing_object_all_tolerated(tmp_path: Path):
    it = tmp_path / "iteration-timing"
    base = it / "eval-a/with_skill"
    _write(base / "run-1/grading.json", _grading(1, 0))
    _write(base / "run-1/timing.json", {"total_duration_seconds": None})
    _write(base / "run-2/grading.json", _grading(1, 0))
    _write(base / "run-2/timing.json",
           {"total_duration_seconds": "not_provided_by_subagent_notification"})
    _write(base / "run-3/grading.json", _grading(1, 0))  # timing.json 缺失
    _write(base / "run-4/grading.json", _grading(1, 0))
    _write(base / "run-4/timing.json",
           {"total_duration_seconds": {"value": 5}})
    _write(base / "run-5/grading.json", _grading(1, 0))
    _write(base / "run-5/timing.json", {"total_duration_seconds": "42.5"})
    result = aggregate.aggregate_iteration(it)
    cfg = result["evals"][0]["configs"]["with_skill"]
    assert cfg["graded_run_count"] == 5
    assert cfg["duration_available_runs"] == 1
    assert cfg["duration_seconds_mean"] == 42.5  # 缺失不回填 0


def test_timing_fallback_to_grading_timing_block(tmp_path: Path):
    it = tmp_path / "iteration-fb"
    grading = _grading(1, 0)
    grading["timing"] = {"total_duration_seconds": 12}
    _write(it / "eval-a/with_skill/run-1/grading.json", grading)
    result = aggregate.aggregate_iteration(it)
    cfg = result["evals"][0]["configs"]["with_skill"]
    assert cfg["duration_seconds_mean"] == 12.0


# ---------------------------------------------------------------------------
# 条件式断言 N/A 与多 run 方差
# ---------------------------------------------------------------------------

def test_na_assertions_are_excluded_from_denominator(tmp_path: Path):
    it = tmp_path / "iteration-na"
    _write(it / "eval-a/with_skill/run-1/grading.json", _grading(5, 0, na=1))
    result = aggregate.aggregate_iteration(it)
    cfg = result["evals"][0]["configs"]["with_skill"]
    assert cfg["total"] == 5
    assert cfg["na"] == 1
    assert cfg["pass_rate_mean"] == 1.0


def test_summary_na_field_is_honoured(tmp_path: Path):
    it = tmp_path / "iteration-na2"
    _write(it / "eval-a/with_skill/run-1/grading.json",
           {"summary": {"passed": 4, "total": 6, "na": 2}})
    result = aggregate.aggregate_iteration(it)
    cfg = result["evals"][0]["configs"]["with_skill"]
    assert cfg["total"] == 4
    assert cfg["pass_rate_mean"] == 1.0


def test_multi_run_mean_and_stdev(tmp_path: Path):
    it = tmp_path / "iteration-var"
    base = it / "eval-a/with_skill"
    _write(base / "run-1/grading.json", _grading(4, 0))   # 1.0
    _write(base / "run-2/grading.json", _grading(2, 2))   # 0.5
    _write(base / "run-3/grading.json", _grading(3, 1))   # 0.75
    result = aggregate.aggregate_iteration(it)
    cfg = result["evals"][0]["configs"]["with_skill"]
    assert cfg["pass_rate_mean"] == 0.75
    assert cfg["pass_rate_stdev"] == 0.25


def test_corrupt_grading_json_marks_run_ungraded(tmp_path: Path):
    it = tmp_path / "iteration-bad"
    run = it / "eval-a/with_skill/run-1"
    run.mkdir(parents=True)
    (run / "grading.json").write_text("{not json", encoding="utf-8")
    result = aggregate.aggregate_iteration(it)
    cfg = result["evals"][0]["configs"]["with_skill"]
    assert cfg["run_count"] == 1
    assert cfg["graded_run_count"] == 0
    assert cfg["pass_rate_mean"] is None


# ---------------------------------------------------------------------------
# 端到端：CLI 输出文件
# ---------------------------------------------------------------------------

def test_cli_writes_benchmark_files(tmp_path: Path):
    it = tmp_path / "iteration-cli"
    _write(it / "eval-a/with_skill/run-1/grading.json", _grading(3, 0))
    _write(it / "eval-a/without_skill/run-1/grading.json", _grading(1, 2))
    assert aggregate.main([str(it)]) == 0
    data = json.loads((it / "benchmark.json").read_text(encoding="utf-8"))
    assert data["summary"]["with_skill"]["micro_passed"] == 3
    md = (it / "benchmark.md").read_text(encoding="utf-8")
    assert "eval-a".removeprefix("eval-") in md
    assert "n/a" in md or "pp" in md
