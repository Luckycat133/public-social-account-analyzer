# Eval Dataset Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize and harden the existing evaluation dataset structure with documented validation/test boundaries, reproducible splitting, schema and leakage checks, version metadata, path configuration, and local permission guidance.

**Architecture:** Keep `skill/evals/datasets/source/` as the single source of truth and derive `validation_data/` and `test_data/` through the existing deterministic stratified splitter. Extend the splitter with pure validation helpers and manifest metadata, cover behavior with focused pytest tests, then publish directory-level documentation and version history without changing the meaning or IDs of existing samples.

**Tech Stack:** Python 3.9+, Python standard library, JSONL/JSON, pytest, Markdown.

## Global Constraints

- Keep directory names exactly `source`, `validation_data`, and `test_data`.
- Preserve all existing sample IDs, semantics, and the current seed-42, test-ratio-0.30 split.
- JSONL files use UTF-8, one JSON object per line, and a trailing newline.
- Validation data is for development regression; test data is held out for final acceptance.
- Document general model-development guidance separately: validation is 15–20% of training data; independent test data is 20–30%.
- Do not add synthetic business samples without a reviewed data requirement.
- Recommend directory mode `0750` and file mode `0640`; explain that Git does not reliably preserve full Unix modes.
- Do not modify collection, normalization, analysis, or report-generation behavior.

---

### Task 1: Add dataset schema and partition-integrity tests

**Files:**
- Create: `tests/test_split_dataset.py`
- Modify: `skill/scripts/split_dataset.py`

**Interfaces:**
- Consumes: Existing `read_jsonl`, `write_jsonl`, and dataset rows keyed by `id`.
- Produces: `validate_dataset_rows(name, rows, path_label) -> List[str]`, `validate_partition_ids(name, source_rows, validation_rows, test_rows) -> List[str]`, and permission-safe JSONL writes.

- [ ] **Step 1: Write failing tests for schema, duplicate IDs, leakage, coverage, and file permissions**

```python
import stat

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


def test_validate_dataset_rows_rejects_duplicate_id():
    rows = [_behavior("bhv-001"), _behavior("bhv-001")]
    errors = split_dataset.validate_dataset_rows("behavior_cases", rows, "source.jsonl")
    assert any("重复 id" in error and "bhv-001" in error for error in errors)


def test_validate_dataset_rows_rejects_missing_and_wrong_types():
    row = _behavior("bhv-001")
    row["prompt"] = ""
    row["assertions"] = "not-a-list"
    errors = split_dataset.validate_dataset_rows("behavior_cases", [row], "source.jsonl")
    assert any("prompt" in error and "非空字符串" in error for error in errors)
    assert any("assertions" in error and "字符串数组" in error for error in errors)


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
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python3 -m pytest tests/test_split_dataset.py -q`
Expected: FAIL because `validate_dataset_rows` and `validate_partition_ids` do not exist and `write_jsonl` does not enforce mode `0640`.

- [ ] **Step 3: Implement the minimal validation and permission helpers**

Add the following interfaces to `skill/scripts/split_dataset.py` and call `os.chmod(path, FILE_MODE)` after JSONL writes:

```python
FILE_MODE = 0o640
DIRECTORY_MODE = 0o750

DATASET_SCHEMAS = {
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
    "trigger_should": {
        "id": str,
        "label": str,
        "platform": str,
        "query": str,
    },
    "trigger_should_not": {
        "id": str,
        "label": str,
        "reason": str,
        "query": str,
    },
}


def validate_dataset_rows(name, rows, path_label):
    errors = []
    schema = DATASET_SCHEMAS[name]
    seen = set()
    for lineno, row in enumerate(rows, 1):
        row_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(row, dict):
            errors.append(f"{path_label}:{lineno} 顶层必须是 JSON 对象")
            continue
        if isinstance(row_id, str) and row_id in seen:
            errors.append(f"{path_label}:{lineno} 重复 id: {row_id}")
        if isinstance(row_id, str):
            seen.add(row_id)
        for field, expected_type in schema.items():
            value = row.get(field)
            if expected_type is str and (not isinstance(value, str) or not value.strip()):
                errors.append(f"{path_label}:{lineno} 字段 {field} 必须是非空字符串")
            elif expected_type is list and (
                not isinstance(value, list)
                or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                errors.append(f"{path_label}:{lineno} 字段 {field} 必须是非空字符串数组")
    return errors


def validate_partition_ids(name, source_rows, validation_rows, test_rows):
    source_ids = {row["id"] for row in source_rows}
    validation_ids = {row["id"] for row in validation_rows}
    test_ids = {row["id"] for row in test_rows}
    errors = []
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
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m pytest tests/test_split_dataset.py -q`
Expected: PASS with 4 tests.

- [ ] **Step 5: Commit the independently testable validation unit**

```bash
git add tests/test_split_dataset.py skill/scripts/split_dataset.py
git commit -m "test: cover eval dataset integrity"
```

### Task 2: Integrate deep verification and versioned manifest metadata

**Files:**
- Modify: `tests/test_split_dataset.py`
- Modify: `skill/scripts/split_dataset.py`
- Modify: `skill/evals/datasets/manifest.json`

**Interfaces:**
- Consumes: Task 1 validation helpers and the existing manifest checksum entries.
- Produces: `verify(...) -> int` that validates schema, counts, partition integrity, and checksums; manifest schema `public-social-account-analyzer/eval-dataset-manifest@2` with `dataset_version`, `paths`, `split_policy`, and `quality_checks`.

- [ ] **Step 1: Add a failing end-to-end verification test**

```python
import json


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
    split_dataset.write_jsonl(str(validation / "behavior_cases.jsonl"), [rows[0]])
    split_dataset.write_jsonl(str(test / "behavior_cases.jsonl"), [rows[0]])
    manifest = {
        "datasets": [{
            "dataset": "behavior_cases",
            "total": 2,
            "validation_count": 1,
            "test_count": 1,
        }]
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert split_dataset.verify(
        str(source), str(validation), str(test), str(manifest_path)
    ) == 1
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python3 -m pytest tests/test_split_dataset.py::test_verify_rejects_cross_partition_leakage -q`
Expected: FAIL because the current `verify` only checks optional checksums and returns success.

- [ ] **Step 3: Wire schema, count, and partition checks into `verify`**

For each manifest dataset, read all three JSONL files, accumulate errors from `validate_dataset_rows` and `validate_partition_ids`, compare actual counts to `total`, `validation_count`, and `test_count`, then run the existing SHA-256 checks. Emit `[INVALID] <message>` for each integrity error and return `1` when any error exists.

Build manifests with these exact top-level fields:

```python
DATASET_VERSION = "1.0.0"

manifest = {
    "schema": "public-social-account-analyzer/eval-dataset-manifest@2",
    "dataset_version": DATASET_VERSION,
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "generated_by": "skill/scripts/split_dataset.py",
    "paths": {
        "source": "source",
        "validation": "validation_data",
        "test": "test_data",
    },
    "split_policy": {
        "method": "stratified_random_largest_remainder",
        "seed": args.seed,
        "test_ratio": args.test_ratio,
        "validation_ratio": round(1.0 - args.test_ratio, 4),
        "stratify_fields": DATASETS,
    },
    "quality_checks": [
        "jsonl_object",
        "required_fields",
        "unique_id",
        "partition_disjointness",
        "source_coverage",
        "record_counts",
        "sha256",
    ],
    "consistency_tolerance": CONSISTENCY_TOLERANCE,
    "max_distribution_deviation": round(max_dev_all, 4),
    "datasets": results,
}
```

- [ ] **Step 4: Run focused and full tests**

Run: `python3 -m pytest tests/test_split_dataset.py -q`
Expected: PASS.

Run: `python3 -m pytest -q`
Expected: PASS with all project tests; outside the restricted sandbox if loopback-port tests require it.

- [ ] **Step 5: Regenerate and verify the existing split**

Run: `python3 skill/scripts/split_dataset.py --test-ratio 0.30 --seed 42`
Expected: rewrites `validation_data/*.jsonl`, `test_data/*.jsonl`, and `manifest.json`; existing ID assignments remain unchanged.

Run: `python3 skill/scripts/split_dataset.py --verify`
Expected: JSON output contains `"verify": "PASS"` and exit code 0.

- [ ] **Step 6: Commit the verification behavior**

```bash
git add tests/test_split_dataset.py skill/scripts/split_dataset.py skill/evals/datasets/manifest.json
git commit -m "feat: validate eval dataset partitions"
```

### Task 3: Publish the standardized dataset documentation and configuration

**Files:**
- Create: `skill/evals/datasets/README.md`
- Create: `skill/evals/datasets/USAGE.md`
- Create: `skill/evals/datasets/config.example.json`
- Create: `skill/evals/datasets/CHANGELOG.md`
- Create: `skill/evals/datasets/source/README.md`
- Create: `skill/evals/datasets/validation_data/README.md`
- Create: `skill/evals/datasets/test_data/README.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Manifest schema and command behavior from Task 2.
- Produces: Human-readable structure, field semantics, split procedure, path mapping, usage policy, security policy, and update history.

- [ ] **Step 1: Create the root dataset README**

Document the exact tree, single-source-of-truth flow, all required fields, data provenance, JSONL format, 15–20% validation guidance, 20–30% independent test guidance, repository default 70/30 evaluation split, stratification keys, quality gates, permission model, maintainers, and project MIT license reference.

- [ ] **Step 2: Create purpose-specific README files**

`source/README.md` must prohibit direct edits to derived partitions. `validation_data/README.md` must permit development regression and prohibit reporting it as held-out performance. `test_data/README.md` must define held-out access, prohibit tuning against test failures, and require release-level execution records.

- [ ] **Step 3: Create the path configuration example**

```json
{
  "schema": "public-social-account-analyzer/eval-dataset-config@1",
  "datasets_root": "skill/evals/datasets",
  "paths": {
    "source": "skill/evals/datasets/source",
    "validation": "skill/evals/datasets/validation_data",
    "test": "skill/evals/datasets/test_data",
    "manifest": "skill/evals/datasets/manifest.json"
  },
  "split": {
    "method": "stratified_random_largest_remainder",
    "seed": 42,
    "test_ratio": 0.3,
    "stratify_fields": {
      "behavior_cases": "category",
      "trigger_should": "platform",
      "trigger_should_not": "reason"
    }
  },
  "model_development_guidance": {
    "validation_ratio_of_training_data": "0.15-0.20",
    "test_ratio_of_independent_data": "0.20-0.30"
  },
  "permissions": {
    "directories": "0750",
    "files": "0640"
  }
}
```

- [ ] **Step 4: Create usage and version documents**

`USAGE.md` must include commands for dry-run, split, verify, strict distribution checks, permission application, validation-set iteration, held-out test execution, and update/release workflow. `CHANGELOG.md` must follow Keep a Changelog v1.1.0 with `## [1.0.0] - 2026-07-24` and `Added`, `Changed`, and `Security` sections.

- [ ] **Step 5: Update project-level documentation**

Add the dataset tree and links to `README.md`. Add an `## [Unreleased]` section to root `CHANGELOG.md` with `Added`, `Changed`, and `Security` entries describing the documented dataset structure, integrity verification, and permission policy.

- [ ] **Step 6: Check documentation consistency**

Run: `rg -n "test_data|validation_data|15.?20%|20.?30%|0750|0640|split_dataset.py --verify" skill/evals/datasets README.md CHANGELOG.md`
Expected: each required concept appears in the appropriate documentation and paths are consistent.

- [ ] **Step 7: Commit the documentation unit**

```bash
git add README.md CHANGELOG.md skill/evals/datasets/*.md skill/evals/datasets/*/README.md skill/evals/datasets/config.example.json
git commit -m "docs: standardize eval dataset governance"
```

### Task 4: Apply permissions and run final acceptance checks

**Files:**
- Modify metadata only: `skill/evals/datasets/` directory and contained files
- Verify: all files from Tasks 1–3

**Interfaces:**
- Consumes: Completed dataset structure and verification script.
- Produces: Locally secured dataset tree and evidence that all automated checks pass.

- [ ] **Step 1: Apply local permissions**

Run:

```bash
find skill/evals/datasets -type d -exec chmod 750 {} +
find skill/evals/datasets -type f -exec chmod 640 {} +
```

Expected: all directories show `drwxr-x---`; all files show `-rw-r-----`.

- [ ] **Step 2: Verify permissions**

Run: `find skill/evals/datasets -maxdepth 2 -print -exec stat -f '%Sp %N' {} \;`
Expected: no dataset directory is more permissive than `0750` and no dataset file is more permissive than `0640`.

- [ ] **Step 3: Verify manifest and partition integrity**

Run: `python3 skill/scripts/split_dataset.py --verify`
Expected: PASS, no duplicate IDs, no overlap, complete source coverage, matching counts, matching SHA-256.

- [ ] **Step 4: Run focused and complete test suites**

Run: `python3 -m pytest tests/test_split_dataset.py -q`
Expected: PASS.

Run: `python3 -m pytest -q`
Expected: all tests pass; use an environment permitted to bind loopback ports for browser-backend tests.

- [ ] **Step 5: Confirm the existing samples were preserved**

Run: `git diff -- skill/evals/datasets/source/*.jsonl skill/evals/datasets/validation_data/*.jsonl skill/evals/datasets/test_data/*.jsonl`
Expected: no semantic or ID changes beyond deterministic regeneration with seed 42 and test ratio 0.30.

- [ ] **Step 6: Review final status without staging unrelated user changes**

Run: `git status --short`
Expected: only task files are identified for handoff; pre-existing unrelated modifications remain untouched.
