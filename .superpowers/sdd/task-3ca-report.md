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
- Bilibili profile, list, detail, tags, dynamics, and comments share the same
  task Session. Comment aid resolution and reply retrieval no longer bypass it
  through `urllib`; protection reasons remain exact and stop comment traversal.
- Local missing structures use `PARSER_FAILED`, and an explicitly empty
  three-endpoint result uses `NO_PUBLIC_CONTENT`; neither falsely opens the
  platform-protection circuit.
- A later comment-endpoint platform-protection reason now dominates an earlier
  non-protection stop reason at task level. The earlier error remains in the
  report, while an already-recorded protection reason remains stable.
- Non-JSON Bilibili responses open the protection circuit only when their body
  contains explicit login, verification, WAF, rate-limit, or access-denial
  evidence. Other malformed bodies are `PARSER_FAILED`; the comment layer
  sanitizes those to content-level `COMMENTS_UNAVAILABLE`.
- Added standard-library-only `task_contract.py`. Public, authorized OpenAPI,
  and Web-index CLIs validate and persist `analysis_goal` and a unique nonempty
  `task_id`.
- Douyin default directories use the first 12 hexadecimal characters of the
  canonical `sec_uid` SHA-256. Bilibili default directories retain their UID.
- Web-index imports now use `ImmutableWorkspace` create-only reservation,
  allowlisted artifact writes, deterministic `manifest.json`, and `.complete`.
  Existing empty targets and symlink ancestors fail closed. Imported snapshots
  remain `PARTIAL` and explicitly non-exhaustive.
- README, Skill instructions, and the Bilibili, Douyin, and exception references
  now agree that browser switches affect Douyin only. Bilibili platform
  protection stops the shared task session without identity rotation, endpoint
  switching, or browser fallback; ordinary comment unavailability remains a
  content-level reason.

## TDD evidence

- Bilibili RED: 9 tests failed before implementation; GREEN: 9 passed.
- Final-review Bilibili RED: 2 cross-method policy tests failed; GREEN: 2 passed.
- Independent-review RED: 8 session/comment/error/docs tests failed; GREEN: 8 passed.
- Public comment-orchestration RED: 1 protection-reason test failed; GREEN: 1 passed.
- Final lifecycle/docs RED: 8 cases failed (6 reason-order cases, 1 orchestration
  case, and 1 authoritative-doc contract); GREEN: 8 passed.
- Final non-JSON classification RED: 2 failures with 6 protection controls
  already passing; GREEN: all 8 cases passed.
- English verification-page RED: the 2 explicit `captcha required` /
  `verification required` cases failed while 2 ordinary-text controls passed;
  GREEN: all 4 cases passed and the protection cases trip the circuit.
- Task/index RED: 14 selected tests failed before implementation; GREEN: 14 passed.
- Grouped public/authorized/index regression: 189 passed.
- Exact directory/task identity regression: 3 passed.
- Final focused Bilibili/public orchestration regression: 228 passed.
- Final full suite after lifecycle, documentation, and classification fixes:
  638 passed.
- Earlier full suite after the first independent-review fixes: 622 passed.
- The sandbox-only full run produced 609 passed and two `127.0.0.1` bind
  permission failures; both passed when rerun with loopback permission.

## Verification

- `PYTHONPYCACHEPREFIX=/private/tmp/task3ca-pycache python3 -m compileall -q skill/scripts tests`
- `git diff --check`
- `python3 -m json.tool skill/evals/evals.json`
- `pyproject.toml` still declares `dependencies = []`; all new runtime imports
  are from the Python standard library or existing project modules.

No remote is configured, so this task is committed locally and not pushed.
