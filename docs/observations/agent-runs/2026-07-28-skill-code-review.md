# Skill Code Review — 2026-07-28

Scope: every Python file under `skill/scripts/` (26 files, ~26k LOC). Five parallel reviewers covered: core infrastructure, entry points, collector adapters, analysis/rendering, and test coverage. Tests cross-referenced against source modules.

## 1. Top-line summary

- **2 blocking bugs** (one in CLAUDE.md §5.6 single-source-of-truth enums, one broken entry path)
- **1 latent blocking bug** (POSIX `parent_identity` semantics; only Windows path uses it today)
- **2 latent security/compliance gaps** (Cookie-harvesting via `n23.tv` HEAD; `open_id` leakage in `analysis_goal`)
- **5 compliance-boundary violations** mapped to specific CLAUDE.md §5 items
- **~20 important correctness/data-integrity issues**
- **~30 code-smell / future-proofing notes**
- **Test coverage is strong overall (908 tests)** but has 3 critical gaps with **zero direct tests** for compliance §5.6 invariants
- **No token leakage in URLs/logs/artifacts** that any reviewer could find — the OpenAPI client deliberately puts the token in the header (GET) and form body (POST) and on the only network egress
- **Dedup/A2-5 root cause:** `_utils.py` was authored to consolidate `_BEIJING`, `_now_iso`, `_int`, `_extract_hashtags` across 4 adapters but the import is broken (BEIJING_TZ missing from `_constants.py`), so all 4 copies still exist

Headline priority fix list below; full findings follow in §3.

## 2. Headline priority list

| # | Severity | Area | Issue |
|---|---|---|---|
| 1 | 🔴 | analyze.py / validate_model_results.py | **Enum mismatch** between the two modules — `validate_model_results.py` uses an enum that no longer matches `TASK_STATUSES`/`STOP_REASONS` in `task_contract.py` |
| 2 | 🔴 | collect.py:101-108 | **Bilibili short-link resolver uses HEAD**; `b23.tv` returns the short URL itself → public entry path is broken |
| 3 | 🔴 | collect_douyin_authorized.py:109-127 | **profile_url written to `task.json` is the OAuth userinfo endpoint**, not `https://www.douyin.com/user/<sec_uid>`; report would render literally "账号主页: https://open.douyin.com/oauth/userinfo/" |
| 4 | 🟡 | collect_douyin_authorized.py:382-384 | **`open_id` leakage in `analysis_goal`** not guarded (only `access_token` is checked) — violates CLAUDE.md §5.7 |
| 5 | 🟡 | collect_douyin_authorized.py:133-158 | **Missing OpenAPI disclaimer** in `collection-report.md` — violates CLAUDE.md §5.10 |
| 6 | 🟡 | collect_douyin_authorized.py:108-131 | **Timing fields missing** (`started_at`/`ended_at`/`duration_ms`/`phase_durations_ms`) — schema divergence with public path |
| 7 | 🟡 | collect_douyin_authorized.py:220-229 | `stop_condition="api_error"` not in the public enum; resume path will reject it |
| 8 | 🟡 | run_pipeline.py:697-718 | **`--classification-results` accepted without `--with-llm-tax`** — silently treats external classifications as authoritative |
| 9 | 🟡 | analyze.py | **Cadence restriction bypass** for index sources |
| 10 | 🟡 | analyze.py + render_report.py | **Disclaimer wording divergence** between PRDs |
| 11 | 🟡 | analyze.py / normalize.py | **`field_coverage` semantics not reconciled** between modules |
| 12 | 🟡 | analyze.py | `KeyError` risk on `excluded_flagged_post_ids` |
| 13 | 🟡 | analyze.py | Duplicate `build_business_insights_prompt` definition |
| 14 | 🟡 | analyze.py | `parse_time` non-deterministic for "M月D日" (year inference) |
| 15 | 🟡 | run_pipeline.py:441-464 | `stop_reason` in `delivery-summary.json` not re-validated |
| 16 | 🟡 | run_pipeline.py:343-352 | Optional artifact co-occurrence not validated |
| 17 | 🟡 | collect.py:1665-1711 | `date_from`/`date_to` written to `task.json` without sanitization |
| 18 | 🟡 | collect.py:2308-2355 | Checkpoint posts silently kept on adapter failure with no `partial_posts` |
| 19 | 🟡 | collectors/douyin.py:440-448 | **401 mapped to `STOP_ACCESS_RESTRICTED`** instead of `STOP_LOGIN_REQUIRED` — violates §5 #1 |
| 20 | 🟡 | collectors/weibo.py:122-125 | **HTTP 302 treated as `LOGIN_REQUIRED`** — 302 is a normal redirect |
| 21 | 🟡 | collectors/douyin.py:449-453 | **Interpolates `e.reason` into user-visible messages** — possible proxy-credential leak on `URLError` |
| 22 | 🟡 | collectors/douyin.py:1730-1734 | SSR with no P0 fields returns `SUCCESS` (only browser fallback path gates `PARTIAL`) |
| 23 | 🟡 | collectors/bilibili.py:459 | `discover_medialist` hardcoded `range(20)` caps pagination at 400 regardless of `limit` |
| 24 | 🟡 | collectors/bilibili.py:1939 | `is_forward` becomes `False` on empty `orig` dict (should be tri-state `None`) |
| 25 | 🟡 | collectors/bilibili.py:1883 | `_empty_post` reports `STATUS=ok` despite zero metrics |
| 26 | 🟡 | collectors/browser_backend.py:451, 524 | CDP error text flows into `task.json` unredacted |
| 27 | 🟡 | collectors/browser_backend.py:618-633 | `navigate_and_get_html` ignores load events → stale `Page.loadEventFired` cross-contamination |
| 28 | 🟡 | collectors/douyin.py:702-706 | Browser-error string matched on Chinese literal; i18n breaks the diagnostic |
| 29 | 🟡 | task_contract.py:148-159 | `account_output_key` returns raw numeric uid for Bilibili; `CON`/`NUL`/`PRN` are Windows reserved device names |
| 30 | 🟡 | immutable_workspace.py:938 | `_reserve_posix` sets `parent_identity=chain.entries[-3].identity` (grandparent, not parent). Latent on POSIX; Windows sets it correctly |
| 31 | 🟡 | task_contract.py:122-135 | `validate_analysis_goal` bounds by code points, not bytes (CJK/emoji overflow) |
| 32 | 🟡 | csv_contract.py:232-248 | `duration_seconds` float truncated to int silently (12.7 → 12) |
| 33 | 🟡 | csv_contract.py:288 | `deserialize_csv_cell` returns float for integer-typed numeric cells |
| 34 | 🟡 | execution_timing.py:32-46 | `phase_durations_ms` sum may not equal `duration_ms` by up to N ms |
| 35 | 🟡 | collectors/_utils.py:17 | **ImportError**: `BEIJING_TZ` imported from `_constants.py` but never defined |
| 36 | 🟡 | import_index_snapshot.py:539-563 | date-filter + limit truncation order is rank-biased |
| 37 | 🟡 | import_index_snapshot.py:245 | `KeyError` instead of `EvidenceError` on missing `observed_at` |
| 38 | 🟡 | collect.py:2143-2155 | Bilibili UID exposed in default workspace name (raw, not hashed) |
| 39 | 🟡 | validate_model_results.py | Threshold and singleton-rate paths uncovered; `collect_business_errors` entirely untested |
| 40 | 🟡 | tests/ | **Zero direct tests for `task_contract.py`**, `csv_contract.py`, `execution_timing.py` |

## 3. Findings by area

### 3.1 Collector adapters (reviewer: a9ad209285db6b69a)

**Compliance violations (§5):**

- **C1** `douyin.py:440-448` — 401 collapsed into `STOP_ACCESS_RESTRICTED`. Per §5 #1, 401 should be `LOGIN_REQUIRED`. Use `STOP_LOGIN` from `_constants.py`.
- **C3** `weibo.py:122-125` — 302 (HTTP "Found") in the login-wall set. 302 is a normal redirect (`weibo.com/<name>` → `/u/<uid>`). Drop 302 (and 405). Body-based detection already exists.
- **C4** `bilibili.py:1883` — `_empty_post` from search-degradation path sets `collection_status="ok"` despite zero metrics. Per §5 #4, missing data must surface as `PARTIAL` or `null`, never invented success.

**Data integrity:**

- **D1** `douyin.py:1730-1734` — `build_post_raw` returns `SUCCESS` when SSR has no P0 fields. Only gates `PARTIAL` when `browser_source and p0_missing_fields`. Drop the `browser_source` gate.
- **D2** Three different `_int` implementations across bilibili/douyin/`_utils`. The `_utils.parse_int` is the most capable but the broken import (B1) means it isn't adopted. `"1.2万+"` parses as 12000 in douyin but raises in bilibili.
- **D3** `douyin.py:449-453` — interpolates `e.reason` into user-visible messages. On some Linux distros and proxies with auth, `e.reason` can contain proxy credentials (`<urlopen error Tunnel connection failed: 407 Proxy Authentication Required for 'http://user:pass@proxy:8080'>`). Use fixed diagnostic code.
- **D4** `bilibili.py:459` — `discover_medialist` hardcoded `range(20)` upper bound. With `size=20`, pagination caps at 400 regardless of `limit`. Replace with `range((limit + size - 1) // size + 5)`.
- **D5** `bilibili.py:1939` — `is_forward = bool(it.get("orig")) if "orig" in it else None` — empty `orig` dict becomes `False`. Should be `None` (no explicit evidence either way). Violates §5 #5 tri-state contract.

**Security:**

- **S1** `browser_backend.py:451, 524` — CDP error text (page-controlled) flows into `task.json` unredacted. Truncate to bounded length and exclude control characters.
- **S2** `browser_backend.py:618-633` — `navigate_and_get_html` ignores `Page.loadEventFired`, uses unconditional `time.sleep`. If a `BrowserSession` is reused, stale `loadEventFired` cross-contaminates the next caller. Currently dead code but high-risk.
- **S3** `douyin.py:702-706` — `if "未找到可用的浏览器" in str(exc)` for diagnostic matching. Any i18n change to the error silently misclassifies. Replace with enum attribute on `BrowserError`.

**Edge cases:**

- **E5** `bilibili.py:719-730` — `empty_streak` only incremented when `items` is empty. If API returns items but `_extract_dynamic_card` returns `None` for every one, `empty_streak` stays 0 and the loop pages until `has_more=False`. Increment when items present but no cards extracted.
- **E3** `weibo.py:198-200` — `_parse_weibo_time` preserves original timezone offset (e.g. `+00:00`) instead of normalizing to `+08:00`.

**DRY (A-series, all rooted in B1):**

- A2 `_BEIJING` redefined 4× (bilibili/douyin/weibo/_douyin_browser_transport)
- A3 `_now_iso()` defined 4×
- A4 `_int()` defined 4× with subtle differences
- A5 `_extract_hashtags` defined 4× with 3 different signatures

### 3.2 Core infrastructure (reviewer: ac92322294f223ac0)

**Blocking (latent):**

- `task_contract.py:148-159` — `account_output_key` returns raw numeric uid for Bilibili. If identity is `CON`, `NUL`, `PRN`, `AUX`, `COM1`-`COM9`, `LPT1`-`LPT9`, the resulting directory becomes a device handle on Windows. Reject bare-digit uids matching Windows reserved names, or always hash.
- `immutable_workspace.py:938` — `_reserve_posix` sets `parent_identity=chain.entries[-3].identity` which is the **grandparent**, not the parent. The chain builds `[root, ..., parent, target, source]`; `[-3]` is `target` (or `parent` if the path is shallow). Latent: the field is only consumed on Windows, where `_reserve_windows` sets it correctly. Would break on cross-backend migration.

**Important:**

- `task_contract.py:122-135` — `validate_analysis_goal` bounds by code points, not bytes. A 500-emoji string is "500 chars" by `len()` but 2000 UTF-8 bytes. If downstream budgets are byte-bounded, this lets a goal exceed budgets.
- `csv_contract.py:232-248` — `serialize_csv_cell` for `duration_seconds` truncates float to int silently. `12.7` → `12`. Document or round.
- `csv_contract.py:288` — `deserialize_csv_cell` returns float for integer-typed numeric cells. Round-trip drift for views/likes/etc.
- `execution_timing.py:32-46` — `phase_durations_ms` sum may not equal `duration_ms` by up to N ms (each phase rounds down independently). Build sum first, then allocate per-phase.
- `immutable_workspace.py:917, 923` — `_reserve_posix` has two `os.mkdir` calls. If second fails, target dir leaks.

**Verified safe (worth recording to avoid regressions):**

- `preflight_workspace_target` Windows TOCTOU window — junction attack caught downstream by `os.mkdir` raising `FileExistsError`.
- `commit()` flow — markers, fsync, identity verification all sequenced correctly; `WorkspaceCommitIndeterminate` is the right error when fsync fails.
- `_parse_windows_directory_buffer` — bounds checks hold.

### 3.3 Entry points (reviewer: a0aafe0e41f51a29c)

**Blocking:**

- **D-1** `collect_douyin_authorized.py:109-127` — `profile_url` fallback is `_PROFILE_ENDPOINT = "https://open.douyin.com/oauth/userinfo/"`. The OpenAPI `collect_profile` returns the OAuth endpoint, not the public `https://www.douyin.com/user/<sec_uid>` URL. On API failure, fallback is again the OAuth endpoint. Reports would render literally "账号主页: https://open.douyin.com/oauth/userinfo/". Synthesize from `sec_uid` or fail loudly.
- **C-2** `collect.py:101-108` — `_follow_bilibili_short_link` uses `HEAD`. `b23.tv` doesn't support HEAD; returns the short URL itself. The short URL fails `_BILIBILI_PROFILE_RE.fullmatch` downstream. Use `GET` with redirect handler.

**Important (compliance/security):**

- **D-2** `collect_douyin_authorized.py:382-384` — only `access_token` is checked against `analysis_goal`. CLAUDE.md §5.7 requires both `access_token` AND `open_id` to never enter artifacts. A user can smuggle `open_id` into `analysis_goal` and have it surface in `task.json` and the report.
- **D-5** `collect_douyin_authorized.py:133-158` — Missing OpenAPI disclaimer in `collection-report.md`. Per §5.10, OpenAPI source requires a dedicated disclaimer distinct from the anonymous one.
- **D-3** `collect_douyin_authorized.py:108-131` — Missing `ExecutionTimer` instance; `task.json` lacks `started_at`/`ended_at`/`duration_ms`/`phase_durations_ms`. Schema divergence with public path.
- **D-4** `collect_douyin_authorized.py:220-229` — `coverage["stop_condition"] = "api_error"` is not in the public enum documented at `collect.py:1297-1308`. Resume path will reject it.
- **C-3** `collect.py:2143-2155` — Bilibili workspace name uses raw UID (e.g. `bilibili-123456-20260728`). Douyin is hashed. Either hash both or document.
- **C-7** `collect.py:1665-1711` — `date_from`/`date_to` written to `task.json` raw; all other fields go through `_safe_*` helpers. External callers of `run()` could pass arbitrary strings.
- **C-9** `collect.py:2308-2355` — On non-Douyin platform failure with `checkpoint_state` set, `posts` is initialized from checkpoint; if the adapter raises without `partial_posts`, the checkpoint posts are kept silently and the checkpoint is overwritten with the same data, losing the resume digest.

**Important (pipeline correctness):**

- **R-1** `run_pipeline.py:343-352` — Optional artifact co-occurrence not validated. If an optional artifact depends on another (e.g. `taxonomy-result-template.json` requires `taxonomy-prompt.md`), no cross-validation.
- **R-2** `run_pipeline.py:697-718` — `--classification-results` accepted without `--with-llm-tax`. External classifications are silently treated as authoritative against a possibly-missing taxonomy.
- **R-3** `run_pipeline.py:441-464` — `stop_reason` in `delivery-summary.json` not re-validated against `safe_stop_reason_label`. Per §5 #6, single source of truth.

**Nits:**

- C-4 budget validation duplicated in `main()` and `run()` (lines 2779-2805 vs 1922-1947)
- C-5 `SOCIAL_BROWSER_FALLBACK` env: `env_value != "0"` enables fallback on empty/`"false"`/`"no"`
- C-6 `--since` uses start-of-day, not end-of-day (intent is "strictly after")
- D-6 credential length bounds not enforced (4 KB env value would pass)
- I-6 date window no year sanity range (year 3025 accepted)
- X-2 task_id set in two places (`validate_evidence` and `run`)

### 3.4 Analysis & rendering (reviewer: a9846586f87a07a6d)

The published version differs from the agent's draft in important ways; the **critical findings are short and high-value**:

- **B1** analyze.py — cadence restriction bypass for index sources
- **B2** validate_model_results.py vs analyze.py — enum mismatch
- **I1** KeyError risk on `excluded_flagged_post_ids`
- **I2** Duplicate `build_business_insights_prompt` definition
- **I3** Disclaimer wording in `render_report.py` diverges from PRD §5 #10
- **I4** `field_coverage` semantics not reconciled between normalize.py and analyze.py
- **I5** `parse_time` non-deterministic for "M月D日" (year inferred from current date)
- **I6** `_comment_semantic_input` not cached in `analyze_comments_in_memory`

Plus ~30 nits (S1–S30): hardcoded Chinese strings duplicated, `parse_int`/`parse_bool` handle some "null" aliases asymmetrically, `_safe_get` collapses explicit `None` to default, validation checks incomplete (per-pattern evidence minimums, hex-case for SHA-256), `monthly_distribution` sort relies on ISO string lexical order.

**Worth noting:**
- `parse_int` (analyze.py:220-232) accepts booleans via `float(s)` — `float("True")` raises → returns `None`. Correct (booleans should not be metric values) but `parse_bool` doesn't handle `"null"`/`"none"`/`"nan"` aliases that `parse_int` does (line 224). Asymmetry.
- `validate_business_insight_results` (analyze.py:3414-3420) does not check `limitations` for control chars directly; `_business_text` strips them (line 3061) so this is OK, but the validation runs in order, so limitations are checked last.
- `restrictions_source` check (analyze.py:4200-4211) — any unrecognized `stop_reason` is rejected as "invalid restriction audit", which conflates "no marker expected" with "marker mismatch".

### 3.5 Test coverage (reviewer: acc790b8c7e43079c)

**Inventory:** 908 test functions across 27 files. Strong overall.

**Critical gaps with zero direct tests:**

1. **`task_contract.py`** — compliance §5.6 single-source-of-truth module. `safe_stop_reason_label`, `safe_task_status_label`, `validate_analysis_goal`, `new_task_id`, `account_output_key`, `TASK_STATUSES`/`STOP_REASONS` integrity — all untested directly.
2. **`csv_contract.py`** — entire 317-line module. `serialize_csv_cell`/`deserialize_csv_cell` round-trips, `_safe_legacy_literal` AST allowlist, `MAX_STRUCTURED_CELL_CHARS`/`MAX_LITERAL_NODES`/`MAX_LITERAL_DEPTH` boundaries, `_coerce_json_compatible` rejection of NaN/inf/non-string keys.
3. **`execution_timing.py`** — `ExecutionTimer.phase` (accumulation) and `snapshot` (monotonic / JSON-safe / phase_durations_ms sorted) — only the integration shape is assertion-covered via `test_collection_contracts.py`.

**Compliance-boundary test holes:**

- §5.4 null vs 0: no direct test for `serialize_csv_cell("views", None) == ""` round-trip, no test that "null" literal in JSONL is rejected
- §5.5 tri-state: no test for `"true"/"false"/"null"/missing` → `True`/`False`/`None`/`None` in JSONL round-trip
- §5.7 token leakage: no test that `task.json` disk artifact never contains `access_token` after `--analysis-goal=<token>` (only rejection is tested)
- §5.10 disclaimer: only public-page disclaimer is verified; **OpenAPI disclaimer variant is not tested**
- §5.8 Douyin `--all`: no test for `PUBLIC_ALL_HARD_MAX_*+1` rejection
- §5.9 browser fallback: `SOCIAL_BROWSER_FALLBACK=0` + `--browser-fallback` interaction not tested; no test that raw page text containing a fake token is never persisted

**Module-specific gaps:**

- `url_policy.py` — only rejection paths tested; no happy-path for `bilibili.com/123`, `iesdouyin.com`, `weibo.com/u/<id>`, `sanitize_routing_url` low-level rejects. **This is the security perimeter.**
- `_constants.py` — `validate_public_limit` boundary inputs (`0`, `100`, `101`, `True`, `None`) not directly tested; `DOUYIN_PAGE_STATE_PATTERNS` regex matchers have no direct unit tests (false-positive risk is hidden).
- `validate_model_results.py` — `collect_business_errors` entirely untested; threshold paths uncovered.
- `analyze.py` private helpers — `parse_collection_status`, `filter_task_date_window`, `format_published_at_for_boundary`, `compute_metric_summary` — no direct unit tests.
- `tools/skill_eval/runner.py` — zero tests.

**Tests that give false confidence (recommend fixing):**

1. `test_resolve_profile_url.py:42-47` — relies on `ValueError` raising for HTTP; no happy-path baseline
2. `test_demo_runner.py:18` — `callable(runner.run)` passes for any callable
3. `test_skill_hardening.py:73-89` — `assert axes["engagement_efficiency"]["denominator_floor"] > 1` is satisfied by any constant > 1
4. `test_comment_analysis.py:114-167` — `result == {**result, ...}` is a no-op pattern (the line is harmless but misleading)
5. `test_skill_eval_aggregate.py:130` — comment says "缺失不回填 0" but assertion is for a single surviving value; doesn't verify mean computation
6. `test_pinned_fixture_and_summary_contract.py:97-105` — tests SKILL.md contains specific Chinese phrases (brittle)
7. `test_skill_hardening.py:156-168` — calls private `_validate_business_claim_support`

## 4. Recommended fixes (priority order)

### Fix this week (correctness/compliance)

1. **Profile URL in OpenAPI path** (D-1) — synthesize `https://www.douyin.com/user/<sec_uid>` from `data.get("sec_uid")`; fail loudly if missing.
2. **`b23.tv` resolver** (C-2) — switch to `GET` with a custom redirect handler.
3. **`open_id` leakage guard** (D-2) — also check `open_id` against `analysis_goal`.
4. **OpenAPI disclaimer** (D-5) — add dedicated disclaimer block to `collection-report.md`.
5. **Timing fields in OpenAPI path** (D-3, X-1) — instantiate `ExecutionTimer` and write the timing block.
6. **401 mapping in douyin** (C1) — map to `STOP_LOGIN_REQUIRED`, not `STOP_ACCESS_RESTRICTED`.
7. **302 in weibo login set** (C3) — drop 302 from login-wall detection.
8. **`task.json` schema divergence** (X-1) — single source of truth for the schema; both entry points must conform.

### Fix in next iteration (compliance drift + data integrity)

9. **Enum mismatch** (B2) — synchronize `validate_model_results.py` with `TASK_STATUSES`/`STOP_REASONS` from `task_contract.py`.
10. **Cadence restriction bypass** (B1) — explicit handling for index sources.
11. **`field_coverage` reconciliation** (I4) — single source of truth in `csv_contract.py`.
12. **`--classification-results` without `--with-llm-tax`** (R-2) — require either both, or emit `EXTERNAL_TAXONOMY` diagnostic.
13. **`stop_reason` re-validation** (R-3) — run through `safe_stop_reason_label` before serializing.
14. **POSIX `parent_identity`** (immutable_workspace.py:938) — fix the `chain.entries[-4]` index even though it's latent.
15. **`CON`/`NUL` reserved names** (task_contract.py:148-159) — reject or hash.
16. **`_utils.py` import error** (B1 in agent review) — add `BEIJING_TZ` to `_constants.py` or delete `_utils.py`.
17. **Auth-path `task.json` `profile_url`** (D-1) — same as #1 above.

### Hardening pass (security / data-quality)

18. **Proxy-credential leak in douyin `_fetch`** (D3) — fixed diagnostic string.
19. **CDP error text in browser_backend** (S1) — truncate and exclude control chars.
20. **`navigate_and_get_html` dead-code bug** (S2) — delete or refactor.
21. **Empty `orig` dict → `False`** (D5) — replace with `None`.
22. **`_empty_post` STATUS=ok with zero metrics** (C4) — change to `PARTIAL`.
23. **`build_post_raw` P0 field gate** (D1) — drop `browser_source` requirement.
24. **`discover_medialist` hardcoded 20** (D4) — derive from `limit`.
25. **Checkpoint posts on failure** (C-9) — preserve with explicit log + `task_status=PARTIAL`.
26. **`date_from`/`date_to` sanitization** (C-7) — apply `_safe_timestamp`.
27. **Bilibili UID exposed in workspace name** (C-3) — hash or document.
28. **Chinese-string diagnostic match in browser fallback** (S3) — enum attribute on `BrowserError`.

### Test additions (highest ROI)

29. **`tests/test_task_contract.py`** — direct tests for `safe_stop_reason_label` (all 3 branches), `safe_task_status_label`, `validate_analysis_goal` (empty / control chars / NFKC / length=501), `new_task_id` (format / monotonicity / uniqueness), `account_output_key` (deterministic hash stability).
30. **`tests/test_csv_contract.py`** — round-trip for `serialize_csv_cell`/`deserialize_csv_cell`, `_safe_legacy_literal` allowlist (`__import__('os')`, deep nesting, oversize), `null → ""` → `"" → None` invariant.
31. **`tests/test_execution_timing.py`** — `ExecutionTimer.phase` accumulation, `snapshot` monotonicity, `phase_durations_ms` reconciliation.
32. **`tests/test_url_policy.py`** — happy paths for `bilibili.com/123`, `iesdouyin.com`, `weibo.com/u/<id>`; `sanitize_routing_url` low-level rejects (HTTP, credentials, port, percent in path).
33. **`tests/test_constants.py`** — `validate_public_limit` boundary inputs, `DOUYIN_PAGE_STATE_PATTERNS` direct regex matchers (positive + false-positive cases).
34. **`tests/test_validate_model_results.py`** — `collect_business_errors`, threshold paths, CLI matrix.
35. **OpenAPI disclaimer test** (§5.10) — currently only public-page disclaimer is verified.
36. **JSONL tri-state round-trip test** (§5.5) — `"true"/"false"/"null"/missing` → `True`/`False`/`None`/`None`.
37. **`task.json` on-disk token-leakage test** (§5.7) — verify `access_token` substring never appears in artifacts after `--analysis-goal=<token>`.

### Cleanup (later)

38. The `_utils.py` consolidation — finish migrating `_BEIJING`, `_now_iso`, `_int`, `_extract_hashtags` to a shared helper, or delete the file.
39. Duplicate `build_business_insights_prompt` definition (analyze.py).
40. `_validate_business_claim_support` token lists — lift to module-level constants.
41. `monthly_distribution` sort — explicit tuple key for clarity.
42. Replace brittle demo-runner-style and `_validate_business_claim_support` private-API tests with public-API assertions.
43. Weibo-specific normalization tests for `"刚刚"` / `"X分钟前"` / `"MM-dd HH:mm"`.
44. Phase_durations_ms reconciliation in `ExecutionTimer.snapshot` (item #34 above covers the test; the fix is to compute sum first, then allocate per-phase).
45. `csv_contract` round-trip type drift (item #33 above covers the test; the fix is to detect `^\d+$` and return int).

## 5. Cross-cutting themes

1. **The compliance contract is mostly honored.** The two outright violations are C1 (401-mapping) and the missing OpenAPI disclaimer (D-5). The latent violations are the POSX `parent_identity` index and the Windows reserved-name issue.
2. **WBI signing (bilibili) and OpenAPI client (douyin) are both safely bounded.** No replay, no forged signatures, no token in URL. The OpenAPI client's `_is_fixed_endpoint` (douyin_openapi.py:329-361) is a particularly strong defense against SSRF — worth holding up as the pattern.
3. **Browser fallback is the riskiest surface.** String-matched diagnostic code (S3), CDP-error leakage (S1), the unused `navigate_and_get_html` (S2), and Chinese-literal error matching all deserve a focused hardening pass.
4. **The consolidation that `_utils.py` was meant to provide failed silently.** B1 + A1-A5 are a single root cause: the shared helpers were authored but never wired up, and the existing code kept duplicating.
5. **Test suite is strong on coverage of the collection path but weak on compliance invariants.** The three gap modules (task_contract, csv_contract, execution_timing) together define the contract that the rest of the codebase promises to honor. Pin them down with direct unit tests.
6. **No secret leakage through tokens in URLs, logs, or artifacts** that any reviewer could find. Douyin OpenAPI puts the token in the header for GET (correct) and form body for POST (correct, per docs). Bilibili stores buvid cookies in-memory only. Weibo does not handle tokens at all. The single latent secret-leakage path is `open_id` smuggled via `analysis_goal` (D-2).
7. **The `_utils.py` consolidation attempt and the OpenAPI profile_url default are both "code that looks fine but is silently broken".** Code reviewers should be especially alert for patterns where dead code paths or fallback default values are never exercised by tests.
