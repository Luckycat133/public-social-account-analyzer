# Task 3C-B implementation report

Baseline: `8896f08`.

## Scope completed

- Added `run_pipeline.py` with the fixed
  `VERIFY_COLLECTION -> NORMALIZE -> ANALYZE -> RENDER -> VALIDATE -> RESERVE -> SERIALIZE_CREATE_ONLY -> COMMIT`
  sequence. All derived work and validation happen in memory before output
  reservation; publication uses one create-only immutable workspace commit.
- Added explicit required and optional analysis inventories, including binary
  create-only writes. The pipeline ignores a collection's compatibility CSV and
  rebuilds normalization from the verified `source/posts.jsonl` bytes.
- Added an identity-bound collection reader. It retains directory and artifact
  handles, rechecks exact inventory, identities, metadata, sizes, and SHA-256,
  and requires every read to report the same immutable source format and commit
  digest. It never reopens a collection artifact by pathname after validation.
- The Windows reader now obtains directory inventory through
  `GetFileInformationByHandleEx` on held handles, uses restart/continue paging,
  fails closed on nonterminal errors, and requests `FILE_LIST_DIRECTORY` access.
- Extracted pure in-memory normalize, analyze, and render interfaces. Legacy
  stage CLIs remain available only for unsealed legacy directories and reject
  any input or output containing `manifest.json` or `.complete`.
- Renderer diagnostics are call-local. Missing inputs, section exceptions, bad
  links, external images, invalid template inventories, and empty outputs are
  fatal. Allowlisted template slots are replaced in one pass, so public account
  text containing `{{...}}` cannot be interpreted as template syntax.
- Added optional `--classification-results FILE`. It accepts only strict UTF-8
  JSON with exactly one complete typed taxonomy record for every analyzed
  parent `post_id`; duplicates, omissions, extra parents, unknown fields,
  invalid enums/types, non-finite confidence, and out-of-range confidence fail
  before reservation. Valid source bytes are preserved exactly as
  `source/classification-results.json` and allow semantic analysis to become
  `COMPLETED`.
- Lifecycle state is consistent across `task.json`, `analysis.json`, Markdown,
  HTML, and `pipeline-report.md`. `.complete` expresses durable publication;
  only complete upstream input, lossless normalization, complete semantic
  classification, and successful render validation produce business status
  `COMPLETED`. Valid limited or pending-classification work is committed as
  `PARTIAL` with explicit reasons.
- Updated README, usage, Skill, schema, exceptions, Douyin evidence/platform,
  and changelog documentation for the separate immutable analysis workspace,
  classification input, zero-row behavior, and status semantics.

## TDD evidence

- Initial pipeline contracts: 10 failing tests before implementation, then 10
  passing tests for binary create-only writes, verified reads, collection
  immutability, pure phases, fatal rendering, inventory, and lifecycle.
- Expanded pipeline contracts: 14 failing tests before implementation, then 14
  passing tests for preflight failure behavior, optional evidence, legacy CLI
  refusal, render diagnostics, and exact commit behavior.
- Independent review fixes were each reproduced with focused RED tests before
  implementation: Windows native/POSIX identity mismatch; legacy renderer
  fail-open state; derived-status divergence; Windows pathname reopening;
  renderer process-global state; and incomplete template inventory.
- Final security/completeness wave started with 10 expected failures covering
  held-handle Windows inventory, native directory parsing, single-pass template
  substitution, complete classification publication, invalid classification
  rejection, and CLI wiring. All 10 passed after implementation.
- Added native Windows restart/continue pagination and nonterminal-error tests;
  both passed. A final `FILE_LIST_DIRECTORY` access test failed before the access
  mask fix and passed afterward. The specialist review's defensive parser
  boundary candidate was then reproduced as RED; rejecting a file name that
  crosses its native record boundary made it GREEN.

## Final verification

- Focused immutable-analysis regression:
  `python3 -m pytest -q tests/test_analysis_pipeline.py tests/test_immutable_workspace.py tests/test_normalize.py tests/test_render_report.py tests/test_index_snapshot.py`
  -> `157 passed in 0.55s` after the final parser hardening.
- Full restricted-sandbox run -> `681 passed`, with only two expected
  `127.0.0.1` bind permission failures in browser-backend tests.
- Final independent full run with loopback permission after parser hardening:
  `python3 -m pytest -q` -> `684 passed in 4.49s`.
- `PYTHONPYCACHEPREFIX=/private/tmp/task3cb-pycache python3 -m compileall -q skill/scripts tests`
  -> passed.
- `git diff --check` -> passed.
- `skill/evals/evals.json` parsed successfully.
- `python3 skill/scripts/run_pipeline.py --help` -> passed and exposes
  `--classification-results`.
- `pyproject.toml` remains `dependencies = []`; new runtime code uses only the
  Python standard library and existing project modules.

## Independent review

APPROVED with no P0/P1/P2 findings. The reviewer independently exercised the
focused and full suites, compilation, diff checks, lifecycle/status alignment,
classification completeness, render failure behavior, and the held-handle
Windows enumeration contract. The native-enumeration specialist's only parser
hardening observation was converted into the final RED/GREEN test above.

Residual platform validation is limited to the absence of a Windows host in
this macOS environment. The Win32 ABI and paging contract are covered with
standard-library fakes, but a future Windows CI smoke run should exercise
NTFS/ReFS/SMB and real ACL behavior.

No live network call was added or used. Per the task brief, this task is
committed locally and is not pushed.
