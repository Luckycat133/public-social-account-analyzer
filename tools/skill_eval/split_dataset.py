#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_dataset.py — 评估数据集的分层随机划分工具（validation / test）。

用途
    将 skill/evals/datasets/source/ 下的主数据池（single source of truth）以
    **分层随机** 方式划分为 test_data/（留出验收集）与 validation_data/（开发迭代集），
    生成校验和清单 manifest.json 与分布一致性报告，保证划分可复现、可回归。

设计要点（对应「Agent Skill 评估最佳实践」）
    - test_data 是 **留出集（held-out）**：日常迭代 Skill 时不得查看，仅用于最终验收，
      防止把 Skill 过拟合到自己的评估集上。
    - validation_data 是 **开发迭代集**：改 Skill / 改脚本时用它做快速回归。
    - 分层（stratify）确保两套数据在关键维度（如 platform / category / label）上
      分布一致，避免某一类样本全落到一边。
    - 固定随机种子（--seed，默认 42）→ 同样输入永远得到同样划分（幂等、可复现）。

约定
    - 输入 / 输出均为 JSONL（每行一个 JSON 对象）。
    - 结构化结果写 stdout；诊断信息写 stderr。
    - 不接受交互式输入；所有参数经命令行传入。

示例
    # 预览划分（不写文件）
    python3 tools/skill_eval/split_dataset.py --dry-run

    # 按默认参数执行划分（test 占 30%，种子 42）
    python3 tools/skill_eval/split_dataset.py

    # 自定义留出比例与种子
    python3 tools/skill_eval/split_dataset.py --test-ratio 0.25 --seed 7

    # 只校验现有划分是否与 source 一致（不重新划分）
    python3 tools/skill_eval/split_dataset.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# ---- 数据集文件与其分层键 ----------------------------------------------------
# key = source 文件名（去掉 .jsonl）；value = 用于分层的字段名。
# 分层字段缺失时回退到 "_default" 单一层，脚本不会崩溃。
DATASETS: Dict[str, str] = {
    "behavior_cases": "category",     # 行为用例按场景类别分层
    "p0_cases": "scenario_type",      # PRD P0 用例按验证场景类型分层
    "trigger_should": "platform",     # 应触发按平台分层
    "trigger_should_not": "category", # 不应触发按风险大类分层，避免单例分层
}

DATASET_SCHEMAS: Dict[str, Dict[str, type]] = {
    "behavior_cases": {
        "id": str,
        "name": str,
        "platform": str,
        "category": str,
        "account_type": str,
        "prompt": str,
        "expected_output": str,
        "assertions": list,
    },
    "p0_cases": {
        "id": str,
        "name": str,
        "primary_p0_id": str,
        "p0_ids": list,
        "source_ref": str,
        "platform": str,
        "scenario_type": str,
        "scenario_group": str,
        "verification_type": str,
        "prompt": str,
        "expected_output": str,
        "assertions": list,
    },
    "trigger_should": {
        "id": str,
        "label": str,
        "platform": str,
        "query": str,
    },
    "trigger_should_not": {
        "id": str,
        "label": str,
        "category": str,
        "reason": str,
        "query": str,
    },
}

DATASET_VERSION = "0.3.0"
DEFAULT_TEST_RATIO = 0.30   # 留出（test）比例，对应「独立数据的 20-30%」标准区间
# 分布一致性阈值：各层在 test 中的实际占比与目标 test_ratio 的最大允许偏差。
# 分层样本较小时偏差天然偏大，这里给出提示而非硬失败（见 --strict）。
CONSISTENCY_TOLERANCE = 0.20
FILE_MODE = 0o640
DIRECTORY_MODE = 0o750
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TRIGGER_LABELS = {
    "trigger_should": "should_trigger",
    "trigger_should_not": "should_not_trigger",
}
EXPECTED_P0_IDS = {
    "FR-001", "FR-002", "FR-003", "FR-004", "FR-005", "FR-006",
    "FR-008", "FR-009", "FR-010", "FR-011", "FR-012", "FR-013",
    "FR-015",
    "NFR-001", "NFR-002", "NFR-003", "NFR-004", "NFR-005",
    "NFR-006", "NFR-007",
    "AC-01", "AC-02", "AC-03", "AC-04", "AC-05", "AC-06", "AC-07",
    "AC-08", "AC-09", "AC-10",
}


def eprint(*args: Any) -> None:
    """诊断信息写 stderr，避免污染 stdout 的结构化输出。"""
    print(*args, file=sys.stderr)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"[FATAL] {path}:{lineno} 不是合法 JSON —— {exc}. "
                    f"每行必须是一个完整 JSON 对象。"
                )
            if not isinstance(row, dict):
                raise SystemExit(
                    f"[FATAL] {path}:{lineno} 顶层必须是 JSON 对象。"
                )
            rows.append(row)
    return rows


def read_json_object(path: str) -> Dict[str, Any]:
    """读取一个顶层为对象的 UTF-8 JSON 文件。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[FATAL] 无法读取 {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit(f"[FATAL] {path} 顶层必须是 JSON 对象")
    return value


def write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.chmod(path, FILE_MODE)


def ensure_directory(path: str) -> None:
    """创建数据目录并收紧为 owner rwx、group rx。"""
    os.makedirs(path, exist_ok=True)
    os.chmod(path, DIRECTORY_MODE)


def validate_dataset_rows(
    name: str,
    rows: List[Dict[str, Any]],
    path_label: str,
) -> List[str]:
    """按数据集契约检查必需字段、字段类型与 id 唯一性。"""
    errors: List[str] = []
    schema = DATASET_SCHEMAS[name]
    seen = set()

    for lineno, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append(f"{path_label}:{lineno} 顶层必须是 JSON 对象")
            continue

        row_id = row.get("id")
        if isinstance(row_id, str) and row_id in seen:
            errors.append(f"{path_label}:{lineno} 重复 id: {row_id}")
        if isinstance(row_id, str):
            seen.add(row_id)

        for field, expected_type in schema.items():
            value = row.get(field)
            if expected_type is str:
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"{path_label}:{lineno} 字段 {field} 必须是非空字符串"
                    )
            elif expected_type is list:
                if (
                    not isinstance(value, list)
                    or not value
                    or any(
                        not isinstance(item, str) or not item.strip()
                        for item in value
                    )
                ):
                    errors.append(
                        f"{path_label}:{lineno} 字段 {field} 必须是非空字符串数组"
                    )

        expected_label = TRIGGER_LABELS.get(name)
        if expected_label and row.get("label") != expected_label:
            errors.append(
                f"{path_label}:{lineno} 字段 label 必须为 {expected_label}"
            )
    return errors


def validate_partition_ids(
    name: str,
    source_rows: List[Dict[str, Any]],
    validation_rows: List[Dict[str, Any]],
    test_rows: List[Dict[str, Any]],
) -> List[str]:
    """检查 validation/test 互斥且完整覆盖 source。"""
    source_ids = {row["id"] for row in source_rows}
    validation_ids = {row["id"] for row in validation_rows}
    test_ids = {row["id"] for row in test_rows}
    errors: List[str] = []

    overlap = sorted(validation_ids & test_ids)
    missing = sorted(source_ids - validation_ids - test_ids)
    unknown = sorted((validation_ids | test_ids) - source_ids)
    if overlap:
        errors.append(f"{name} validation/test 交叉污染: {', '.join(overlap)}")
    if missing:
        errors.append(f"{name} source id 未被划分: {', '.join(missing)}")
    if unknown:
        errors.append(f"{name} 划分包含 source 外 id: {', '.join(unknown)}")
    return errors


def validate_partition_groups(
    name: str,
    validation_rows: List[Dict[str, Any]],
    test_rows: List[Dict[str, Any]],
) -> List[str]:
    """阻止同一语义场景组同时出现在开发集和留出集。"""
    if name != "p0_cases":
        return []
    validation_groups = {row["scenario_group"] for row in validation_rows}
    test_groups = {row["scenario_group"] for row in test_rows}
    overlap = sorted(validation_groups & test_groups)
    if not overlap:
        return []
    return [f"{name} validation/test 场景组交叉污染: {', '.join(overlap)}"]


def validate_p0_coverage(
    catalog: Dict[str, Any], rows: List[Dict[str, Any]]
) -> List[str]:
    """按 PRD 目录检查每项 P0 的数量、平台和场景覆盖门槛。"""
    requirements = catalog.get("requirements")
    if not isinstance(requirements, list):
        return ["P0 requirements 清单必须是数组"]

    errors: List[str] = []
    catalog_ids = {
        item.get("id") for item in requirements if isinstance(item, dict)
    }
    for row in rows:
        primary = row.get("primary_p0_id")
        p0_ids = row.get("p0_ids")
        if primary not in catalog_ids:
            errors.append(f"{row.get('id')} primary_p0_id 未在目录中: {primary}")
        if isinstance(p0_ids, list):
            unknown = sorted(set(p0_ids) - catalog_ids)
            if unknown:
                errors.append(
                    f"{row.get('id')} p0_ids 含未知编号: {', '.join(unknown)}"
                )
            if primary not in p0_ids:
                errors.append(
                    f"{row.get('id')} primary_p0_id 必须包含在 p0_ids 中"
                )

    for requirement in requirements:
        if not isinstance(requirement, dict):
            errors.append("P0 requirement 必须是对象")
            continue
        requirement_id = requirement.get("id")
        matched = [
            row for row in rows if requirement_id in row.get("p0_ids", [])
        ]
        min_cases = requirement.get("min_cases", 1)
        if len(matched) < min_cases:
            errors.append(
                f"{requirement_id} 缺少 P0 用例: 需要 {min_cases}，实际 {len(matched)}"
            )
        platforms = {row.get("platform") for row in matched}
        for platform in requirement.get("required_platforms", []):
            if platform not in platforms:
                errors.append(f"{requirement_id} 缺少平台覆盖: {platform}")
        scenario_types = {row.get("scenario_type") for row in matched}
        for scenario_type in requirement.get("required_scenario_types", []):
            if scenario_type not in scenario_types:
                errors.append(f"{requirement_id} 缺少场景覆盖: {scenario_type}")
    return errors


def validate_p0_catalog(catalog: Dict[str, Any]) -> List[str]:
    """校验目录精确覆盖 PRD V1.0 的全部 P0 编号。"""
    requirements = catalog.get("requirements")
    if not isinstance(requirements, list):
        return ["P0 requirements 清单必须是数组"]
    ids = [item.get("id") for item in requirements if isinstance(item, dict)]
    actual = set(ids)
    errors: List[str] = []
    missing = sorted(EXPECTED_P0_IDS - actual)
    extra = sorted(value for value in actual - EXPECTED_P0_IDS if isinstance(value, str))
    if missing:
        errors.append(f"P0 官方需求编号缺失: {', '.join(missing)}")
    if extra:
        errors.append(f"P0 目录包含非官方编号: {', '.join(extra)}")
    if len(ids) != len(actual):
        errors.append("P0 目录包含重复编号")
    for item in requirements:
        if not isinstance(item, dict):
            continue
        if item.get("priority") != "P0":
            errors.append(f"{item.get('id')} priority 必须为 P0")
    return errors


def build_p0_coverage_report(
    catalog: Dict[str, Any], rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """生成需求到用例的机器可读追踪矩阵，不冒充执行通过状态。"""
    requirement_rows: List[Dict[str, Any]] = []
    external_count = 0
    for requirement in catalog["requirements"]:
        requirement_id = requirement["id"]
        cases = [row for row in rows if requirement_id in row["p0_ids"]]
        verification_types = sorted(
            {row["verification_type"] for row in cases}
        )
        external = any(value.startswith("external_") for value in verification_types)
        if external:
            external_count += 1
        requirement_rows.append(
            {
                "id": requirement_id,
                "title": requirement["title"],
                "kind": requirement["kind"],
                "source_ref": requirement["source_ref"],
                "case_ids": [row["id"] for row in cases],
                "platforms": sorted({row["platform"] for row in cases}),
                "scenario_types": sorted(
                    {row["scenario_type"] for row in cases}
                ),
                "verification_types": verification_types,
                "execution_gate": (
                    "external_evidence_required" if external else "runnable_offline"
                ),
            }
        )
    covered = sum(1 for item in requirement_rows if item["case_ids"])
    required = len(requirement_rows)
    return {
        "schema": "public-social-account-analyzer/p0-coverage@1",
        "dataset_version": DATASET_VERSION,
        "coverage": {
            "required": required,
            "covered_by_cases": covered,
            "dataset_coverage_rate": round(covered / required, 4) if required else 0.0,
            "external_acceptance_required": external_count,
        },
        "status_semantics": {
            "dataset_coverage": "存在可执行或可填写的验收用例，不代表运行通过",
            "external_evidence_required": "必须由真实公开页面、人工真值或运营试用记录完成",
        },
        "requirements": requirement_rows,
    }


def build_manifest(
    results: List[Dict[str, Any]],
    seed: int,
    test_ratio: float,
    max_distribution_deviation: float,
) -> Dict[str, Any]:
    """构建带治理元数据的数据集快照清单。"""
    return {
        "schema": "public-social-account-analyzer/eval-dataset-manifest@3",
        "dataset_version": DATASET_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "tools/skill_eval/split_dataset.py",
        "paths": {
            "source": "source",
            "validation": "validation_data",
            "test": "test_data",
        },
        "split_policy": {
            "method": "stratified_random_largest_remainder",
            "seed": seed,
            "test_ratio": test_ratio,
            "validation_ratio": round(1.0 - test_ratio, 4),
            "stratify_fields": DATASETS,
        },
        "quality_checks": [
            "jsonl_object",
            "required_fields",
            "unique_id",
            "partition_disjointness",
            "source_coverage",
            "scenario_group_disjointness",
            "p0_requirement_coverage",
            "record_counts",
            "sha256",
        ],
        "consistency_tolerance": CONSISTENCY_TOLERANCE,
        "max_distribution_deviation": round(max_distribution_deviation, 4),
        "datasets": results,
    }


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def stratified_split(
    rows: List[Dict[str, Any]],
    stratify_field: str,
    test_ratio: float,
    seed: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """按 stratify_field 分层随机划分（最大余数法 / largest remainder）。

    做法：
      1) 全局目标 test 数 = round(test_ratio * 总数)，保证整体比例精确。
      2) 每层配额 = test_ratio * 层样本数；先按 floor 分配，
         剩余名额再按「余数从大到小」逐层 +1。
    这样即使存在大量单样本层（配额<1），也不会把它们全塞进 test，
    而是按比例挑选，整体与各层分布都尽量一致。层内洗牌用
    (seed, 层名) 派生的独立种子 → 跨运行完全可复现。
    返回 (validation_rows, test_rows, 每层计数明细)。
    """
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get(stratify_field, "_default"))
        buckets[key].append(row)

    total = len(rows)
    global_target = round(total * test_ratio)

    # 每层：floor 配额 + 余数
    floors: Dict[str, int] = {}
    remainders: Dict[str, float] = {}
    for key, items in buckets.items():
        quota = len(items) * test_ratio
        floor = int(math.floor(quota))
        if len(items) >= 2:
            floor = max(1, min(floor, len(items) - 1))
        floors[key] = floor
        remainders[key] = quota - floors[key]

    assigned = sum(floors.values())
    global_target = max(global_target, assigned)
    remaining = global_target - assigned
    # 余数从大到小分配剩余名额；同余数按层名排序，确保确定性
    order = sorted(buckets.keys(), key=lambda k: (-remainders[k], k))
    n_test_per: Dict[str, int] = dict(floors)
    for key in order:
        if remaining <= 0:
            break
        if n_test_per[key] < len(buckets[key]):  # 不超过该层样本数
            n_test_per[key] += 1
            remaining -= 1

    validation: List[Dict[str, Any]] = []
    test: List[Dict[str, Any]] = []
    detail: Dict[str, Dict[str, int]] = {}

    for key in sorted(buckets):  # 排序保证跨运行确定性
        items = buckets[key][:]
        random.Random(f"{seed}:{key}").shuffle(items)  # 层内独立可复现洗牌
        n_test = n_test_per[key]
        test_part = items[:n_test]
        val_part = items[n_test:]
        test.extend(test_part)
        validation.extend(val_part)
        detail[key] = {"total": len(items), "test": len(test_part),
                       "validation": len(val_part)}

    # 按 id 排序，让输出文件稳定（便于 diff 与版本控制）
    validation.sort(key=lambda r: str(r.get("id", "")))
    test.sort(key=lambda r: str(r.get("id", "")))
    return validation, test, detail


def consistency_report(
    detail: Dict[str, Dict[str, int]], test_ratio: float
) -> Tuple[List[Dict[str, Any]], float]:
    """计算每层 test 实际占比与目标比例的偏差，返回明细与最大偏差。"""
    rows: List[Dict[str, Any]] = []
    max_dev = 0.0
    for key, c in sorted(detail.items()):
        total = c["total"]
        actual = (c["test"] / total) if total else 0.0
        dev = abs(actual - test_ratio)
        max_dev = max(max_dev, dev)
        rows.append(
            {
                "stratum": key,
                "total": total,
                "test": c["test"],
                "validation": c["validation"],
                "test_ratio_actual": round(actual, 4),
                "deviation": round(dev, 4),
            }
        )
    return rows, max_dev


def process_one(
    name: str,
    stratify_field: str,
    source_dir: str,
    val_dir: str,
    test_dir: str,
    test_ratio: float,
    seed: int,
    dry_run: bool,
) -> Dict[str, Any]:
    src_path = os.path.join(source_dir, f"{name}.jsonl")
    if not os.path.exists(src_path):
        raise SystemExit(f"[FATAL] 缺少主数据池文件：{src_path}")

    rows = read_jsonl(src_path)
    schema_errors = validate_dataset_rows(name, rows, src_path)
    if name == "p0_cases":
        catalog_path = os.path.join(os.path.dirname(source_dir), "p0_requirements.json")
        catalog = read_json_object(catalog_path)
        schema_errors.extend(validate_p0_catalog(catalog))
        schema_errors.extend(validate_p0_coverage(catalog, rows))
    if schema_errors:
        raise SystemExit("[FATAL] " + "\n[FATAL] ".join(schema_errors))
    validation, test, detail = stratified_split(rows, stratify_field, test_ratio, seed)
    group_errors = validate_partition_groups(name, validation, test)
    if group_errors:
        raise SystemExit("[FATAL] " + "\n[FATAL] ".join(group_errors))
    creport, max_dev = consistency_report(detail, test_ratio)

    eprint(f"  · {name}.jsonl  共 {len(rows)} 条 → "
           f"validation {len(validation)} / test {len(test)}  "
           f"(分层字段={stratify_field}, 最大分布偏差={max_dev:.3f})")

    result: Dict[str, Any] = {
        "dataset": name,
        "stratify_field": stratify_field,
        "total": len(rows),
        "validation_count": len(validation),
        "test_count": len(test),
        "max_distribution_deviation": round(max_dev, 4),
        "strata": creport,
    }

    if not dry_run:
        val_path = os.path.join(val_dir, f"{name}.jsonl")
        test_path = os.path.join(test_dir, f"{name}.jsonl")
        write_jsonl(val_path, validation)
        write_jsonl(test_path, test)
        result["validation_sha256"] = sha256_of_file(val_path)
        result["test_sha256"] = sha256_of_file(test_path)
        result["source_sha256"] = sha256_of_file(src_path)

    return result


def verify(source_dir: str, val_dir: str, test_dir: str, manifest_path: str) -> int:
    """校验现有划分的 schema、ID 完整性、数量与文件校验和。"""
    if not os.path.exists(manifest_path):
        eprint(f"[ERROR] 未找到 manifest：{manifest_path}，请先执行一次划分。")
        return 2
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        eprint("[INVALID] manifest datasets 清单必须是数组")
        print(json.dumps({"verify": "FAIL"}, ensure_ascii=False, indent=2))
        return 1
    names = [ds.get("dataset") for ds in datasets if isinstance(ds, dict)]
    expected_names = set(DATASETS)
    actual_names = set(names)
    if (
        len(names) != len(datasets)
        or len(names) != len(expected_names)
        or actual_names != expected_names
    ):
        missing = sorted(expected_names - actual_names)
        extra = sorted(name for name in actual_names - expected_names if isinstance(name, str))
        eprint(
            "[INVALID] manifest datasets 清单必须且只能覆盖 "
            f"{sorted(expected_names)}；缺失={missing}，额外={extra}"
        )
        print(json.dumps({"verify": "FAIL"}, ensure_ascii=False, indent=2))
        return 1

    entry_errors: List[str] = []
    for ds in datasets:
        name = ds["dataset"]
        for field in ("total", "validation_count", "test_count"):
            if field not in ds:
                entry_errors.append(f"{name} 字段 {field} 缺失")
                continue
            value = ds[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                entry_errors.append(f"{name} 字段 {field} 必须是非负整数")
        for field in ("source_sha256", "validation_sha256", "test_sha256"):
            if field not in ds:
                entry_errors.append(f"{name} 字段 {field} 缺失")
                continue
            value = ds[field]
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                entry_errors.append(f"{name} 字段 {field} 必须是 64 位十六进制")
    if entry_errors:
        for error in entry_errors:
            eprint(f"[INVALID] {error}")
        print(json.dumps({"verify": "FAIL"}, ensure_ascii=False, indent=2))
        return 1

    governance = manifest.get("p0_governance")
    governance_errors: List[str] = []
    if not isinstance(governance, dict):
        governance_errors.append("manifest 缺少 p0_governance")
    else:
        root = os.path.dirname(source_dir)
        for path_field, hash_field in (
            ("requirements_path", "requirements_sha256"),
            ("coverage_path", "coverage_sha256"),
        ):
            relative_path = governance.get(path_field)
            expected_hash = governance.get(hash_field)
            if not isinstance(relative_path, str) or not relative_path:
                governance_errors.append(f"p0_governance {path_field} 无效")
                continue
            if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
                governance_errors.append(f"p0_governance {hash_field} 无效")
                continue
            full_path = os.path.join(root, relative_path)
            if not os.path.exists(full_path):
                governance_errors.append(f"P0 治理文件缺失: {full_path}")
            elif sha256_of_file(full_path) != expected_hash.lower():
                governance_errors.append(f"P0 治理文件校验和不匹配: {full_path}")
    if governance_errors:
        for error in governance_errors:
            eprint(f"[INVALID] {error}")
        print(json.dumps({"verify": "FAIL"}, ensure_ascii=False, indent=2))
        return 1

    ok = True
    for ds in datasets:
        name = ds["dataset"]
        source_path = os.path.join(source_dir, f"{name}.jsonl")
        validation_path = os.path.join(val_dir, f"{name}.jsonl")
        test_path = os.path.join(test_dir, f"{name}.jsonl")
        paths = [source_path, validation_path, test_path]

        if any(not os.path.exists(path) for path in paths):
            for path in paths:
                if not os.path.exists(path):
                    eprint(f"[MISMATCH] 文件缺失：{path}")
            ok = False
            continue

        source_rows = read_jsonl(source_path)
        validation_rows = read_jsonl(validation_path)
        test_rows = read_jsonl(test_path)
        schema_errors: List[str] = []
        schema_errors.extend(validate_dataset_rows(name, source_rows, source_path))
        schema_errors.extend(
            validate_dataset_rows(name, validation_rows, validation_path)
        )
        schema_errors.extend(validate_dataset_rows(name, test_rows, test_path))
        integrity_errors = list(schema_errors)
        if not schema_errors:
            integrity_errors.extend(
                validate_partition_ids(name, source_rows, validation_rows, test_rows)
            )
            integrity_errors.extend(
                validate_partition_groups(name, validation_rows, test_rows)
            )
            if name == "p0_cases":
                catalog_path = os.path.join(
                    os.path.dirname(source_dir), "p0_requirements.json"
                )
                if not os.path.exists(catalog_path):
                    integrity_errors.append(
                        f"{name} 缺少 P0 目录: {catalog_path}"
                    )
                else:
                    integrity_errors.extend(
                        validate_p0_catalog(read_json_object(catalog_path))
                    )
                    integrity_errors.extend(
                        validate_p0_coverage(read_json_object(catalog_path), source_rows)
                    )

        expected_counts = {
            "total": len(source_rows),
            "validation_count": len(validation_rows),
            "test_count": len(test_rows),
        }
        for field, actual in expected_counts.items():
            expected = ds[field]
            if expected != actual:
                integrity_errors.append(
                    f"{name} {field} 记录为 {expected}，实际为 {actual}"
                )

        for error in integrity_errors:
            eprint(f"[INVALID] {error}")
        if integrity_errors:
            ok = False

        checks = [
            (validation_path, ds["validation_sha256"].lower()),
            (test_path, ds["test_sha256"].lower()),
            (source_path, ds["source_sha256"].lower()),
        ]
        for path, expected in checks:
            if not os.path.exists(path):
                eprint(f"[MISMATCH] 文件缺失：{path}")
                ok = False
                continue
            actual = sha256_of_file(path)
            status = "OK" if actual == expected else "MISMATCH"
            if actual != expected:
                ok = False
                eprint(f"[{status}] {path}\n           期望 {expected}\n           实际 {actual}")
            else:
                eprint(f"[OK] {os.path.relpath(path)}")
    if ok:
        print(json.dumps({"verify": "PASS", "manifest": os.path.relpath(manifest_path)},
                         ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"verify": "FAIL"}, ensure_ascii=False, indent=2))
    return 1


def build_arg_parser() -> argparse.ArgumentParser:
    here = os.path.dirname(os.path.abspath(__file__))
    datasets_root = os.path.normpath(
        os.path.join(here, "..", "..", "skill", "evals", "datasets")
    )
    p = argparse.ArgumentParser(
        description="评估数据集的分层随机划分工具（validation / test）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--datasets-root", default=datasets_root,
                   help="datasets 根目录（含 source/ validation_data/ test_data/）。默认自动定位。")
    p.add_argument("--test-ratio", type=float, default=DEFAULT_TEST_RATIO,
                   help=f"留出（test）比例，取值 0-1。默认 {DEFAULT_TEST_RATIO}（对应独立数据 20-30%%）。")
    p.add_argument("--seed", type=int, default=42,
                   help="随机种子，保证可复现。默认 42。")
    p.add_argument("--dry-run", action="store_true",
                   help="只计算并打印划分结果，不写任何文件。")
    p.add_argument("--verify", action="store_true",
                   help="不重新划分，校验 schema、分区完整性、数量与 sha256。")
    p.add_argument("--strict", action="store_true",
                   help=f"分布最大偏差超过 {CONSISTENCY_TOLERANCE} 时以非零码退出。")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    if not 0.0 < args.test_ratio < 1.0:
        eprint(f"[FATAL] --test-ratio 必须在 (0,1) 之间，收到 {args.test_ratio}")
        return 2

    root = args.datasets_root
    source_dir = os.path.join(root, "source")
    val_dir = os.path.join(root, "validation_data")
    test_dir = os.path.join(root, "test_data")
    manifest_path = os.path.join(root, "manifest.json")

    if args.verify:
        return verify(source_dir, val_dir, test_dir, manifest_path)

    if not args.dry_run:
        for d in (root, source_dir, val_dir, test_dir):
            ensure_directory(d)

    eprint(f"[split] datasets_root={root}")
    eprint(f"[split] test_ratio={args.test_ratio}  seed={args.seed}  "
           f"dry_run={args.dry_run}")

    results: List[Dict[str, Any]] = []
    max_dev_all = 0.0
    for name, field in DATASETS.items():
        res = process_one(name, field, source_dir, val_dir, test_dir,
                           args.test_ratio, args.seed, args.dry_run)
        results.append(res)
        max_dev_all = max(max_dev_all, res["max_distribution_deviation"])

    manifest = build_manifest(results, args.seed, args.test_ratio, max_dev_all)

    if not args.dry_run:
        catalog_path = os.path.join(root, "p0_requirements.json")
        coverage_path = os.path.join(root, "p0_coverage.json")
        catalog = read_json_object(catalog_path)
        p0_rows = read_jsonl(os.path.join(source_dir, "p0_cases.jsonl"))
        with open(coverage_path, "w", encoding="utf-8") as f:
            json.dump(
                build_p0_coverage_report(catalog, p0_rows),
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
        os.chmod(coverage_path, FILE_MODE)
        manifest["p0_governance"] = {
            "requirements_path": "p0_requirements.json",
            "requirements_sha256": sha256_of_file(catalog_path),
            "coverage_path": "p0_coverage.json",
            "coverage_sha256": sha256_of_file(coverage_path),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.chmod(manifest_path, FILE_MODE)
        eprint(f"[split] 已写 manifest：{manifest_path}")

    # 结构化摘要写 stdout
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if args.strict and max_dev_all > CONSISTENCY_TOLERANCE:
        eprint(f"[STRICT] 最大分布偏差 {max_dev_all:.3f} 超过阈值 "
               f"{CONSISTENCY_TOLERANCE}，以错误码退出。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
