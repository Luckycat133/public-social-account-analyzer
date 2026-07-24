# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-24

### Added
- **Tiered Architecture Pattern**: Separated the codebase into a human-oriented root repository and a clean AI Agent skill package located in `skill/`.
- **Bilibili Public Collector**: Implemented 3-tier endpoint fallback strategy (`medialist` -> `arc/wbi` -> `search/type`) with optional browser fallback for IP restriction recovery; wired `collect_tags` into the full `collect_post_list` flow.
- **Douyin Public Collector**: Added a multi-variant SSR extractor (`RENDER_DATA` / `_SSR_DATA` / `__INIT_DATA` / `_ROUTER_DATA` / `__INITIAL_STATE__`) for public video items and profile metadata, with an `iesdouyin` public API fallback when the page ships only a JS-VM (`_$jsvmprt`) shell.
- **Weibo Public Collector**: Implemented the public profile/post collector (env-gated via `WEIBO_COLLECTOR_ENABLED`, off by default; raises `ADAPTER_UNAVAILABLE` when disabled so the MVP is never blocked).
- **Deterministic Analytics Engine**: Added median/quartile metrics with a four-way engagement model (`view_based_engagement_rate`, `follower_based_engagement_ratio`, `deep_approval_rate = (coins+favorites)/views`, `community_discussion_rate = (comments+danmaku)/views` — hybrid denominators, transparent and independently named), IQR dispersion ratio, seasonal/semester cadence detection, and high/low performer comparison.
- **Incremental Collection**: Added `--resume --out <dir>` / `--since` with idempotent post-id/bvid dedup merge and `task.json` incremental bookkeeping.
- **Multi-Format Report Generator**: Implemented rendering pipelines for Markdown reports, HTML dynamic dashboards, normalized CSV, and analysis JSON, with zero-dependency inline SVG visualizations (24-hour publish-time distribution, timeline scatter, high/low radar, field-coverage badges).
- **LLM Taxonomy Assist**: Optional `--with-llm-tax` prompt generation and `--llm-tax-results` backfill.
- **Automated Test Suite**: 100 unit tests covering collectors, normalization, metrics, rendering, incremental collection, and datetime handlers.

### Changed
- Refactored `SKILL.md` to comply with the Agent Skills specification by streamlining YAML frontmatter metadata and eliminating redundant sections.
- Updated `pyproject.toml` with pytest `pythonpath` configuration targeting `skill/scripts`.
- Unified all collector imports to package-relative form (`from .base import BaseCollector`).
- `analyze.py`: `split_samples` now excludes `FAILED`/`DELETED`/`RESTRICTED` posts from the flagged bucket; `compute_cadence` back-fills a continuous monthly timeline and uses the valid-date count as the seasonal denominator; `compute_high_low` bases the top/bottom 20% split on measured (non-null) samples only; `classification_status` is sourced from `meta` instead of a hard-coded literal.

### Fixed
- **NaN / Inf robustness**: `normalize.py`, `render_report.py`, and CSV export guard against `NaN`/`Inf`/`OverflowError` and preserve negative signs when parsing metrics.
- **Millisecond timestamps**: Bilibili `_to_iso` and Douyin `duration` normalize millisecond values to seconds.
- **Empty-response guards**: Bilibili `search/type` and `view` responses are null-safe (`.get("data")`) instead of raising `KeyError`.
- **ISO parsing**: timeline scatter tolerates trailing-`Z` UTC timestamps.
- **Graceful degradation**: the report pipeline emits complete null-valued standard artifacts even at 0 collected posts (no crash).

### Security
- Enforced strict compliance boundaries prohibiting login credential storage, WAF bypass, private backend metrics scraping, and automated account management. Douyin JS-VM / dynamic-render pages are reported honestly as `PARSER_FAILED`; only a transport-layer `--browser-fallback` (Headless Chrome) is offered, never signature forging or WAF bypass.
