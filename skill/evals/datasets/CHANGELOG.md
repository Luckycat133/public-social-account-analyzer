# Evaluation Dataset Changelog

All notable changes to the evaluation dataset are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and dataset versions use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-24

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
