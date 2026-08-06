# Migration Plan: Research Output & PRD Source → Skill Project

**Generated:** 2026-08-05  
**Source Root:** `/Users/jack/Documents/public-social-account-analyzer-workspace/`  
**Target Root:** `/Users/jack/Documents/public-social-account-analyzer/skill/`

---

## 1. File-by-File Mapping Table

### 1.1 Platform Methods — Merge 5 Research Sites → Per-Platform Target

| Source File | Source Dir | Target File | Target Dir | Action |
|-------------|------------|-------------|------------|--------|
| `xiaohongshu.md` | `research-output/github/` | `xiaohongshu.md` | `docs/research/platform-methods/` | **Merge** (primary) |
| `xiaohongshu.md` | `research-output/clawhub/` | `xiaohongshu.md` | `docs/research/platform-methods/` | **Merge** |
| `xiaohongshu.md` | `research-output/glama/` | `xiaohongshu.md` | `docs/research/platform-methods/` | **Merge** |
| `xiaohongshu.md` | `research-output/npm/` | `xiaohongshu.md` | `docs/research/platform-methods/` | **Merge** |
| `xiaohongshu.md` | `research-output/pypi/` | `xiaohongshu.md` | `docs/research/platform-methods/` | **Merge** |
| `douyin.md` | `research-output/github/` | `douyin.md` | `docs/research/platform-methods/` | **Merge** (primary) |
| `douyin.md` | `research-output/clawhub/` | `douyin.md` | `docs/research/platform-methods/` | **Merge** |
| `douyin.md` | `research-output/glama/` | `douyin.md` | `docs/research/platform-methods/` | **Merge** |
| `douyin.md` | `research-output/npm/` | `douyin.md` | `docs/research/platform-methods/` | **Merge** |
| `douyin.md` | `research-output/pypi/` | `douyin.md` | `docs/research/platform-methods/` | **Merge** |
| `bilibili.md` | `research-output/github/` | `bilibili.md` | `docs/research/platform-methods/` | **Merge** (primary) |
| `bilibili.md` | `research-output/clawhub/` | `bilibili.md` | `docs/research/platform-methods/` | **Merge** |
| `bilibili.md` | `research-output/glama/` | `bilibili.md` | `docs/research/platform-methods/` | **Merge** |
| `bilibili.md` | `research-output/npm/` | `bilibili.md` | `docs/research/platform-methods/` | **Merge** |
| `bilibili.md` | `research-output/pypi/` | `bilibili.md` | `docs/research/platform-methods/` | **Merge** |
| `weibo.md` | `research-output/github/` | `weibo.md` | `docs/research/platform-methods/` | **Merge** (primary) |
| `weibo.md` | `research-output/clawhub/` | `weibo.md` | `docs/research/platform-methods/` | **Merge** |
| `weibo.md` | `research-output/glama/` | `weibo.md` | `docs/research/platform-methods/` | **Merge** |
| `weibo.md` | `research-output/npm/` | `weibo.md` | `docs/research/platform-methods/` | **Merge** |
| `weibo.md` | `research-output/pypi/` | `weibo.md` | `docs/research/platform-methods/` | **Merge** |

> **Note:** `research-output/glama/` is missing `xiaohongshu.md` — this is expected (no Glama MCP servers found for XHS). The merge will proceed with 4 sources for XHS, 5 for others.

### 1.2 Platform Comparison Summary

| Source File | Source Dir | Target File | Target Dir | Action |
|-------------|------------|-------------|------------|--------|
| `SUMMARY.md` | `research-output/glama/` | `PLATFORM_COMPARISON.md` | `references/` | **Copy/Rename** |

> **Note:** `SUMMARY.md` does not currently exist in `glama/` — if absent, create from consolidated platform-methods content (see §2.2).

### 1.3 PRD-Source References — Direct Copy (Overwrite Target)

| Source File | Source Dir | Target File | Target Dir | Action |
|-------------|------------|-------------|------------|--------|
| `collection-schema.md` | `prd-source/references/` | `collection-schema.md` | `references/` | **Overwrite** |
| `data-schema.md` | `prd-source/references/` | `data-schema.md` | `references/` | **Overwrite** |
| `cookie-guide.md` | `prd-source/references/` | `cookie-guide.md` | `references/` | **Overwrite** |

> **Note:** Target already has `collection-schema.md` (identical size 18649 bytes), `data-schema.md` (929 bytes), `cookie-guide.md` (3125 bytes). Overwrite to ensure parity with PRD source of truth.

### 1.4 PRD-Source Platform References — Keep Existing (Update if Different)

| Source File | Source Dir | Target File | Target Dir | Action |
|-------------|------------|-------------|------------|--------|
| `bilibili.md` | `prd-source/references/platforms/` | `bilibili.md` | `references/platforms/` | **Keep** (compare & update if needed) |
| `douyin.md` | `prd-source/references/platforms/` | `douyin.md` | `references/platforms/` | **Keep** (compare & update if needed) |
| `weibo.md` | `prd-source/references/platforms/` | `weibo.md` | `references/platforms/` | **Keep** (compare & update if needed) |
| `xiaohongshu.md` | `prd-source/references/platforms/` | `xiaohongshu.md` | `references/platforms/` | **Keep** (compare & update if needed) |

> **Note:** Target files appear to be copies of PRD-source (same byte counts for bilibili/xiaohongshu). Diff before deciding; prefer PRD-source as canonical.

### 1.5 New Scripts from Research Findings

| Source Concept | Target File | Target Dir | Action |
|----------------|-------------|------------|--------|
| PRD Adapter (normalize research data → PRD schema) | `prd_adapter.py` | `scripts/` | **Create New** |
| Cookie Manager (unified cookie handling per cookie-guide.md) | `cookie_manager.py` | `scripts/` | **Create New** |
| Sign Server (X-S/X-T, WBI, XR-SN signing abstractions) | `sign_server.py` | `scripts/` | **Create New** |
| Identity Resolver (account name → canonical profile URL) | `identity_resolver.py` | `scripts/` | **Create New** |

---

## 2. Merge Strategy for `platform-methods/`

### 2.1 Target Structure per Platform File

Each `references/platform-methods/{platform}.md` will have this structure:

```markdown
# {Platform} Collection Methods — Consolidated Research

> Merged from: GitHub, ClawHub, Glama, npm, PyPI research (2026-08-05)

## Executive Summary
- **Best Overall (Read)**: {top repo/server/package}
- **Best for Publishing**: {top write-capable}
- **Best MCP Server**: {top MCP}
- **Key Gaps**: {views, signature drift, auth fragility, etc.}

## Source Attribution
| Source | File | Focus |
|--------|------|-------|
| GitHub | `github/{platform}.md` | Open-source repos, CLI tools, libraries |
| ClawHub | `clawhub/{platform}.md` | OpenClaw skill registry, MCP wrappers |
| Glama | `glama/{platform}.md` | MCP server marketplace (glama.ai) |
| npm | `npm/{platform}.md` | Node.js packages, TypeScript toolkits |
| PyPI | `pypi/{platform}.md` | Python packages, SDKs |

## Method Categories

### 1. Full-Featured Scrapers / SDKs (GitHub primary)
- Table: Repo | Stars | Last Update | Aggressiveness | Profile | Post | Metrics | Confidence
- Top 3 detailed with PRD coverage matrix, usage commands, gaps

### 2. MCP Servers (Glama + ClawHub)
- Table: Server | URL | Auth | Tools | Profile | Post | Metrics | Confidence
- Top 3 detailed with tool lists, PRD coverage, confidence

### 3. npm Packages
- Table: Package | Version | Auth | Methods | Coverage | Confidence
- Detail for each

### 4. PyPI Packages
- Table: Package | Version | Auth | Methods | Coverage | Confidence
- Detail for each

## Consolidated PRD Coverage Matrix
| PRD Field | GitHub Best | MCP Best | npm Best | PyPI Best | Overall Status |
|-----------|-------------|----------|----------|-----------|----------------|
| Profile: account_id | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| Profile: followers | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| ... | | | | | |

## Critical Gaps & Risks
- Per-source gaps (signature drift, view counts, auth fragility)
- Cross-cutting: no official API, all reverse-engineered

## Recommendations for Skill Implementation
- Preferred primary adapter approach
- Fallback chain
- Cookie/auth handling strategy
- Rate limit / anti-bot mitigation
```

### 2.2 Merge Rules

| Content Type | Rule |
|--------------|------|
| **Method Tables** | Union all rows; deduplicate by repo/package/server name; keep highest-confidence entry; add `source` column |
| **Top 3 Details** | Keep all unique entries across sources; label origin (GitHub/Glamal/ClawHub/npm/PyPI) |
| **Gaps** | Union; deduplicate by gap theme; annotate which sources report it |
| **Confidence** | Weight: GitHub > Glama ≈ ClawHub > npm ≈ PyPI (based on direct inspectability) |
| **Commands/Usage** | Preserve all unique invocation patterns; group by tool type |
| **Dates** | Use most recent `last update` per tool; note staleness if >6 months |

### 2.3 Special Handling

- **Glama missing XHS**: Note in XHS file: "No Glama MCP servers found for Xiaohongshu as of 2026-08-05"
- **ClawHub ghost skills**: Mark as `unverified` with `confidence: low` and note "README only via third-party mirrors"
- **npm/PyPI sparsity**: Most platforms have 0-1 packages; document absence explicitly

---

## 3. Overwrite vs. Keep vs. Merge Decision Matrix

| Target Path | Source(s) | Decision | Rationale |
|-------------|-----------|----------|-----------|
| `docs/research/platform-methods/{platform}.md` | 5 research sites | **MERGE** | New consolidated reference; no existing target |
| `references/PLATFORM_COMPARISON.md` | `glama/SUMMARY.md` | **CREATE** | New cross-platform view; derive if SUMMARY missing |
| `references/collection-schema.md` | `prd-source/references/` | **OVERWRITE** | PRD is canonical; target may drift |
| `references/data-schema.md` | `prd-source/references/` | **OVERWRITE** | PRD is canonical |
| `references/cookie-guide.md` | `prd-source/references/` | **OVERWRITE** | PRD is canonical |
| `references/platforms/{platform}.md` | `prd-source/references/platforms/` | **KEEP + DIFF** | Target appears synced; only update if PRD-source newer |
| `scripts/prd_adapter.py` | — | **CREATE NEW** | Research reveals need for schema normalization layer |
| `scripts/cookie_manager.py` | — | **CREATE NEW** | cookie-guide.md mandates unified handling |
| `scripts/sign_server.py` | — | **CREATE NEW** | Multiple signing schemes (X-S/X-T, WBI, XR-SN) need abstraction |
| `scripts/identity_resolver.py` | — | **CREATE NEW** | Account discovery logic scattered across platform refs |

---

## 4. New Directories Needed

| Directory | Purpose | Created By |
|-----------|---------|------------|
| `docs/research/platform-methods/` | Consolidated per-platform method research | Migration Step 1 |
| `docs/` | Migration plan + future documentation | Migration Step 0 (this plan) |

> **Note:** `scripts/` already exists. No new script subdirectories needed.

---

## 5. Order of Operations

### Phase 0: Preparation (Run First)

```bash
# 0.1 Create target directories
mkdir -p /Users/jack/Documents/public-social-account-analyzer/docs/research/platform-methods
mkdir -p /Users/jack/Documents/public-social-account-analyzer/docs

# 0.2 Backup existing target references (optional but recommended)
cp -r /Users/jack/Documents/public-social-account-analyzer/skill/references \
      /Users/jack/Documents/public-social-account-analyzer/skill/references.backup.$(date +%Y%m%d)
```

### Phase 1: Create Platform Methods (Merge 5 Sources → 4 Files)

```bash
# 1.1 For each platform (xiaohongshu, douyin, bilibili, weibo):
#     - Read all 5 source files
#     - Apply merge strategy (§2)
#     - Write to docs/research/platform-methods/{platform}.md

# Suggested order (most complex first):
# 1. xiaohongshu.md (4 sources, most MCP forks)
# 2. douyin.md (5 sources, complex auth)
# 3. bilibili.md (5 sources, many MCP servers)
# 4. weibo.md (5 sources, fewer tools)
```

### Phase 2: Create Platform Comparison

```bash
# 2.1 If glama/SUMMARY.md exists → copy to references/PLATFORM_COMPARISON.md
# 2.2 Else → synthesize from platform-methods/ files:
#      - Table: Platform | GitHub Best | MCP Best | npm Best | PyPI Best | Overall Maturity
#      - Cross-platform gaps (views, signatures, auth)
#      - Recommendation: primary adapter per platform
```

### Phase 3: Sync PRD-Source References (Overwrite)

```bash
# 3.1 cp prd-source/references/collection-schema.md skill/references/
# 3.2 cp prd-source/references/data-schema.md skill/references/
# 3.3 cp prd-source/references/cookie-guide.md skill/references/
# 3.4 Verify byte-for-byte match with backup
```

### Phase 4: Sync PRD-Source Platform References (Diff & Update)

```bash
# 4.1 For each platform in {bilibili,douyin,weibo,xiaohongshu}:
#     diff prd-source/references/platforms/{platform}.md \
#          skill/references/platforms/{platform}.md
#     If different → overwrite with prd-source version
#     If identical → no-op
```

### Phase 5: Create New Scripts (Scaffold from Research)

```bash
# 5.1 Create scripts/prd_adapter.py
#     - Input: raw platform data (various schemas)
#     - Output: PRD-compliant Profile/Post/Metrics per collection-schema.md
#     - Key functions: normalize_profile(), normalize_post(), normalize_metrics()
#     - Handle nullable fields, field_visibility, collection_status

# 5.2 Create scripts/cookie_manager.py
#     - Per cookie-guide.md: parse, validate, store, load, rotate cookies
#     - Support per-platform cookie schemas (XHS: a1/web_session/webId; Douyin: SESSDATA; Bili: SESSDATA/JCT/BUVID3; Weibo: SUB/SSOLoginState)
#     - Secure temp file handling (0600, auto-cleanup)

# 5.3 Create scripts/sign_server.py
#     - Abstract interface: sign(request, platform) → signed_headers
#     - Implementations: XHS X-S/X-T (ReaJason), Douyin WBI (sunwu51), Bili WBI, XHS XR-SN (borye)
#     - Docker sign server management (start/stop/health)

# 5.4 Create scripts/identity_resolver.py
#     - Input: user-provided identifier (nickname, handle, short URL)
#     - Output: canonical profile URL per platform
#     - Strategies: search API, share link resolution, sec_uid extraction
#     - Per-platform rules from platform references
```

### Phase 6: Validation

```bash
# 6.1 Verify all 4 platform-methods files exist and have content
# 6.2 Verify PLATFORM_COMPARISON.md exists
# 6.3 Verify 3 PRD references overwritten
# 6.4 Verify 4 platform refs synced (or confirmed identical)
# 6.5 Verify 4 new scripts created with basic scaffolding
# 6.6 Run any existing tests to ensure no regressions
```

---

## 6. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| PRD-source platform refs differ from target | Diff first; only overwrite if PRD-source is newer (check git log or file mtime) |
| Glama SUMMARY.md missing | Synthesize from platform-methods — no blocking |
| Research files have conflicting data | Use confidence weighting; document conflicts in Gaps section |
| New scripts break existing collectors | Scaffold only; implement incrementally behind feature flags |
| Cookie guide changes affect existing scripts | Phase 3 overwrites cookie-guide.md; Phase 5 scripts follow new guide |

---

## 7. Deliverables Checklist

- [ ] `docs/migration-plan.md` (this file)
- [ ] `references/platform-methods/xiaohongshu.md`
- [ ] `references/platform-methods/douyin.md`
- [ ] `references/platform-methods/bilibili.md`
- [ ] `references/platform-methods/weibo.md`
- [ ] `references/PLATFORM_COMPARISON.md`
- [ ] `references/collection-schema.md` (overwritten)
- [ ] `references/data-schema.md` (overwritten)
- [ ] `references/cookie-guide.md` (overwritten)
- [ ] `references/platforms/bilibili.md` (synced)
- [ ] `references/platforms/douyin.md` (synced)
- [ ] `references/platforms/weibo.md` (synced)
- [ ] `references/platforms/xiaohongshu.md` (synced)
- [ ] `scripts/prd_adapter.py` (scaffolded)
- [ ] `scripts/cookie_manager.py` (scaffolded)
- [ ] `scripts/sign_server.py` (scaffolded)
- [ ] `scripts/identity_resolver.py` (scaffolded)

---

## 8. Estimated Effort

| Phase | Est. Time | Notes |
|-------|-----------|-------|
| Phase 0 | 5 min | Directory creation, backup |
| Phase 1 | 60-90 min | 4 platforms × merge logic |
| Phase 2 | 15 min | Comparison synthesis |
| Phase 3 | 5 min | 3 file copies |
| Phase 4 | 10 min | 4 diffs + conditional overwrites |
| Phase 5 | 60-120 min | 4 script scaffolds with key functions |
| Phase 6 | 15 min | Validation |
| **Total** | **~2.5-3.5 hours** | Single session feasible |

---

*End of Migration Plan*
