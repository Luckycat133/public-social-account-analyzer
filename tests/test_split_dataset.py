"""评估数据集划分、schema 与分区完整性测试。"""
import json
import stat

import pytest

import split_dataset


def _behavior(case_id: str):
    return {
        "id": case_id,
        "name": "case",
        "platform": "bilibili",
        "category": "happy_path",
        "account_type": "creator",
        "prompt": "分析公开账号",
        "expected_output": "输出分析结果",
        "assertions": ["结果包含来源证据"],
    }


def _p0_case(
    case_id: str,
    primary_p0_id: str,
    *,
    platform: str = "bilibili",
    scenario_type: str = "positive",
    scenario_group=None,
):
    return {
        "id": case_id,
        "name": f"case-{case_id}",
        "primary_p0_id": primary_p0_id,
        "p0_ids": [primary_p0_id],
        "source_ref": "PRD §7/§16",
        "platform": platform,
        "scenario_type": scenario_type,
        "scenario_group": scenario_group or case_id,
        "verification_type": "automated",
        "prompt": "执行可复核的 P0 验收场景",
        "expected_output": "输出满足需求并保留证据",
        "assertions": ["结果可由固定断言复核"],
    }


def _p0_catalog():
    return {
        "requirements": [
            {
                "id": "FR-001",
                "title": "任务创建",
                "kind": "functional",
                "priority": "P0",
                "source_ref": "PRD §7/§16",
                "min_cases": 2,
                "required_platforms": ["bilibili", "douyin"],
                "required_scenario_types": ["positive", "boundary"],
            },
            {
                "id": "AC-01",
                "title": "两平台端到端",
                "kind": "acceptance",
                "priority": "P0",
                "source_ref": "PRD §16 AC-01",
                "min_cases": 1,
                "required_platforms": ["cross_platform"],
                "required_scenario_types": ["external_acceptance"],
            },
        ]
    }


def _complete_manifest_entries():
    return [
        {
            "dataset": name,
            "total": 1,
            "validation_count": 1,
            "test_count": 0,
            "source_sha256": "a" * 64,
            "validation_sha256": "b" * 64,
            "test_sha256": "c" * 64,
        }
        for name in split_dataset.DATASETS
    ]


def test_validate_dataset_rows_rejects_duplicate_id():
    rows = [_behavior("bhv-001"), _behavior("bhv-001")]
    errors = split_dataset.validate_dataset_rows(
        "behavior_cases", rows, "source.jsonl"
    )
    assert any("重复 id" in error and "bhv-001" in error for error in errors)


def test_validate_dataset_rows_rejects_missing_and_wrong_types():
    row = _behavior("bhv-001")
    row["prompt"] = ""
    row["assertions"] = "not-a-list"
    errors = split_dataset.validate_dataset_rows(
        "behavior_cases", [row], "source.jsonl"
    )
    assert any("prompt" in error and "非空字符串" in error for error in errors)
    assert any("assertions" in error and "字符串数组" in error for error in errors)


def test_validate_dataset_rows_rejects_reversed_trigger_label():
    row = {
        "id": "trg-pos-001",
        "label": "should_not_trigger",
        "platform": "bilibili",
        "query": "分析这个公开 B站 账号：https://space.bilibili.com/946974",
    }
    errors = split_dataset.validate_dataset_rows(
        "trigger_should", [row], "source.jsonl"
    )
    assert any("label 必须为 should_trigger" in error for error in errors)


def test_validate_partition_ids_rejects_overlap_and_missing_source_id():
    source = [_behavior("bhv-001"), _behavior("bhv-002")]
    validation = [_behavior("bhv-001")]
    test = [_behavior("bhv-001")]
    errors = split_dataset.validate_partition_ids(
        "behavior_cases", source, validation, test
    )
    assert any("交叉污染" in error and "bhv-001" in error for error in errors)
    assert any("未被划分" in error and "bhv-002" in error for error in errors)


def test_write_jsonl_sets_owner_group_read_mode(tmp_path):
    path = tmp_path / "rows.jsonl"
    split_dataset.write_jsonl(str(path), [_behavior("bhv-001")])
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_verify_rejects_cross_partition_leakage(tmp_path):
    root = tmp_path / "datasets"
    source = root / "source"
    validation = root / "validation_data"
    test = root / "test_data"
    source.mkdir(parents=True)
    validation.mkdir()
    test.mkdir()

    rows = [_behavior("bhv-001"), _behavior("bhv-002")]
    split_dataset.write_jsonl(str(source / "behavior_cases.jsonl"), rows)
    split_dataset.write_jsonl(
        str(validation / "behavior_cases.jsonl"), [rows[0]]
    )
    split_dataset.write_jsonl(str(test / "behavior_cases.jsonl"), [rows[0]])

    manifest = {
        "datasets": [
            {
                "dataset": "behavior_cases",
                "total": 2,
                "validation_count": 1,
                "test_count": 1,
            }
        ]
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert split_dataset.verify(
        str(source), str(validation), str(test), str(manifest_path)
    ) == 1


def test_read_jsonl_rejects_non_object_rows(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('["not", "an", "object"]\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="顶层必须是 JSON 对象"):
        split_dataset.read_jsonl(str(path))


def test_ensure_directory_sets_owner_group_access_mode(tmp_path):
    path = tmp_path / "validation_data"
    split_dataset.ensure_directory(str(path))
    assert stat.S_IMODE(path.stat().st_mode) == 0o750


def test_build_manifest_contains_governance_metadata():
    manifest = split_dataset.build_manifest(
        results=[], seed=42, test_ratio=0.30, max_distribution_deviation=0.0
    )
    assert manifest["schema"].endswith("eval-dataset-manifest@3")
    assert manifest["dataset_version"] == "1.1.0"
    assert manifest["paths"] == {
        "source": "source",
        "validation": "validation_data",
        "test": "test_data",
    }
    assert manifest["split_policy"]["seed"] == 42
    assert manifest["split_policy"]["validation_ratio"] == 0.7
    assert "partition_disjointness" in manifest["quality_checks"]


def test_verify_returns_failure_for_schema_error_without_crashing(tmp_path):
    root = tmp_path / "datasets"
    source = root / "source"
    validation = root / "validation_data"
    test = root / "test_data"
    source.mkdir(parents=True)
    validation.mkdir()
    test.mkdir()

    invalid = _behavior("bhv-001")
    invalid.pop("id")
    split_dataset.write_jsonl(str(source / "behavior_cases.jsonl"), [invalid])
    split_dataset.write_jsonl(
        str(validation / "behavior_cases.jsonl"), [invalid]
    )
    split_dataset.write_jsonl(str(test / "behavior_cases.jsonl"), [])
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "dataset": "behavior_cases",
                        "total": 1,
                        "validation_count": 1,
                        "test_count": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert split_dataset.verify(
        str(source), str(validation), str(test), str(manifest_path)
    ) == 1


def test_process_one_rejects_invalid_source_schema(tmp_path):
    source = tmp_path / "source"
    validation = tmp_path / "validation_data"
    test = tmp_path / "test_data"
    source.mkdir()
    validation.mkdir()
    test.mkdir()
    invalid = _behavior("bhv-001")
    invalid.pop("prompt")
    split_dataset.write_jsonl(str(source / "behavior_cases.jsonl"), [invalid])

    with pytest.raises(SystemExit, match="字段 prompt 必须是非空字符串"):
        split_dataset.process_one(
            "behavior_cases",
            "category",
            str(source),
            str(validation),
            str(test),
            0.30,
            42,
            True,
        )


def test_verify_rejects_manifest_count_mismatch(tmp_path):
    root = tmp_path / "datasets"
    source = root / "source"
    validation = root / "validation_data"
    test = root / "test_data"
    source.mkdir(parents=True)
    validation.mkdir()
    test.mkdir()
    row = _behavior("bhv-001")
    split_dataset.write_jsonl(str(source / "behavior_cases.jsonl"), [row])
    split_dataset.write_jsonl(str(validation / "behavior_cases.jsonl"), [row])
    split_dataset.write_jsonl(str(test / "behavior_cases.jsonl"), [])
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "dataset": "behavior_cases",
                        "total": 99,
                        "validation_count": 1,
                        "test_count": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert split_dataset.verify(
        str(source), str(validation), str(test), str(manifest_path)
    ) == 1


def test_dry_run_does_not_create_or_chmod_dataset_directories(tmp_path, monkeypatch):
    root = tmp_path / "new-datasets"
    monkeypatch.setattr(
        split_dataset,
        "process_one",
        lambda name, field, *args: {
            "dataset": name,
            "max_distribution_deviation": 0.0,
        },
    )
    monkeypatch.setattr(
        "sys.argv", ["split_dataset.py", "--datasets-root", str(root), "--dry-run"]
    )

    assert split_dataset.main() == 0
    assert not root.exists()


def test_verify_rejects_manifest_missing_required_dataset(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"datasets": [{"dataset": "behavior_cases"}]}),
        encoding="utf-8",
    )

    assert split_dataset.verify(
        str(tmp_path / "source"),
        str(tmp_path / "validation_data"),
        str(tmp_path / "test_data"),
        str(manifest_path),
    ) == 1
    assert "datasets 清单" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("mutate", "expected_message"),
    [
        (lambda entries: entries.__setitem__(0, {"dataset": entries[0]["dataset"]}), "字段 total 缺失"),
        (lambda entries: entries[0].pop("validation_count"), "字段 validation_count 缺失"),
        (lambda entries: entries[0].pop("source_sha256"), "字段 source_sha256 缺失"),
        (lambda entries: entries[0].__setitem__("total", True), "字段 total 必须是非负整数"),
        (lambda entries: entries[0].__setitem__("source_sha256", "not-a-checksum"), "字段 source_sha256 必须是 64 位十六进制"),
    ],
)
def test_verify_rejects_incomplete_or_invalid_manifest_entries(
    tmp_path, capsys, mutate, expected_message
):
    entries = _complete_manifest_entries()
    mutate(entries)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"datasets": entries}), encoding="utf-8")

    assert split_dataset.verify(
        str(tmp_path / "source"),
        str(tmp_path / "validation_data"),
        str(tmp_path / "test_data"),
        str(manifest_path),
    ) == 1
    assert expected_message in capsys.readouterr().err


def test_validate_p0_coverage_rejects_missing_requirement_case():
    rows = [
        _p0_case("p0-fr001-positive", "FR-001"),
        _p0_case(
            "p0-fr001-boundary",
            "FR-001",
            platform="douyin",
            scenario_type="boundary",
        ),
    ]

    errors = split_dataset.validate_p0_coverage(_p0_catalog(), rows)

    assert any("AC-01" in error and "缺少" in error for error in errors)


def test_validate_p0_catalog_rejects_omitted_official_requirement():
    catalog = {
        "requirements": [
            {
                "id": requirement_id,
                "title": "requirement",
                "kind": "functional",
                "priority": "P0",
                "min_cases": 1,
                "required_platforms": ["cross_platform"],
                "required_scenario_types": ["positive"],
            }
            for requirement_id in sorted(split_dataset.EXPECTED_P0_IDS - {"FR-015"})
        ]
    }

    errors = split_dataset.validate_p0_catalog(catalog)

    assert any("FR-015" in error and "缺失" in error for error in errors)


def test_validate_p0_coverage_rejects_missing_required_platform_and_scenario():
    rows = [
        _p0_case("p0-fr001-a", "FR-001"),
        _p0_case("p0-fr001-b", "FR-001"),
        _p0_case(
            "p0-ac01",
            "AC-01",
            platform="cross_platform",
            scenario_type="external_acceptance",
        ),
    ]

    errors = split_dataset.validate_p0_coverage(_p0_catalog(), rows)

    assert any("FR-001" in error and "douyin" in error for error in errors)
    assert any("FR-001" in error and "boundary" in error for error in errors)


def test_validate_partition_groups_rejects_semantic_leakage():
    validation = [
        _p0_case(
            "p0-fr001-a", "FR-001", scenario_group="task-creation-defaults"
        )
    ]
    test = [
        _p0_case(
            "p0-fr001-b",
            "FR-001",
            platform="douyin",
            scenario_group="task-creation-defaults",
        )
    ]

    errors = split_dataset.validate_partition_groups(
        "p0_cases", validation, test
    )

    assert any("场景组交叉污染" in error for error in errors)


def test_stratified_split_keeps_both_partitions_for_non_singleton_strata():
    rows = [
        {"id": "a-1", "kind": "a"},
        {"id": "a-2", "kind": "a"},
        {"id": "b-1", "kind": "b"},
        {"id": "b-2", "kind": "b"},
    ]

    validation, test, detail = split_dataset.stratified_split(
        rows, "kind", 0.30, 42
    )

    assert {row["kind"] for row in validation} == {"a", "b"}
    assert {row["kind"] for row in test} == {"a", "b"}
    assert detail == {
        "a": {"total": 2, "test": 1, "validation": 1},
        "b": {"total": 2, "test": 1, "validation": 1},
    }


def test_build_p0_coverage_report_distinguishes_external_acceptance():
    catalog = _p0_catalog()
    rows = [
        _p0_case("p0-fr001-positive", "FR-001"),
        _p0_case(
            "p0-fr001-boundary",
            "FR-001",
            platform="douyin",
            scenario_type="boundary",
        ),
        _p0_case(
            "p0-ac01",
            "AC-01",
            platform="cross_platform",
            scenario_type="external_acceptance",
        ),
    ]
    rows[-1]["verification_type"] = "external_live"

    report = split_dataset.build_p0_coverage_report(catalog, rows)

    assert report["coverage"] == {
        "required": 2,
        "covered_by_cases": 2,
        "dataset_coverage_rate": 1.0,
        "external_acceptance_required": 1,
    }
    ac01 = next(item for item in report["requirements"] if item["id"] == "AC-01")
    assert ac01["execution_gate"] == "external_evidence_required"
