# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Added deterministic high/low evidence coverage and structured core insights whose evidence rows map exactly to selected records.
- Added `run_pipeline.py`, which verifies a committed collection through one identity-bound reader and publishes normalization, analysis, provenance, Markdown, and HTML as a separate create-only immutable workspace.
- Added explicit required/optional analysis artifact inventories, create-only binary writes, call-local renderer diagnostics, and pure in-memory normalize/analyze/render interfaces.
- Added strict, complete semantic-classification input via `--classification-results`; validated source bytes are preserved in the immutable analysis workspace and can advance analysis status to `COMPLETED`.
- Added an experimental Douyin browser fallback when SSR is absent or its post-list structure is unrecognized. It observes eligible public CDP network responses and falls back to visible post cards when needed; a recognized empty list remains `NO_PUBLIC_CONTENT`, and no Python runtime package is added.
- Added offline Douyin tests for browser-response parsing, bounded collection, CLI policy, retained partial posts, and documentation coverage.
- Added a zero-runtime-dependency `import_index_snapshot.py` path for public Douyin Web-index evidence after direct collection is blocked. The Agent verifies source/item ownership, while the importer validates official URLs and field consistency; it supports official Jingxuan item URLs and explicitly disclosed profile-index records.

### Changed
- High/low item evidence now requires a canonical, post-ID-bound platform item URL, collection timestamp, and metrics. Ordinary profile/off-platform/source-only links are rejected; the strict Douyin search-index profile exception remains disclosed but incomplete, while exact official Jingxuan item URLs are supported.
- Derived analysis now remains `PARTIAL` with `EVIDENCE_INCOMPLETE` when any selected high/low record lacks complete item evidence, even after semantic classification is complete.
- High/low analysis now thresholds and sizes groups from non-null measured values (including zero), reports measured count and median, resolves ties deterministically, and preserves the exact selected-item provenance contract with median-relative performance.
- Normalized posts now preserve `hashtags`, `platform_metrics`, `field_visibility`, provenance, collection timestamps, source URLs, and nullable public flags across memory, canonical JSON CSV, and analysis outputs; bounded, type-checked readers retain compatibility with legacy delimited hashtags and historical Python-repr structured cells.
- Missing or invalid per-post collection status now becomes auditable `PARTIAL` data with source provenance and a normalization warning. Analysis exposes fixed zero-filled `status_counts`, and warnings downgrade the normalization phase instead of inventing success.
- Bilibili pin status now distinguishes a successful no-pin response from an unobserved endpoint, while Bilibili, Douyin index evidence, and Weibo keep unsupported public flags as `null`.
- Deep-approval and community-discussion rates now remain `null` when every numerator component is unknown; when at least one component is known, remaining unknown components count as zero and the output note discloses this policy.
- Committed collection workspaces are now read-only inputs. Legacy `normalize.py`, `analyze.py`, and `render_report.py` refuse immutable workspaces instead of adding or replacing files in place.
- Analysis lifecycle now distinguishes durable publication (`.complete`) from business completeness (`task_status` and `phase_results`); limited collection input or pending semantic classification produces a committed `PARTIAL` analysis.
- Douyin collection now defaults to the experimental fallback. `SOCIAL_BROWSER_FALLBACK=0` disables its default, while explicit `--no-browser-fallback` globally overrides both Douyin and Bilibili browser paths. Each browser run uses a temporary profile and does not reuse login state.
- When browser collection is stopped by a public access restriction, normalized posts already collected are preserved as partial results. Diagnostics are limited to safe codes and sanitized response paths.
- Index provenance, platform-ID/link availability, source rank, and timestamp precision now survive normalization and analysis. Reports disclose partial/stale/non-exhaustive index data, suppress profile anchors as item links, and do not infer total engagement from index-visible likes.
- Cadence analysis no longer fabricates a weekly average when all publication dates are unknown, and date-only evidence is excluded from hour-of-day and exact-hour interval claims.

### Security
- Analysis input reads retain directory and artifact identities, recheck the source commit digest, and never reopen collection artifacts by pathname after validation. Existing or symlink output targets fail before processing, and post-reservation failures never overwrite or delete nodes.
- Windows readers re-enumerate exact inventories through held directory handles, and HTML template replacement is single-pass so public text cannot be reinterpreted as template syntax.
- The fallback does not reproduce signatures or bypass login, CAPTCHA, slider, rate-limit, or other access protections. It does not persist cookies, request headers, signed URLs, response bodies, or media.
- The Web-index importer rejects non-Douyin/lookalike hosts, credentials, ports, query strings, author mismatches, ID/URL mismatches, and non-integer metrics; persisted evidence is field-whitelisted.

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
- Enforced strict compliance boundaries prohibiting login credential storage, WAF bypass, private backend metrics scraping, and automated account management. Douyin JS-VM / dynamic-render pages without parseable SSR data may use the experimental browser transport, which observes public network responses then visible cards; it never forges signatures or bypasses WAF protections.
