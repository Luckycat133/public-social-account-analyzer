# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-24

### Added
- **Tiered Architecture Pattern**: Separated the codebase into a human-oriented root repository and a clean AI Agent skill package located in `skill/`.
- **Bilibili Public Collector**: Implemented 3-tier endpoint fallback strategy (`medialist` -> `arc/wbi` -> `search/type`) with optional browser fallback for IP restriction recovery.
- **Douyin Public Collector**: Added SSR `RENDER_DATA` extractor for public video items and profile metadata.
- **Deterministic Analytics Engine**: Added median and quartile-based metrics calculation for engagement rates and publication cadence.
- **Multi-Format Report Generator**: Implemented rendering pipelines for Markdown reports, HTML dynamic dashboards, normalized CSV, and analysis JSON.
- **Automated Test Suite**: Added 73 unit tests covering collectors, normalization, metrics, and datetime handlers.

### Changed
- Refactored `SKILL.md` to comply with the Agent Skills specification by streamlining YAML frontmatter metadata and eliminating redundant sections.
- Updated `pyproject.toml` with pytest `pythonpath` configuration targeting `skill/scripts`.

### Security
- Enforced strict compliance boundaries prohibiting login credential storage, WAF bypass, private backend metrics scraping, and automated account management.
