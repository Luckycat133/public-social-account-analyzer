# AGENTS.md — Public Social Account Analyzer

## Project Shape & Runtime Boundary

Two-tier layout: repo root (`README.md`, `USAGE.md`, `tests/`, `docs/`, `workspace/` runtime output) + Agent-Skills deliverable under `skill/` (`SKILL.md`, `scripts/`, `references/`, `assets/`, `evals/`).
- **Zero external runtime dependencies**: production code uses **Python 3.9+ stdlib only** (`pytest` is dev-only). Production scripts never call an LLM; classification/business-insight JSON is supplied externally and sealed by digest.

## Verification & Smoke Commands

```bash
python3 -m pytest tests/ -q                          # full regression (must be 100% green before commit)
python3 -m pytest tests/test_douyin.py -q            # focused module test
python3 tools/skill_eval/split_dataset.py --verify   # eval dataset split contract
git diff --check
# real-network public smoke only (normalize/analyze/render stay 100% offline & deterministic):
python3 skill/scripts/collect.py "https://space.bilibili.com/123456" --limit 5 --out workspace/smoke
```

## Hard Invariants (Why + Counterfactual)

- **Single source of truth for task constants**: Always import `TASK_STATUSES`, `STOP_REASONS`, `LABEL_MISSING`, `LABEL_UNKNOWN`, `ANALYZABLE_TASK_STATUSES`, `safe_*_label`, `validate_analysis_goal`, `new_task_id` from `skill/scripts/task_contract.py`—redeclaring them causes silent status/stop-reason drift across adapters and reports.
- **Create-only immutable workspaces**: Collection (`collect.py`) and analysis (`run_pipeline.py`) are independent create-only commits (`--input` must be a sealed workspace; `--output` must not exist) so failed runs never overwrite or corrupt prior evidence. Legacy `normalize.py`/`analyze.py`/`render_report.py` intentionally reject sealed workspaces—use `run_pipeline.py`.
- **Two-phase model workflow**: `--with-llm-tax` → write `taxonomy-results.json` outside workspace → `--classification-results` (digest-verified & sealed) → `--with-business-insights` → write `business-insight-results.json` → `--business-insight-results`. Resume (`--resume --out`) requires matching platform + canonical URL passing `verify_committed_workspace`.
- **No fabricated success & strict credential isolation**: Missing/invalid `collection_status` degrades to `PARTIAL`; unit tests must mock network transport (never depend on live network). Never log or leak `DOUYIN_OPENAPI_ACCESS_TOKEN`, cookies, signed URLs, private raw data, or generated `workspace/` payloads; `browser_backend.py` is fallback-only and never persists cookies/headers/bodies.
- **New artifact registration**: Any new collected artifact path must be added to both `ANALYSIS_REQUIRED_ARTIFACTS`/`ANALYSIS_OPTIONAL_ARTIFACTS` in `skill/scripts/immutable_workspace.py` and `docs/guides/deployment-package-checklist.md` §1, otherwise strict delivery validation will reject it.

## Coding, Acceptance & Deployment Drift

- **Dependency direction**: `entry scripts → collectors/* → shared helpers (base.py, _constants.py, _utils.py)`; 4-space indent, type hints on public interfaces, Conventional Commits (`feat(scope): ...`).
- **PRD AC-01…AC-10 evidence**: AC-01/AC-02 require real sealed `workspace/<platform>-<id>-<date>/` (`.complete` + `manifest.json`); AC-03/AC-06 require `tests/manual_accuracy_check.py prepare|verify` bound to two immutable commits (source↔CSV self-consistency is NOT human truth); AC-10 uses `docs/guides/operations-trial-template.md`. Never mark AC PASS with placeholders.
- **Pre-release drift check**: Run [docs/guides/deployment-package-checklist.md](docs/guides/deployment-package-checklist.md) verifying symlink/snapshot surfaces (`~/.agents/skills/`, `~/.claude/skills/`, `~/.workbuddy/skills/`), CLI flag parity, and full `pytest`.

## 1-Hop Pointers

- Architecture & full module map: [docs/architecture/STRUCTURE.md](docs/architecture/STRUCTURE.md)
- Agent Skill contract & per-platform rules: [skill/SKILL.md](skill/SKILL.md), `skill/references/` (`data-schema.md`, `analysis-rules.md`, `exceptions.md`, `platforms/`, `douyin-index-evidence.md`)
- Operations & acceptance plans: [USAGE.md](USAGE.md), [docs/prd/需求实现状态与抖音能力边界.md](docs/prd/需求实现状态与抖音能力边界.md), [docs/guides/prd-v1.0-acceptance-test-plan.md](docs/guides/prd-v1.0-acceptance-test-plan.md)
