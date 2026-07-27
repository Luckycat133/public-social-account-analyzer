# Task 3C-C1B1-A implementation report

Baseline: `edc55fb`.

## Scope completed

- High/low analysis now derives eligibility, the `< 15` threshold, group size,
  and median from non-null measurements of the selected main metric. A real
  zero is measured; `null` is excluded. Group size is
  `ceil(measured_count * 20%)`, producing 3/4/4/4 items for 15/16/19/20
  measured posts.
- `performance_meta` now exposes `measured_count` and
  `main_metric_median` for both successful and insufficient results. The
  insufficient reason reports the measured count, not the larger valid-post
  count. These semantics are identical in the pure in-memory path and the
  legacy file-based CLI.
- Equal main-metric values are ordered deterministically by valid 1-based
  `source_rank`, then `post_id`, then canonical platform text for a legal
  cross-platform ID collision. Invalid ranks follow valid ranks. High and low
  groups are disjoint and use positions from the same global ordering.
- Every selected high/low item now has the exact 30-field schema required by
  the analysis contract. It preserves source and collection provenance,
  nullable flags, timestamp precision, hashtags, platform metrics, field
  visibility, duration and content type; `text` is intentionally absent.
- Selected items expose `main_metric` and `relative_to_main_median`, rounded to
  four decimal places. The ratio is `null` when the median is zero or missing.
- `item_url_known=false` suppresses the selected item's `post_url` while
  preserving its verified source/evidence anchor. Structured provenance is
  copied rather than aliased.
- Legacy CSV blanks for `collected_at` are canonicalized to `None`, removing
  the only selected-item discrepancy found by the exact CLI parity test.
- Updated the high/low analysis rules, analysis schema, and changelog. Evidence
  coverage, core insights, pipeline/index behavior, taxonomy, renderer and
  comments remain explicitly outside this subtask.

## TDD evidence

- The first RED run had five expected failures for missing measured metadata
  and the 20-valid/14-measured insufficiency reason. The minimal metadata slice
  then passed all five cases.
- The second RED run had three expected failures (zero-median relative field,
  input-order-dependent ties, and incomplete item schema) while the successful
  metadata case already passed. The completed item/tie slice then passed all
  four cases.
- Exact legacy CLI parity first failed because a blank CSV `collected_at`
  remained `""`; after canonicalization, high, low, and performance metadata
  matched the in-memory output exactly.
- Independent review identified the remaining cross-platform same-ID tie. Its
  forward/reverse regression failed before the platform tie-break and passed
  afterward.
- Tests also lock zero/null distinction, global high/low ranks, disjoint sets,
  invalid-rank ordering, the exact field inventory and values, source-anchor
  retention when item URLs are unknown, and blank legacy timestamps.

## Final verification

- Analysis-focused broad run:
  `python -m pytest tests/test_metrics.py tests/test_normalize.py tests/test_analysis_pipeline.py tests/test_index_snapshot.py tests/test_render_report.py -q`
  -> `192 passed`.
- Final complete offline run with loopback permission:
  `python -m pytest -q` -> `756 passed`.
- The restricted sandbox's preliminary full run reached `753 passed`; its only
  two failures were the known browser-backend tests denied permission to bind
  a temporary `127.0.0.1` port. Both passed in the permitted complete run.
- `PYTHONPYCACHEPREFIX=/tmp/public-social-account-analyzer-c1b1a-pyc python -m compileall -q skill/scripts tests`
  -> passed.
- `python -m json.tool skill/evals/evals.json`, `git diff --check`, and the
  `analyze.py` / `normalize.py` CLI help smoke tests -> passed.
- `pyproject.toml` remains `dependencies = []`; this task adds no runtime or
  network dependency.

## Independent review

APPROVED / CLEAN with no P0, P1, or P2 findings after the cross-platform
tie-break fix. The final reviewer also reported `268` focused cases passing.

No live network call was added or used. The change is committed locally and is
not pushed by this subtask.
