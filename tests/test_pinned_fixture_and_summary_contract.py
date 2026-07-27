"""置顶隔离离线 fixture + 数据质量摘要顺序契约的回归测试。

对应 iteration-1 基准暴露的两个缺口：
1. 真实采集样本中无置顶内容 → 置顶排除断言无可验证对象。
   现在用确定性离线 fixture 端到端证明：置顶被单独标记、
   未混入发布节奏统计、未拉偏表现指标。
2. 最终答复未在分析结论前展示数据质量摘要 → SKILL.md 与
   evals.json 的契约文本回归锁定（防止再次被削弱/删除）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_BUILDER = (
    REPO_ROOT / "skill/evals/datasets/fixtures/build_pinned_fixture.py"
)
SKILL_MD = REPO_ROOT / "skill/SKILL.md"
EVALS_JSON = REPO_ROOT / "skill/evals/evals.json"


# ---------------------------------------------------------------------------
# fixture 构建 + 流水线端到端
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pipeline_analysis(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("pinned-fixture")
    collection = tmp / "collection"
    analysis_dir = tmp / "analysis"
    build = subprocess.run(
        [sys.executable, str(FIXTURE_BUILDER), "--out", str(collection)],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    pipeline = subprocess.run(
        [sys.executable, str(REPO_ROOT / "skill/scripts/run_pipeline.py"),
         "--input", str(collection), "--output", str(analysis_dir)],
        capture_output=True, text=True, timeout=300,
    )
    assert pipeline.returncode == 0, pipeline.stderr
    return json.loads(
        (analysis_dir / "analysis.json").read_text(encoding="utf-8")
    )


def test_fixture_is_deterministic(tmp_path):
    """两次构建的 source 内容字节一致。"""
    outs = []
    for name in ("a", "b"):
        out = tmp_path / name
        proc = subprocess.run(
            [sys.executable, str(FIXTURE_BUILDER), "--out", str(out)],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        outs.append(out)
    for rel in ("source/posts.jsonl", "source/profile.json", "task.json"):
        assert (outs[0] / rel).read_bytes() == (outs[1] / rel).read_bytes(), rel


def test_pinned_posts_are_flagged_and_excluded(pipeline_analysis):
    boundary = pipeline_analysis["sample_boundary"]
    assert boundary["excluded_flagged"] == 3  # 2 置顶 + 1 转载
    flagged_ids = set(boundary["excluded_flagged_post_ids"])
    assert {"BVpin0000001", "BVpin0000002", "BVrep0000001"} <= flagged_ids


def test_pinned_not_mixed_into_cadence(pipeline_analysis):
    """置顶(周日23:00)未混入节奏统计：23点桶为0、周日桶为0、总数=17。"""
    cadence = pipeline_analysis["publish_cadence"]
    assert cadence["total_posts"] == 17
    assert cadence["hour_distribution"]["23"] == 0
    assert cadence["weekday_distribution"]["6"] == 0  # 周日
    assert cadence["weekday_weekend"]["weekend_count"] == 0


def test_pinned_metrics_do_not_skew_valid_medians(pipeline_analysis):
    """置顶 1000 万播放未拉偏有效样本中位数（有效播放 ≤ 18500）。"""
    views_median = (
        pipeline_analysis["metric_summary"]["views"]["median"]
    )
    assert views_median is not None
    assert views_median <= 20_000


# ---------------------------------------------------------------------------
# 数据质量摘要「先摘要后结论」契约回归
# ---------------------------------------------------------------------------

def test_skill_md_requires_summary_before_conclusions():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "最终答复先摘要后结论" in text, (
        "SKILL.md 必须保留『最终答复先摘要后结论』契约条款"
    )
    assert "成功/失败/受限数量与关键字段覆盖率" in text
    assert "最终答复在分析结论前先展示数据质量摘要" in text, (
        "输出验证清单必须保留摘要顺序检查项"
    )


def test_eval_assertion_requires_summary_in_final_reply():
    data = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    eval1 = next(e for e in data["evals"] if e["id"] == 1)
    matched = [a for a in eval1["assertions"] if "最终用户答复" in a]
    assert matched, "eval1 必须有约束最终答复摘要顺序的断言"
    assert "不算通过" in matched[0]


def test_eval_pinned_assertion_is_conditional_with_fixture():
    data = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    eval1 = next(e for e in data["evals"] if e["id"] == 1)
    matched = [a for a in eval1["assertions"] if "置顶" in a]
    assert matched
    assert "N/A" in matched[0], "无置顶样本时断言必须按 N/A 计"
    assert "fixture" in matched[0], "断言必须指向确定性离线 fixture"


def test_eval10_forbids_hypothetical_reports():
    data = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    eval10 = next(e for e in data["evals"] if e["id"] == 10)
    first = eval10["assertions"][0]
    assert "假设稿" in first and "草稿" in first, (
        "eval10 断言必须明确禁止无采集的假设型报告"
    )
