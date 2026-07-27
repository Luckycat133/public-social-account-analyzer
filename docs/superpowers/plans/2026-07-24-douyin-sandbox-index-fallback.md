# Douyin Sandbox Index Fallback Implementation Plan

**Goal:** Add a zero-runtime-dependency, no-login Web-index evidence importer that produces honest partial Douyin workspaces when direct SSR/CDP collection is blocked.

**Architecture:** The Skill uses the environment's Web connector, where the Agent verifies the public source and item-region ownership. A deterministic standard-library script validates evidence shape, official hosts, ID/URL relationships, and field consistency, writes the existing source/task artifacts, and hands off to normalization, analysis, and report scripts.

**Tech stack:** Python 3.9+ standard library, pytest (development only), Markdown.

## Task 1: Evidence contract and importer (TDD)

**Files:**

- Create `tests/test_index_snapshot.py`
- Create `skill/scripts/import_index_snapshot.py`
- Modify `skill/references/data-schema.md`

1. Write failing tests for selected-source import, search-index local keys, author/source/URL rejection,
   numeric and time validation, non-overwrite behavior, status fields, and deterministic output.
2. Run the focused test file and capture the expected RED result.
3. Implement the smallest standard-library validator, transformer, atomic-ish workspace writer, and CLI.
4. Run the focused tests until green, then run normalization integration tests.

## Task 2: Skill orchestration and documentation

**Files:**

- Create `skill/references/douyin-index-evidence.md`
- Modify `skill/SKILL.md`
- Modify `skill/references/platform-douyin.md`
- Modify `README.md`, `USAGE.md`, `CHANGELOG.md`
- Modify relevant Skill eval cases

1. Document the exact fallback trigger, Web query/open procedure, evidence JSON contract, Agent source/identity checks and importer consistency checks,
   output commands, and the difference between selected-page and search-index evidence.
2. Explicitly prohibit generic recommendations, title-only author guesses, fabricated IDs/URLs, and claims of
   real-time completeness.
3. Add a Skill eval covering blocked direct collection followed by a validated partial index import.

## Task 3: Offline and live acceptance

**Files:**

- Create or update `docs/observations/douyin-sandbox-index-acceptance.md`
- Generate ignored task outputs under `workspace/`

1. Run `import -> normalize -> analyze -> render_report` on deterministic fixture evidence.
2. Obtain fresh public evidence for “大漠叔叔” and “中国政府网” without a Douyin login.
3. Import both, inspect sampled records and reports, and verify exact identity, provenance, missing-field honesty,
   `PARTIAL` state, and absence of sensitive data.
4. Run full pytest, Python compilation, `git diff --check`, runtime-dependency check, and Skill validation.
5. Review the final diff and record limitations before committing.
