# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Added standardized `source`, `validation_data`, and held-out `test_data` documentation, a path configuration example, and an operational data usage guide.
- Added evaluation dataset tests covering schema contracts, duplicate IDs, partition leakage, source coverage, manifest counts, and local file modes.
- Added script-layer and historical-observation indexes that document entry-point contracts, module boundaries, and evidence freshness.

### Changed
- Strategy/commonality requests in the Agent Skill now use a two-stage taxonomy workflow and only treat the classified, manifest-sealed analysis as final.
- Collection CLI output now separates immutable commit success from business status; quality reports include explicit collected/error counts and the sanitized stop stage.
- Douyin browser coverage now records safe requested/launched, evidence-source, scroll, and budget fields across collection and analysis, while temporary profiles are allocated lazily at browser start.
- Extended `split_dataset.py --verify` to validate JSONL structure, required fields, partition integrity, record counts, and SHA-256 checksums.
- Upgraded the evaluation dataset manifest to schema version 2 with dataset version, path, split-policy, and quality-check metadata.
- Consolidated the repository structure documentation with the current 128-test suite, collector dependency direction, networking boundaries, and relocated historical records.
- Kept comment sampling explicitly best-effort only; comment persistence and comment-insight conclusions remain unimplemented rather than being claimed by evaluation data.
- Clarified LLM taxonomy behavior: the Agent Skill flow assigns classification to the executing agent when valid samples exist, while `analyze.py` only exposes optional prompt-generation and result-backfill interfaces and never calls an LLM itself.

### Security
- Established a local permission baseline of `0750` for dataset directories and `0640` for dataset files, with deployment guidance because Git does not preserve full Unix modes.
- Added deterministic high/low evidence coverage and structured core insights whose evidence rows map exactly to selected records.
- Added `run_pipeline.py`, which verifies a committed collection through one identity-bound reader and publishes normalization, analysis, provenance, Markdown, and HTML as a separate create-only immutable workspace.
- Added explicit required/optional analysis artifact inventories, create-only binary writes, call-local renderer diagnostics, and pure in-memory normalize/analyze/render interfaces.
- Added strict, complete semantic-classification input via `--classification-results`; validated source bytes are preserved in the immutable analysis workspace and can advance analysis status to `COMPLETED`.
- Added an experimental Douyin browser fallback when SSR is absent or its post-list structure is unrecognized. It observes eligible public CDP network responses and falls back to visible post cards when needed; a recognized empty list remains `NO_PUBLIC_CONTENT`, and no Python runtime package is added.
- Added offline Douyin tests for browser-response parsing, bounded collection, CLI policy, retained partial posts, and documentation coverage.
- Added a zero-runtime-dependency `import_index_snapshot.py` path for public Douyin Web-index evidence after direct collection is blocked. The Agent verifies source/item ownership, while the importer validates official URLs and field consistency; it supports official Jingxuan item URLs and explicitly disclosed profile-index records.
- Added bounded public Douyin `--all` collection with explicit item/time/scroll budgets and an auditable completeness ledger. Only a validated terminal list page may set `is_exhaustive=true`; every safety or platform stop remains non-exhaustive, retaining `PARTIAL` data when posts were already collected and `FAILED` when none were available.
- Added `collect_douyin_authorized.py` for the OpenAPI credential owner. It requires the access token and `open_id` returned by the same OAuth authorization, verifies that exact identity through official userinfo, paginates `video.list`, keeps the access token out of URLs/logs/artifacts, and declares exhaustive coverage only after the official terminal page.
- Added deterministic comment-evidence analysis with strict JSONL/parent/ledger validation, four collection states, field and parent coverage, stable representative samples, immutable byte-for-byte evidence copying, and matching Markdown/HTML presentation. Semantic comment insights remain explicitly pending model input.
- Added deterministic classification breakdowns after complete taxonomy input: a full topic-by-format count matrix, topic/format main-metric coverage and medians, plus high/low-group structured feature comparisons for taxonomy fields, series, public flags, hashtags, and fixed duration buckets. The output remains descriptive and never invents title/opening semantics, causality, or significance.
- Added a PRD implementation and acceptance matrix that separates implemented contracts, conditional online capabilities, outstanding human acceptance, and the limits of anonymous third-party Douyin history collection.

### Changed
- Public Douyin exhaustive coverage now accepts account-list candidates only on exact HTTP 200 and rejects any supplied top-level API status other than integer zero. It atomically audits each candidate's frozen owners, every raw item, post-ID aliases, parseable official direct-post URL (including its optional trailing slash), cursor aliases, and pagination facts before committing one logical page. Empty, whitespace, control-character, duplicate, or malformed response account bindings remain ambiguous and block exhaustiveness; only a valid non-target identifier is explicitly foreign. Consistent duplicate owners update page/cursor/terminal once; malformed, mixed, or identity-conflicting entries preserve only other validated posts as partial evidence. A terminal page stops scrolling and drains through a final quiet poll with no trailing CDP command, so events queued during response-body, DOM, or text calls cannot be missed. HTTP/API errors, ambiguous bindings, unresolved/load-failed/invalid bodies, unknown schemas, author failures, or conflicting pagination facts keep `is_exhaustive=false`.
- Douyin profile collection now fails closed on conflicting API/SSR account bindings and merges only same-account API, SSR, network, cached, and visible-header evidence. Certification parsing shares a strict finite tri-state domain, accepts text only from explicit certification fields or a bound DOM badge, and prevents later partial snapshots from erasing public IDs, exact zero metrics, or stronger evidence. Restricted pages retain their original stop reason while allowing one profile-header-only read, never a post-card scan; account ID, verification, and total-likes visibility distinguish public, fallback, and unknown evidence.
- Known Douyin item enrichment can fall back once from missing public SSR detail to a bounded temporary-browser detail snapshot. The fallback accepts only the requested canonical `/video/<id>` or `/note/<id>`, rejects recommendation/list pollution and identity conflicts, preserves explicit access restrictions, and never scrolls, clicks, retries, signs requests, or discovers new posts.
- Markdown and HTML reports now share one auditable contract for platform-specific account fields, fixed collection-status counts, classification lifecycle and coverage, full high/low evidence rows, and source-provided core insights. Pending taxonomy slots remain distinct from model `unknown` / `other`, and profile-index anchors are never presented as item links.
- Authorized OpenAPI coverage now propagates through analysis and both report formats. Reports label userinfo as an authorization evidence source, distinguish an official terminal traversal from a non-exhaustive run, preserve the required public-page disclaimer for anonymous sources, and use a dedicated OpenAPI disclaimer for authorized evidence instead of misclassifying it as an anonymous page or Web-index snapshot.
- Semantic classification now separates lifecycle state, classifier version, and exact coverage at both the analysis root and `meta`. Pending slots remain `null` (with empty labels), strict legacy and immutable file inputs share the same atomic validation path, and pipeline completion additionally requires complete selected-item evidence.
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

### Fixed

- Web-index imports now preserve and enforce explicit date windows before limiting results; unknown-date search cards cannot enter bounded rankings, and derived task metadata retains the requested window.
- Web-index imports can overlay newer public profile fields only from a sealed, same-account anonymous collection commit, with digest-bound provenance and null-preserving field merges. Authorized-owner data is rejected, and freshness must be provably later than the observation/date-precision baseline.
- Browser fallback coverage now records `browser_fallback_launched=false` when SSR satisfies the request without starting a browser, instead of omitting the launch state.
- Failed collection analysis errors now report only sanitized task status and stop reason and explicitly state that no analysis workspace was created.
- Completed taxonomy reports no longer warn that classification may still be pending, and platform `content_type` is labeled separately from model-classified `format`.

- Public Douyin SSR/browser list evidence is now bound to the requested account before it can contribute posts, an empty-page observation, or terminal-page completeness. SSR accepts only frozen account post-list containers; browser transport accepts only frozen public list-response paths and visible user-post cards. Foreign, missing-author, mixed-author, recommendation, and global-page observations are ignored.
- Authorized Douyin collection now follows the official dual-credential identity contract: userinfo receives form-encoded `access_token` and `open_id`, its response must echo the exact `open_id`, and `video.list` receives JSON Content-Type plus the token only in the `access-token` header. Direct and numeric share item URLs must bind to `video_id`; nonnumeric opaque iesdouyin share URLs are source-only, while numeric mismatches fail closed. User-controlled analysis goals that echo the token are rejected before transport or output. The public orchestration entry no longer accepts a preconstructed client that could bypass environment-bound identity verification.
- Authorized limited collection now enforces the unified 1–100 item contract before transport or output reservation. A `video.list` page containing more items than its requested `count` fails closed and can never be truncated into a false terminal-coverage claim.
- Derived analysis now revalidates collection coverage as untrusted input: only typed allowlisted fields propagate, exhaustive claims must agree with terminal signals, task lifecycle, requested range, and normalized item counts, while public platform-protection stops may keep an intentionally sparse non-exhaustive ledger.
- Resume now accepts only an immutable, manifest-verified collection commit for the same platform and canonical account URL. Legacy, cross-account, malformed, duplicate-key, non-finite, or ambiguous JSONL/CSV inputs fail before adapters, network access, or output reservation.
- Account/list/detail protection reasons now stop all later detail and comment requests at task scope. Already collected posts remain auditable partial data, requested comments receive an empty committed artifact and zero-count ledger, and `RATE_LIMITED` propagates through collection and analysis without being downgraded to a parser failure.
- Comment analysis and collection now share the same distinct canonical parent set: only unflagged `SUCCESS`/`PARTIAL` posts are eligible. Strict JSONL uses LF record boundaries (with CRLF support), so Unicode U+2028/U+2029 inside public text is preserved rather than reinterpreted as a record separator.

### Security
- Report links now require canonical HTTPS URLs, while public account, classification, title, metric, statement, and URL text is escaped independently for Markdown and HTML output.
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
