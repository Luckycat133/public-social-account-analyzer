---
name: social-media-analysis
description: Social-media account content analysis pipeline for public-social-account-analyzer. Use for platform adapters (Bilibili/Douyin/Weibo/Xiaohongshu), content classification, business insights, taxonomy drafts, and immutable analysis workspaces.
---

# Social Media Analysis Skill

Scope: `skill/scripts/collectors/` (bilibili.py, douyin.py, douyin_openapi.py, weibo.py, xiaohongshu.py, base.py), `skill/scripts/run_pipeline.py`, `skill/references/` (analysis-rules.md, platforms/, exceptions.md, etc.), `skill/evals/`, and `tools/skill_eval/`.

## Invariants

- Two-tier layout: repo root (developer-facing) + `skill/` (Agent-Skills-spec deliverable: `SKILL.md`, `scripts/`, `references/`, `assets/`, `evals/`).
- Production code never calls an LLM; the Agent executes classification/business-insight steps through external JSON files (`source/classification-results.json`, `source/business-insight-results.json`).
- Two-phase model workflow: `--with-llm-tax` → write `taxonomy-results.json` outside workspace → `--classification-results` (validated, sealed by digest) → `--with-business-insights` → write `business-insight-results.json`.
- Collection and analysis are independent create-only commits: `--input` collection must be a sealed workspace; `--output` analysis must not exist. Failure never overwrites or deletes.
- Resume (`--resume --out`) only accepts the same platform + canonical URL whose `.complete` and `manifest.json` pass `verify_committed_workspace`.
- `BaseCollector` ABC: `supports`, `check_access`, `collect_profile`, `collect_post_list`, `collect_post_detail`, `collect_comments`, `get_collection_coverage`, `normalize_profile`, `normalize_post`.
- Platform-specific constraints in `skill/references/platforms/`; per-platform adapters under `skill/scripts/collectors/`.

## When to use

- Adding or editing platform adapters (Bilibili/Douyin/Weibo/Xiaohongshu).
- Changing collection pipeline (`collect.py`, `collect_douyin_authorized.py`, `import_index_snapshot.py`).
- Touching analysis pipeline (`run_pipeline.py`, `immutable_workspace.py`, `task_contract.py`).
- Modifying `skill/references/` domain rules or `skill/evals/` evaluation data.

## Verification

- `python3 -m pytest tests/ -q` full regression.
- Local smoke (real network, public pages only): `python3 skill/scripts/collect.py <url> --limit 5 --out workspace/smoke`.
- Dataset integrity: `python3 tools/skill_eval/split_dataset.py --verify`.
- `git diff --check` before commit.
