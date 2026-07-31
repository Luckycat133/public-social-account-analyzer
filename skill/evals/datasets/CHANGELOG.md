# Evaluation Dataset Changelog

All notable changes to the evaluation dataset are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and dataset versions use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-07-29

### Changed

- 模糊的 B站/抖音账号分析请求现在评测按用户目标与证据充分性自适应路由，不再断言固定最近 30 条或固定完整采集。
- 明确日期窗口使用完整采集编排证明覆盖，取消抖音日期任务的隐含 100 条上限。
- B站完整覆盖用例保留默认 10,000 条、硬上限 50,000 条预算；快速模糊请求不机械触发该预算。

### Added

- 新增抖音模糊请求、无签名同源页内分页、瞬态限制有界重试、最佳部分证据选择与样本节奏标签用例。
- 新增用例后按固定 seed 42、test ratio 0.30 重新生成 validation/test 分区与 manifest。

## [0.2.0] - 2026-07-27

### Added

- Added a machine-readable catalog for all 30 PRD V1.0 P0 requirements: 13 functional requirements, 7 non-functional requirements, and 10 acceptance criteria.
- Added 30 traceable P0 cases with source references, platform scope, scenario type, verification mode, objective assertions, and semantic leakage groups.
- Added a generated P0 coverage report that separates dataset coverage from external evidence gates.
- Added checksum governance for the P0 catalog and coverage report.

### Changed

- Added scenario-group leakage and strict P0 coverage validation.
- Stratified P0 cases by scenario type and negative triggers by coarse risk category.
- Preserved validation and test examples for every non-singleton stratum where mathematically possible.
- Expanded output-contract and conditional Weibo trigger samples so strict distribution validation passes.

### Security

- Added explicit P0 cases for credential rejection, private-data exclusion, no-login behavior, and anti-bypass compliance.

## [0.1.0] - 2026-07-24

### Added

- Added separate `validation_data` and held-out `test_data` directories derived from a single `source` pool.
- Added dataset-level, source, validation, and test documentation covering provenance, JSONL schemas, field meanings, split policy, and usage boundaries.
- Added a path configuration example and an operational guide for reproducible splitting and verification.
- Added manifest metadata for dataset version, paths, stratification policy, quality checks, counts, distributions, and SHA-256 checksums.

### Changed

- Standardized the default evaluation split at 70% validation and 30% test with seed 42 and dataset-specific stratification fields.
- Extended verification to detect schema violations, duplicate IDs, cross-partition leakage, incomplete source coverage, count mismatches, and checksum drift.

### Security

- Documented a local permission baseline of `0750` for directories and `0640` for files.
- Prohibited credentials, cookies, access tokens, private platform exports, and personal sensitive data in evaluation files.
