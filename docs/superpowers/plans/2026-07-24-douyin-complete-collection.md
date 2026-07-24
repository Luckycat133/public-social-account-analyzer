# Douyin Complete Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an honest best-effort all-public-post mode, an official OAuth-authorized full-history mode, and close the collection-integrity/documentation gaps identified against the PRD.

**Architecture:** Public accounts continue through SSR and an isolated no-login browser that passively observes page-owned pagination; a coverage ledger distinguishes an explicit terminal page from every partial stop. A separate standard-library OpenAPI command handles only the token owner's authorized account and follows official cursors. Shared workspace artifacts record coverage, per-item enrichment and persisted comment outcomes without ever storing credentials.

**Tech Stack:** Python 3.9+ standard library, Chrome DevTools Protocol through the repository browser backend, pytest as a development-only dependency, Markdown.

## Global Constraints

- Runtime dependencies remain exactly `[]`; no new Python package is allowed.
- Public collection never logs in, reuses user profiles/Cookies, solves challenges, forges signatures, replays signed URLs, rotates proxies, or retries around an access restriction.
- Public `is_exhaustive=true` is allowed only after a verified post-list payload explicitly reports `has_more=false`.
- Authorized `is_exhaustive=true` is allowed only after the official `/video/list/` response reports `has_more=false`.
- Idle, timeout, date cutoff, requested limit, max items, max scrolls, repeated page/cursor, index evidence, login, verification and access restriction are never exhaustive.
- OAuth credentials are read only from `DOUYIN_OPENAPI_ACCESS_TOKEN`; token values must never appear in URLs, files, stdout/stderr, exceptions or diagnostics.
- Unknown public fields remain `null`; invalid/missing platform post IDs never produce an account-profile URL as item evidence.
- Every production behavior change follows RED -> GREEN -> REFACTOR and records exact test evidence.
- Work only in `/Users/jack/Documents/public-social-account-analyzer/.worktrees/douyin-browser-fallback`; preserve the unrelated deletion in the main checkout.

---

### Task 1: Public all-post pagination and coverage ledger

**Files:**

- Modify: `skill/scripts/collectors/_douyin_browser_transport.py`
- Modify: `skill/scripts/collectors/douyin.py`
- Modify: `skill/scripts/collectors/base.py`
- Modify: `skill/scripts/collect.py`
- Modify: `skill/references/data-schema.md`
- Test: `tests/test_douyin.py`
- Test: `tests/test_collectors.py`

**Interfaces:**

- Produces `extract_post_page_observations(data)` with list-scoped `items`, optional `has_more`, and a non-persisted cursor value.
- Extends `DouyinBrowserResult` with a sanitized `coverage: dict[str, Any]`.
- Adds `DouyinCollector.collect_all_post_list(url, date_range=None, max_items=10000, max_seconds=1800.0, max_scrolls=2000)`.
- Adds `BaseCollector.get_collection_coverage() -> dict[str, Any]`, defaulting to `{}`.
- Adds CLI `--all`, `--max-items`, `--max-seconds`, and `--max-scrolls`; `--all` is supported only for Douyin.

- [ ] **Step 1: Write failing pagination-observation tests**

Add tests proving that pagination metadata is accepted only from a dictionary that owns a recognized post-list key; unrelated nested `has_more=false` is ignored; duplicate items merge; cursor values are never copied into the returned coverage dictionary.

```python
payload = {"data": {"aweme_list": [AWEME], "has_more": False, "max_cursor": "secret-cursor"}}
pages = extract_post_page_observations(payload)
assert pages[0].has_more is False
assert pages[0].cursor == "secret-cursor"
assert extract_post_page_observations({"feed": {"has_more": False}}) == []
```

- [ ] **Step 2: Run the focused tests and record the expected RED result**

Run `python3 -m pytest tests/test_douyin.py -k 'page_observation or exhaustive or coverage' -q` and confirm failure because the observation/coverage API does not exist.

- [ ] **Step 3: Implement list-scoped observations and terminal-page handling**

Keep normal limited collection behavior compatible. In exhaustive mode continue normal page scrolling until explicit `has_more=false` or a safety stop. Persist only counts, booleans and cursor fingerprints/counters—not raw cursors, headers, response bodies or query strings.

- [ ] **Step 4: Add failing CLI/workspace coverage tests**

Tests must prove: `--all` rejects non-Douyin URLs; positive budget validation; explicit terminal page produces `is_exhaustive=true`; idle/timeout/repeat/max budget with partial posts produces `task_status=PARTIAL`; standard `--limit 30` remains compatible.

- [ ] **Step 5: Implement `collect_all_post_list` and workspace reporting**

Write `collection_coverage` into `task.json` and a dedicated “覆盖与完备性” section in `collection-report.md`. `--all` incomplete results must raise/propagate a sanitized partial-result condition so existing posts survive while task status becomes `PARTIAL`.

- [ ] **Step 6: Run focused and full tests, then commit**

Run the focused tests, then `python3 -m pytest -q`. Commit as `feat(douyin): add accountable all-post collection`.

### Task 2: Official authorized-account full-history collector

**Files:**

- Create: `skill/scripts/collectors/douyin_openapi.py`
- Create: `skill/scripts/collect_douyin_authorized.py`
- Create: `tests/test_douyin_openapi.py`
- Modify: `skill/references/data-schema.md`
- Modify: `skill/references/exceptions.md`

**Interfaces:**

- `DouyinOpenAPIClient(access_token, transport=None)` calls fixed-host official endpoints only.
- `collect_profile()` calls `POST https://open.douyin.com/oauth/userinfo/`.
- `collect_video_pages(limit=None, page_size=20)` calls `GET https://open.douyin.com/video/list/` using `cursor`/`count`, returning normalized items plus a coverage ledger.
- CLI reads only `DOUYIN_OPENAPI_ACCESS_TOKEN` and writes the existing workspace artifact contract.

- [ ] **Step 1: Write failing transport, mapping and secrecy tests**

Use an injected fake transport with two pages: cursor `0 -> 20`, second page `has_more=false`, and a duplicate video across pages. Assert stable order, ID deduplication, mapped title/time/pinned/type/metrics/official share URL, `is_exhaustive=true`, and no token substring in any requested URL, serialized artifact, captured stdout/stderr or exception.

- [ ] **Step 2: Verify RED**

Run `python3 -m pytest tests/test_douyin_openapi.py -q`; expected failure is missing module/CLI.

- [ ] **Step 3: Implement the minimal fixed-host client and mapper**

Use `urllib.request`; token is an `access-token` header. Validate top-level and data-level error codes, list type, boolean/integer `has_more`, cursor progress, non-empty numeric `video_id`, and Douyin-owned HTTPS share URLs. Strip query/fragment before persistence.

- [ ] **Step 4: Implement partial-stop and workspace tests**

Cover missing token, API error before page one, API error after one page, repeated cursor, repeated zero-new page, requested limit, `--all`, refuse overwrite, and standard outputs (`source/profile.json`, `source/posts.jsonl`, `normalized-posts.csv`, `task.json`, `collection-report.md`).

- [ ] **Step 5: Implement the CLI and partial-result contract**

Only the token owner returned by `/oauth/userinfo/` is collected. `--all` requires terminal `has_more=false` for `COMPLETED`; partial API failures preserve acquired items. Do not implement OAuth login, token exchange, token refresh or third-party account lookup.

- [ ] **Step 6: Run focused/full tests and commit**

Run `python3 -m pytest tests/test_douyin_openapi.py -q`, then the full suite. Commit as `feat(douyin): add authorized full-history collector`.

### Task 3: Collection integrity, detail outcomes and persisted comments

**Files:**

- Modify: `skill/scripts/collectors/douyin.py`
- Modify: `skill/scripts/collect.py`
- Modify: `skill/references/data-schema.md`
- Modify: `skill/references/exceptions.md`
- Test: `tests/test_douyin.py`
- Test: `tests/test_collectors.py`
- Test: `tests/test_datetime.py`

**Interfaces:**

- Adds `--enrich-details` and per-item `platform_metrics.detail_status`.
- Persists comment records in `source/comments.jsonl` and aggregate `comment_collection` in `task.json`/report.
- Rejects `date_from > date_to` before creating or mutating a workspace.

- [ ] **Step 1: Write failing ID/dedup/date tests**

Prove that SSR list entries without a numeric `aweme_id` are skipped, duplicate IDs merge missing fields, a profile URL is never emitted as a post URL, and reversed date ranges exit with code 2 before workspace creation.

- [ ] **Step 2: Verify RED and implement the integrity fixes**

Run the focused tests, implement the minimum validation/dedup/range checks, rerun until green.

- [ ] **Step 3: Write failing detail-enrichment tests**

Prove that enrichment calls only genuine item URLs missing title/published time/duration/topics, merges only missing values, and records `SUCCESS`, `UNAVAILABLE`, or `NOT_NEEDED` without replacing reliable list fields.

- [ ] **Step 4: Implement detail outcomes**

Failures remain item-level and append sanitized error-log entries; they never change an otherwise successful account task to `FAILED`.

- [ ] **Step 5: Write failing comment-persistence tests**

Prove `--comments` writes every returned comment, includes the parent post ID/URL, enforces 20 comments per post, and records attempted posts, comments collected, empty results and failures. Empty comments must not be described as collected comments.

- [ ] **Step 6: Implement comment persistence and run tests**

Write UTF-8 JSONL atomically enough for the existing workspace model; run focused tests and the full suite. Commit as `fix(collection): preserve Douyin detail and comment outcomes`.

### Task 4: Consolidated documentation and acceptance refresh

**Files:**

- Modify: `README.md`
- Modify: `USAGE.md`
- Modify: `CHANGELOG.md`
- Modify: `TODO.md`
- Modify: `skill/SKILL.md`
- Modify: `skill/references/platform-douyin.md`
- Modify: `skill/references/douyin-index-evidence.md`
- Modify: `skill/evals/cases.md`
- Modify: `skill/evals/evals.json`
- Modify: `docs/observations/douyin-browser-fallback-acceptance.md`
- Modify: `docs/observations/douyin-sandbox-index-acceptance.md`
- Create: `docs/抖音需求实现状态.md`
- Test: relevant documentation/eval tests

- [ ] **Step 1: Write failing documentation-contract tests**

Assert that public best-effort, authorized full-history, terminal-page semantics, token secrecy, comments output and exact CLI examples all appear in the appropriate user/Skill docs.

- [ ] **Step 2: Update human and Skill documentation**

Follow Standard Readme and Keep a Changelog. Explain that arbitrary public accounts cannot be guaranteed full history, official OAuth applies only to the token owner, index evidence is never exhaustive, and no-login `--all` is a bounded best-effort traversal.

- [ ] **Step 3: Refresh real-account evidence**

Record the 2026-07-24 current probes for 中国政府网 and 大漠叔叔: both direct browser probes returned zero items after three idle rounds with no candidate XHR/DOM cards; preserve the earlier login-wall run as historical evidence rather than overwriting it. Record the 10-item 大漠叔叔 Jingxuan subset as non-exhaustive. State that authorized OpenAPI live verification remains pending when no user token is supplied.

- [ ] **Step 4: Publish a PRD coverage matrix**

`docs/抖音需求实现状态.md` must map PRD account fields, post fields, metrics, special handling, comments and AC-01/02/03/06/08/10 to `done`, `partial`, `authorized-only`, or `not-yet-live-verified`, with file/test evidence and no inflated claims.

- [ ] **Step 5: Final validation and commit**

Run full pytest (outside the restricted sandbox for loopback browser tests), compile all Python, validate JSON, validate the Skill, run `git diff --check`, and verify `pyproject.toml` runtime dependencies remain `[]`. Commit as `docs: consolidate Douyin collection status`.

### Task 5: Whole-branch review and delivery

**Files:** No planned production edits; fixes may touch files named by review findings.

- [ ] **Step 1: Generate a whole-branch review package from `git merge-base main HEAD` to `HEAD`**
- [ ] **Step 2: Dispatch independent final reviewers for correctness and security/documentation**
- [ ] **Step 3: Fix every Critical/Important finding in one fix wave and re-review**
- [ ] **Step 4: Re-run full validation, inspect commit history/status, and push the feature branch to its configured remote**
- [ ] **Step 5: If no remote exists, stop before inventing one and report the exact missing remote URL/target**
