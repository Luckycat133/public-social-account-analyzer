# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Table of contents

- [1. Project shape](#1-project-shape)
- [2. Build, test, and common commands](#2-build-test-and-common-commands)
- [3. Pipeline architecture (the big picture)](#3-pipeline-architecture-the-big-picture)
- [4. Key modules and contracts](#4-key-modules-and-contracts)
- [5. Deployment + drift detection](#5-deployment--drift-detection)
- [6. Acceptance evidence (PRD AC-01…AC-10)](#6-acceptance-evidence-prd-ac-01ac-10)
- [7. Coding conventions](#7-coding-conventions)
- [8. Commit conventions](#8-commit-conventions)
- [9. Useful pointers](#9-useful-pointers)

## 1. Project shape

Public social-account content analyzer. Two-tier layout:

- **Repo root** — developer-facing: `README.md`, `USAGE.md`, `tests/`, `docs/`, `workspace/`.
- **`skill/`** — Agent-Skills-spec deliverable: `SKILL.md` (Agent contract), `scripts/` (Python), `references/` (domain rules), `assets/`, `evals/`.

Project runs on **Python 3.9+ stdlib only** (no third-party runtime imports). Tests need `pytest`. Production code never calls an LLM; the Agent executes classification/business-insight steps through external JSON files.

If `.agents/skills/`, `.claude/skills/`, or `.workbuddy/skills/` exist in the repo, they are deployment-time symlinks — see [docs/guides/deployment-package-checklist.md](docs/guides/deployment-package-checklist.md) and §5 below.

---

## 2. Build, test, and common commands

```bash
# setup
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e ".[dev]"

# full regression
python3 -m pytest tests/ -q

# focused / single tests
python3 -m pytest tests/test_douyin.py -q
python3 -m pytest tests/test_douyin.py::test_collect_post_list -q
python3 -m pytest tests/test_business_insights.py -q -k classification

# dataset integrity
python3 tools/skill_eval/split_dataset.py --verify

# local smoke (real network required, public pages only)
python3 skill/scripts/collect.py "https://space.bilibili.com/123456" --limit 5 --out workspace/smoke
```

There is no compile step, no formatter, no linter. Match existing 4-space indentation and run `git diff --check` before commits.

---

## 3. Pipeline architecture (the big picture)

```text
                ┌────────────────────────────────────────────────────────┐
                │  collect.py / collect_douyin_authorized.py /           │
                │  import_index_snapshot.py                              │
                │   ↓                                                   │
                │  collectors/<platform>.py  (BaseCollector contract)   │
                └────────────────────────────────────────────────────────┘
                                  │  immutable collection workspace
                                  │  (source/profile.json, source/posts.jsonl,
                                  │   task.json, manifest.json, .complete)
                                  ▼
                ┌────────────────────────────────────────────────────────┐
                │  run_pipeline.py  (preferred entry, no network)        │
                │   - VerifiedWorkspaceReader  ←  immutable_workspace.py │
                │   - normalize (in-memory)                              │
                │   - analyze + taxonomy-draft / business-insight-draft  │
                │   - render_report (Markdown + HTML)                    │
                │   - ImmutableWorkspace.reserve/commit  (create-only)   │
                └────────────────────────────────────────────────────────┘
                                  │  independent analysis workspace
                                  │  (normalized-posts.csv, analysis.json,
                                  │   account-analysis-report.md, dashboard.html)
                                  ▼
                ┌────────────────────────────────────────────────────────┐
                │  Agent (external) writes:                              │
                │   source/classification-results.json                   │
                │   source/business-insight-results.json                 │
                │  Both bounded by digest, validated, then re-sealed.    │
                └────────────────────────────────────────────────────────┘
```

Key invariants:

- **Two-phase model workflow** for content-strategy goals: `--with-llm-tax` → write `taxonomy-results.json` outside the workspace → `--classification-results` (validated, sealed by digest) → `--with-business-insights` → write `business-insight-results.json` → `--business-insight-results`.
- **Collection and analysis are independent create-only commits.** `--input` collection must be a sealed workspace; `--output` analysis must not exist. Failure never overwrites or deletes.
- **Legacy scripts `normalize.py`, `analyze.py`, `render_report.py`** explicitly reject sealed immutable workspaces. Use `run_pipeline.py` for new work.
- **Resume** (`--resume --out`) only accepts the same platform + canonical URL whose `.complete` and `manifest.json` pass `verify_committed_workspace`.

---

## 4. Key modules and contracts

| Module | Purpose |
|---|---|
| `skill/scripts/collect.py` | CLI router; picks adapter and writes a collection workspace. Supports explicit limits/date windows, B站/抖音 bounded-complete mode, resume/checkpoint, platform Cookie files, opt-in private persistence and cache revocation. |
| `skill/scripts/run_pipeline.py` | One-shot normalize+analyze+render. Supports evidence-only, taxonomy, business, comment and strict delivery-ready gates. |
| `skill/scripts/collect_douyin_authorized.py` | Authorized OpenAPI path; requires `DOUYIN_OPENAPI_OPEN_ID` + `DOUYIN_OPENAPI_ACCESS_TOKEN` env (token must not enter URLs/logs/artifacts). |
| `skill/scripts/import_index_snapshot.py` | Imports Web-index evidence (官方精选 / 主页搜索索引) into a `PARTIAL` workspace when direct collection had blocked. |
| `skill/scripts/csv_contract.py` | CSV field schema; cell-level type/effective checks. |
| `skill/scripts/execution_timing.py` | `started_at` / `ended_at` / `duration_ms` / `phase_durations_ms` for `task.json`. |
| `skill/scripts/immutable_workspace.py` | `ImmutableWorkspace` (create-only writer), `VerifiedWorkspaceReader` (identity-bound reader), `verify_committed_workspace`, `read_resume_artifact`. Uses POSIX dir-fd chain + Windows `FILE_ID_BOTH_DIR_INFO`; same call may be re-issued under either. |
| `skill/scripts/task_contract.py` | Single source of truth for `TASK_STATUSES`, `STOP_REASONS`, `LABEL_MISSING="null"`, `LABEL_UNKNOWN="INVALID"`, `ANALYZABLE_TASK_STATUSES`, `safe_*_label`, `validate_analysis_goal`, `new_task_id`. **Always import from here; do not redeclare.** |
| `skill/scripts/collectors/base.py` | `BaseCollector` ABC: `supports`, `check_access`, `collect_profile`, `collect_post_list`, `collect_post_detail`, `collect_comments`, `get_collection_coverage`, `normalize_profile`, `normalize_post`. `_canon_status_with_source` makes missing/invalid `collection_status` → `PARTIAL` (never invented success). |
| `skill/scripts/collectors/_constants.py` | `STOP_*` single-string constants used by adapters. |
| `skill/scripts/collectors/bilibili.py` | Bilibili adapter: `medialist` with WBI `arc/search` fallback; platform-protection responses abort the current task. |
| `skill/scripts/collectors/douyin.py` | Douyin public adapter: SSR variants + `--all` bounded scrolling + optional browser fallback. |
| `skill/scripts/collectors/douyin_openapi.py` | Douyin OpenAPI adapter (post-OAuth). |
| `skill/scripts/collectors/weibo.py` | Weibo adapter, env-gated (`WEIBO_COLLECTOR_ENABLED`). |
| `skill/scripts/collectors/xiaohongshu.py` | Xiaohongshu adapter for account-bound legacy/modern embedded profile state and partial public cards. |
| `skill/scripts/collectors/cookie_loader.py` / `_cookie_storage.py` | Platform-isolated Cookie validation plus opt-in atomic `0600` cache storage and revocation. |
| `skill/scripts/collectors/browser_backend.py` | Headless browser transport — only used by fallback path; never persists cookies/headers/bodies. |
| `skill/scripts/collectors/url_policy.py` | URL allowlist / canonicalization. |
| `skill/scripts/collectors/_douyin_browser_transport.py` / `_douyin_detail_contract.py` | Internal helpers for browser fallback and detail contract. |

`skill/references/` holds the per-platform and per-feature rules that `BaseCollector` consumers must satisfy:

- `data-schema.md` — router for artifact, collection and analysis schemas.
- `analysis-rules.md` — router for metrics/sampling, model insights and comment insights.
- `exceptions.md` — `stop_reason` ↔ adapter mapping.
- `platforms/` — per-platform constraints.
- `douyin-index-evidence.md` — Web-index import contract.

Behavior and security policy is defined by `skill/SKILL.md` plus these focused references. Preserve account binding, nullable evidence, protection-stop semantics, credential isolation and immutable output boundaries when changing code; do not duplicate those contracts in this contributor guide.

---

## 5. Deployment + drift detection

Three known deployment surfaces:

```text
~/.agents/skills/public-social-account-analyzer  →  dev skill/   (symlink, P0)
~/.claude/skills/public-social-account-analyzer  →  ~/.agents/... (symlink, P0)
~/.workbuddy/skills/public-social-account-analyzer  (real dir snapshot, P1)
```

`docs/guides/deployment-package-checklist.md` is the canonical drift checklist. Run it before any release:

1. Path-chain integrity (`readlink` + `find`).
2. Key-module existence (`run_pipeline.py`, `execution_timing.py`, `tests/manual_accuracy_check.py`, `references/douyin-index-evidence.md`, `evals/evals.json`).
3. CLI flag parity (`collect.py --all|--enrich-details|--no-browser-fallback`, `run_pipeline.py --with-llm-tax|--classification-results|--with-business-insights|--business-insight-results`).
4. Full `pytest tests/ -q` green.

If deploying via symlink, drift is automatic — the checklist still verifies the entry surface.

---

## 6. Acceptance evidence (PRD AC-01…AC-10)

- **AC-01 / AC-02** are demonstrated by `workspace/<platform>-<id>-<date>/` directories with valid `.complete` and `manifest.json`.
- **AC-03 / AC-06** use `tests/manual_accuracy_check.py prepare` + `verify` subcommands. Both must be bound to two immutable commits (collection + analysis). Source↔CSV self-consistency is **not** a human-truth substitute.
- **AC-10** uses `docs/guides/operations-trial-template.md` (real operations trial + at least one feedback-driven merged commit).

Do not mark any AC PASS with placeholder evidence or duplicate IDs.

---

## 7. Coding conventions

- 4-space indent, `snake_case` functions/vars/modules, `PascalCase` classes, `UPPER_SNAKE_CASE` constants, leading underscore for private helpers.
- Type hints on public interfaces; short docstrings stating the behavioral contract.
- One-way dependency flow: entry scripts → adapters → shared helpers (`base.py`, `_constants.py`, `_utils.py`). Adapters import `browser_backend` only when fallback is enabled.
- Mock platform transport in tests; do not make live network success a unit-test requirement.
- New collected paths must be added to `ANALYSIS_REQUIRED_ARTIFACTS` / `ANALYSIS_OPTIONAL_ARTIFACTS` in `immutable_workspace.py` and to `docs/guides/deployment-package-checklist.md` §1.

---

## 8. Commit conventions

History uses Conventional Commits with scopes:

```text
feat(analysis): ...
fix(douyin): ...
docs: ...
refactor: ...
test: ...
chore: ...
```

- Keep commits focused; never bundle a behavior change with unrelated refactors.
- Update `CHANGELOG.md` (Keep a Changelog v1.1.0) under both `### Added` / `### Changed` / `### Fixed` / `### Security` simultaneously — entries go in `[Unreleased]` until release.
- Bump by behavior, not by line count. Run the drift checklist before tagging.
- Never commit OAuth tokens, signed URLs, raw private data, or generated `workspace/` payloads.

---

## 9. Useful pointers

- PRD: `docs/prd/公开社交媒体账号内容分析Skill-产品需求文档-V1.0.docx`
- PRD ↔ implementation matrix: `docs/prd/需求实现状态与抖音能力边界.md`
- Architecture: `docs/architecture/STRUCTURE.md`
- Operations guide: `USAGE.md`
- Skill Agent contract: `skill/SKILL.md`
- PRD acceptance plan: `docs/guides/prd-v1.0-acceptance-test-plan.md`
