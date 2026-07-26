# Task 3C-A implementation report

Baseline: `6800c5a210f161d3e0dae34e8d486d3f5e406725`

## Scope completed

- Bilibili platform-protection responses now trip a task-session circuit breaker.
  Login, verification, rate-limit, WAF, and access-restriction responses are not
  retried, do not rotate `buvid`, do not switch endpoints, and do not invoke a
  browser fallback.
- Pure local curl transport failures retry at most once with the same identity.
- `finger/spi` initialization is single-shot and non-recursive; `discover_arc`
  retains its identity across pages.
- Added standard-library-only `task_contract.py`. Public, authorized OpenAPI,
  and Web-index CLIs validate and persist `analysis_goal` and a unique nonempty
  `task_id`.
- Douyin default directories use the first 12 hexadecimal characters of the
  canonical `sec_uid` SHA-256. Bilibili default directories retain their UID.
- Web-index imports now use `ImmutableWorkspace` create-only reservation,
  allowlisted artifact writes, deterministic `manifest.json`, and `.complete`.
  Existing empty targets and symlink ancestors fail closed. Imported snapshots
  remain `PARTIAL` and explicitly non-exhaustive.

## TDD evidence

- Bilibili RED: 9 tests failed before implementation; GREEN: 9 passed.
- Final-review Bilibili RED: 2 cross-method policy tests failed; GREEN: 2 passed.
- Task/index RED: 14 selected tests failed before implementation; GREEN: 14 passed.
- Grouped public/authorized/index regression: 189 passed.
- Exact directory/task identity regression: 3 passed.
- Full suite after final review fixes: 613 passed.
- The sandbox-only full run produced 609 passed and two `127.0.0.1` bind
  permission failures; both passed when rerun with loopback permission.

## Verification

- `PYTHONPYCACHEPREFIX=/private/tmp/task3ca-pycache python3 -m compileall -q skill/scripts tests`
- `git diff --check`
- `python3 -m json.tool skill/evals/evals.json`
- `pyproject.toml` still declares `dependencies = []`; all new runtime imports
  are from the Python standard library or existing project modules.

No remote is configured, so this task is committed locally and not pushed.
