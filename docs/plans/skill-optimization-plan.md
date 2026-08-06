# Skill Optimization Plan: public-social-account-analyzer

## Overview
Optimize the skill following skill-creator best practices:
1. Rewrite SKILL.md for progressive disclosure (target ~150 lines from 280)
2. Consolidate references/ directory structure
3. Clean up scripts/ directory (move legacy, organize)
4. Enhance evals with more behavior cases and trigger optimization
5. Clean up distribution artifacts

## Tasks

### Task 1: Rewrite SKILL.md with progressive disclosure
**Priority**: Highest (biggest token savings, trigger accuracy improvement)

**Requirements:**
- Frontmatter description: Make it "pushy" per skill-creator guide - include specific trigger phrases AND near-miss negative keywords
- Body: ~100-150 lines max (currently 280+)
- Structure: Core decision flow (4 steps) → Platform routing table (references only) → Formal artifact entry points → 5 critical Gotchas → Report template
- Remove: Platform details, workflow details, CLI commands, full schema tables, duplicated content
- All detailed contracts → references/ files with clear "Read when..." pointers

**Acceptance Criteria:**
- SKILL.md ≤ 150 lines
- Frontmatter description includes: trigger phrases + negative keywords (YouTube/Instagram/下载/私信/算法/运营写作/热搜/自动化采集)
- Each section has clear "Read when..." pointer to references/
- No platform-specific implementation details in body
- No full CLI command tables
- Tests pass: `pytest tests/ -q` (should not break anything since only documentation changes)

**Files to modify:** `skill/SKILL.md`

---

### Task 2: Consolidate references/ directory
**Priority**: High (reduce fragmentation, clarify ownership)

**Requirements:**
- Create `references/workflow.md` by merging relevant sections from old `workflow.md` + `SKILL.md` formal artifact sections
- Keep `references/data-contracts/` (6 files from data-schema.md split) - already good
- Keep `references/analysis-contracts/` (3 files from analysis-rules.md split) - already good
- Keep `references/platforms/` (4 files) - already good
- Keep `references/cookie-guide.md`, `exceptions.md`, `douyin-index-evidence.md`
- Move `references/PLATFORM_COMPARISON.md` → `docs/research/PLATFORM_COMPARISON.md` (mark as reference-only, not runtime dependency)
- Move `references/platform-methods/` → `docs/research/platform-methods/` (4 files, research artifacts only)
- Update all cross-references in SKILL.md and other files

**Acceptance Criteria:**
- `references/` only contains files that are loaded at runtime by the skill
- `docs/research/` contains research/background documents
- All internal references updated (no broken links)
- No duplicate content between SKILL.md and references/
- Tests pass

**Files to modify:** Multiple references files, SKILL.md cross-references

---

### Task 3: Clean up scripts/ directory
**Priority**: Medium (engineering hygiene)

**Requirements:**
- Create `scripts/legacy/` directory
- Move `normalize.py`, `analyze.py`, `render_report.py` → `scripts/legacy/`
- Update `scripts/README.md` to mark legacy scripts clearly
- Keep all other scripts in current location (structure is good)
- Verify imports still work (legacy scripts may be imported by tests)

**Acceptance Criteria:**
- Legacy scripts in `scripts/legacy/`
- `scripts/README.md` updated
- All tests pass (`pytest tests/ -q`)
- No broken imports

**Files to modify:** `scripts/` directory structure, `scripts/README.md`

---

### Task 4: Enhance evals with behavior cases and trigger optimization
**Priority**: Medium (long-term quality)

**Requirements:**
- Add 5-8 new behavior cases to `skill/evals/datasets/source/behavior_cases.jsonl`:
  1. Multi-account comparison (cross-platform or same platform)
  2. Period-over-period comparison (e.g., "this month vs last month")
  3. Comment insights request with actual comment data
  4. User-provided CSV with missing/partial fields
  5. Cross-platform sample window alignment
  6. Evidence-only delivery request (0 valid posts)
  7. Strategy delivery with partial taxonomy (29/30 valid)
- Create description trigger optimization datasets:
  - `skill/evals/description_train.json` (60% of trigger evals)
  - `skill/evals/description_validation.json` (40% held-out)
- Run trigger optimization loop (using skill-creator's `run_loop.py`)

**Acceptance Criteria:**
- New behavior cases added with proper IDs, assertions
- Description train/validation sets created (20+ queries each, mixed should/should-not)
- Trigger optimization run completes
- Updated SKILL.md frontmatter description with optimized version
- Tests pass

**Files to modify:** `skill/evals/datasets/source/behavior_cases.jsonl`, new description eval files

---

### Task 5: Clean distribution artifacts
**Priority**: Low (housekeeping)

**Requirements:**
- Remove `skill/evals-workspace/` (old eval snapshots)
- Remove `skill/workspace/bili_946974_test_v1/` (test artifacts)
- Update `docs/guides/deployment-package-checklist.md` to reflect new structure
- Verify `.gitignore` covers new legacy directory

**Acceptance Criteria:**
- Artifacts removed
- Deployment checklist updated
- `git status` clean except for intended changes
- Tests pass

**Files to modify:** Directory cleanup, `docs/guides/deployment-package-checklist.md`, `.gitignore`

---

## Dependencies
- Task 1 (SKILL.md) must complete before Task 2 (references) since cross-references need updating
- Task 2 and 3 can run in parallel after Task 1
- Task 4 can start after Task 1 (new SKIL.md description needed for trigger evals)
- Task 5 can run anytime

## Test Command
After each task: `python3 -m pytest tests/ -q` (must pass 1678 tests)

## Definition of Done
All 5 tasks complete, all tests pass, skill triggers correctly on eval queries.