# Task 3C-C1A implementation report

Baseline: `f913263`.

## Scope completed

- Replaced fabricated two-state defaults for public evidence flags with a
  three-state contract. `is_pinned`, `is_repost`, and `is_promoted` now remain
  `null` unless the platform response explicitly proves `true` or `false`.
  The separate `local_record_key` provenance field intentionally remains a
  two-state local flag and defaults to `false` in legacy analysis input.
- Made per-post collection status auditable end to end. Missing status becomes
  `PARTIAL` / `inferred_missing`; invalid status becomes `PARTIAL` /
  `inferred_invalid`; trusted explicit states use `declared`. The contract is
  enforced in collectors, normalization, analysis, direct importers, OpenAPI
  output, ordinary collection persistence, and legacy resume persistence.
- Added structured `COLLECTION_STATUS_INFERRED` and
  `FIELD_VISIBILITY_INVALID` normalization warnings. Warning counts and details
  are preserved in coverage, and any normalization warning makes the pipeline's
  normalization phase and derived task status `PARTIAL` instead of silently
  publishing a complete result.
- Preserved `hashtags`, `platform_metrics`, `field_visibility`, public flags,
  provenance, timestamps, and source links across in-memory normalization,
  CSV, analysis, and `analysis.posts`. Structured values are deep-copied so
  downstream mutation cannot change normalization results.
- Added the shared zero-dependency `csv_contract.py` boundary used by
  `normalize.py`, the general collector, and the authorized Douyin collector.
  New CSV writes use compact sorted-key UTF-8 JSON for hashtags and structured
  objects, lowercase booleans, empty cells for null, and reject non-finite JSON.
- Restored safe backward reading for the historical collector's Python-repr
  CSV cells. The fallback has a 16,384-character cell limit, AST node/depth and
  syntax allowlists, `ast.literal_eval` only after those checks, target-type
  checks, recursive JSON-compatible conversion, finite-float validation, and
  no expression execution. Deep canonical JSON recursion and memory failures
  are caught and degrade to empty structured evidence.
- CSV-only incremental resume now restores canonical and historical hashtags,
  objects, six boolean/provenance fields, and numeric columns to JSON-safe
  runtime types before writing the new `source/posts.jsonl`. Resumed legacy
  rows also receive the collection-status contract, while the old workspace is
  verified byte-for-byte unchanged.
- Analysis now emits a fixed, zero-filled five-state `status_counts` map before
  flag exclusions. Missing and invalid legacy status no longer default to
  success. The default valid sample still excludes pinned, reposted, and
  promoted content while retaining their complete records for audit.
- Deep-approval and community-discussion rates now return `null` when every
  numerator component is unknown. If at least one numerator component is
  observed, remaining unknown components count as zero; the analysis note
  discloses that denominator policy.
- Hardened Bilibili evidence parsing. Pin flags become two-state only after a
  valid top/arc observation; malformed empty payloads remain unknown. Copyright
  accepts only exact enum values `1` / `2` as integers or trimmed canonical
  strings and rejects booleans/floats. Dynamic cards with no `orig` evidence
  keep repost status null. Promotion remains null without public evidence.
- Hardened Weibo boolean evidence. Missing `isTop`, `retweeted_status`, and
  promotion evidence remain null; explicit top values are parsed without
  Python truthiness coercion.
- Updated README, changelog, analysis rules, the unified schema, Douyin index
  evidence, and Bilibili/Douyin/Weibo platform references to match nullable
  flags, status provenance, canonical CSV, bounded historical compatibility,
  fixed status counts, and derived-rate null semantics.

## TDD evidence

- Schema/analysis tests first reproduced loss of structured fields, nullable
  flags, status provenance, fixed status counts, and all-unknown numerator
  behavior before the normalization and analysis changes.
- Collector tests first reproduced false defaults for Bilibili and Weibo,
  missing direct-writer provenance, malformed Bilibili copyright coercion, and
  malformed top/arc responses before their fixes.
- Incremental E2E first failed with missing `collection_status` on resumed raw
  rows, then passed with `PARTIAL` and an auditable inferred source while
  preserving the original workspace bytes.
- General and authorized collector CSV round trips first exposed Python repr,
  capitalized booleans, and lost nested objects; both now round-trip through
  `analyze.build_posts` with exact types and values.
- CSV-only resume first wrote hashtags and nested objects back as strings. Both
  canonical CSV and historical Python-repr CSV now produce type-correct JSONL,
  including nullable public flags and numeric metrics.
- Historical cells `['甲', '乙']`, `{'a': 1}`, and nested tuples are covered.
  Unsafe sets, bytes, non-string object keys, non-finite floats, expression
  calls, oversized cells, and 1,200-level canonical JSON nesting are rejected
  without execution or crashes.

## Final verification

- Final independent full run with loopback permission:
  `python3 -m pytest -q` -> `743 passed in 3.93s`.
- The restricted sandbox's only known failures before escalation were the two
  browser-backend tests that bind a temporary `127.0.0.1` port; the same tests
  pass in the permitted full run.
- `PYTHONPYCACHEPREFIX=/private/tmp/task3cc1a-pycache-final2 python3 -m compileall -q skill/scripts tests`
  -> passed.
- `git diff --check` -> passed.
- `skill/evals/evals.json` parsed successfully with `python3 -m json.tool`.
- `python3 skill/scripts/run_pipeline.py --help` -> passed.
- `pyproject.toml` remains `dependencies = []`; all new runtime parsing and CSV
  handling uses only the Python standard library and existing local modules.

## Independent review

APPROVED / CLEAN with no P0, P1, or P2 findings. The final reviewer exercised
318 focused cases and confirmed the effective full result at 743 / 743 after
the deep-canonical-JSON hardening pass.

No live network call was added or used for this schema-fidelity task. Per the
task instructions, the change is committed locally and is not pushed by this
subtask.
