# Douyin (抖音 / TikTok China) — Consolidated Platform Reference

> **Source aggregation**: GitHub (12 repos), Clawhub (0 verifiable), Glama (1 indexed + 1 best-fit off-registry), PyPI (5 packages), npm (15 packages). Smithery: 0 Douyin servers.

---

## 1. Executive Summary

| Dimension | Assessment |
|-----------|------------|
| **Best overall method (unofficial)** | **hhy5562877/douyin_mcp** (GitHub) — only repo with full PRD profile+post+metrics coverage via private API (`aweme/v1`), cookie + local `a_bogus` signing via `py_mini_racer`. **Not on Glama/Smithery** — must self-host or submit to registry. |
| **Best overall method (official/legal)** | **douyin-api** (PyPI) — wraps ByteDance Open Platform official APIs. Full PRD coverage **but gated by developer approval** (business license, use-case review). |
| **Best commercial API** | **@ethanchen/tikhub-client** (npm) — TikHub commercial API wrapper; covers Douyin + TikTok global + Xiaohongshu + Weibo. Reliable, typed, maintained (Nov 2025). |
| **Runner-up (browser automation)** | **@sparanoid/eop-extractor-douyin** / **douyin-data-extractor** (npm) — Puppeteer/Playwright DOM extraction from rendered `__NEXT_DATA__`. Full PRD fields but **no sec_uid resolution**; brittle to UI changes. |
| **Key trade-off** | **Unofficial private API** (hhy5562877, Evil0ctal, bigdong89) = full data access, no approval needed, but signing breaks on app updates (X-Bogus/a_bogus rotation). **Official API** (douyin-api, weibo-mcp) = sustainable, legal, but requires ByteDance approval (weeks-months). **Commercial API** (TikHub) = reliable, multi-platform, but paid. |
| **Critical gap** | **No nickname → sec_uid resolver in any OSS package** — all require `sec_uid`/`unique_id` upfront. The 302 redirect from `v.douyin.com/<short>` → `iesdouyin.com/share/user/<sec_uid>` is the only programmatic path; no package wraps this as a first-class tool. |

---

## 2. Site-by-Site Findings Table

| Site | Best Finding | Aggressiveness | PRD Coverage (Profile/Post/Metrics) | Confidence | Notes |
|------|--------------|----------------|-------------------------------------|------------|-------|
| **GitHub** | Evil0ctal/Douyin_TikTok_Download_API (~13.5k★) | High (cookies + X-Bogus.js + MsToken + private `/aweme/v1/web/...`) | ✅ Profile (sec_uid, unique_id, douyin_id, bio, verified, followers, following, post_count, total_likes)<br>✅ Post (aweme_id, URL, title, text, type, published_at, duration, hashtags, pinned/promoted/repost)<br>✅ Metrics (views, likes, comments, shares, favorites) | High | Canonical scraper; Docker; Chromium cookie sniffer included; active 2026-07 |
| | bigdong89/Douyin-Downloader (DarkHexBoy fork) | High (API strategy + Playwright fallback) | ✅ Profile (sec_uid, unique_id, name, avatar, followers, aweme_count)<br>✅ Post (aweme_id, URL, title, type, duration, hashtags partial)<br>✅ Metrics (likes, comments, shares, views via API) | High | Modular strategy pattern; bulk mode; cookie extractor in-box; active 2026-07 |
| | hhy5562877/douyin_mcp | High (cookies.txt + py_mini_racer a_bogus) | ✅ Profile (`get_user_info(sec_uid)`)<br>✅ Post (`get_user_posts`, `get_video_detail`)<br>✅ Metrics (per-post likes/comments/shares; user aggregate in payload) | Medium | **Best PRD fit**; 8 tools; NOT on Glama/Smithery; 2 commits only |
| **Clawhub** | *No verifiable skills* | — | — | — | Direct fetch blocked; WebSearch returned only third-party references |
| **Glama** | @yzfly/douyin-mcp-server (indexed) | None (share-link parse only) | ❌ Profile ❌ Post ⚠️ Metrics (transcript only) | High (badge confirmed) | Only Glama-indexed Douyin MCP; downloader, not collector |
| | hhy5562877/douyin_mcp (off-registry) | High | ✅✅✅ | Medium | Best fit but not indexed; submit to Glama recommended |
| **PyPI** | douyin-api (official wrapper) | Low (OAuth2, requests) | ✅✅✅ (all fields via official API) | High | Requires ByteDance developer approval; active (Jul 2025) |
| | TikTokApi (TikTok global) | High (Playwright + ms_token) | ✅✅✅ for TikTok global | High | **Does not work for Douyin China** (different sig/endpoints) |
| | douyin (Germey) | High (aiohttp + X-Bogus/X-Khronos) | ⚠️ Partial (abandoned ~2020) | Medium | Signing stale; no nickname→sec_uid |
| **npm** | @ethanchen/tikhub-client | None (HTTPS + API key) | ✅✅✅ (multi-platform) | High | Commercial; TypeScript types; active Nov 2025 |
| | exportdou (official CLI) | Medium (OAuth-style auth) | ✅ Profile/Post; ❌ Metrics (comments only) | High | Official ExportDou platform; recent Jul 2026 |
| | @sparanoid/eop-extractor-douyin | High (Puppeteer/EOP) | ✅✅✅ (from rendered JSON) | Medium | No sec_uid resolution; brittle; Mar 2024 |

---

## 3. Best Method Detailed: hhy5562877/douyin_mcp (Unofficial, Self-Hosted)

**Name**: douyin_mcp  
**Source**: GitHub — https://github.com/hhy5562877/douyin_mcp  
**Type**: Python MCP server (FastMCP + `py_mini_racer` for a_bogus)  
**License**: MIT (assumed)  
**Registry Status**: **NOT on Glama/Smithery** — must self-host or submit

### PRD Coverage
| PRD Block | Fields | Coverage |
|-----------|--------|----------|
| **Profile** | `account_id` (sec_uid), `account_name`, `bio`, `verified`, `followers`, `following`, `post_count` (`aweme_count`), `total_likes` (`total_favorited`), `platform_metrics.sec_uid`, `unique_id`, `douyin_id` | ✅ via `get_user_info(sec_user_id)` — returns full user payload |
| **Post** | `post_id` (aweme_id), `post_url` (/video/<id>), `title`/`text` (desc), `content_type`, `published_at` (+08:00 conversion needed), `duration`, `hashtags`, `is_pinned`, `is_promoted`, `is_repost` | ✅ via `get_video_detail(aweme_id)` + `get_user_posts(sec_user_id)` — raw aweme payload has all flags |
| **Metrics** | `views` (play_count), `likes` (digg_count), `comments`, `shares`, `favorites` (collect_count) | ✅ per-post via `get_video_detail`; user-level aggregates in `get_user_info` payload |

### Tools Exposed (8)
1. `check_login_status` — validates cookies
2. `search_videos(keyword, offset, count, sort_type, publish_time)`
3. `get_video_detail(aweme_id)`
4. `get_video_comments(aweme_id, cursor, count)`
5. `get_sub_comments(comment_id, cursor, count)`
6. `get_user_info(sec_user_id)` — **profile + aggregate metrics**
7. `get_user_posts(sec_user_id, max_cursor, count)` — **paginated post list**
8. `get_home_feed(tag, count, refresh_index)`

### How to Use
```bash
# Clone and setup
git clone https://github.com/hhy5562877/douyin_mcp
cd douyin_mcp
uv sync  # or pip install -r requirements.txt

# Obtain cookies: login to douyin.com in browser, export cookies.txt (Netscape format) to project root
# Required cookies: sessionid_ss, ttwid, msToken, passport_csrf_token, etc.

# Run MCP server
python -m douyin_mcp  # or uv run douyin_mcp

# Connect MCP client (Claude Code, Cursor, Cline) to stdio transport
```

**Auth**: `cookies.txt` in project root (Netscape format). No QR login; manual cookie export required.  
**Signing**: Local `a_bogus` / `X-Bogus` generation via embedded JS + `py_mini_racer` (no browser needed).  
**Endpoints**: Private `aweme/v1/web/...` (same as Evil0ctal).  
**Rate limits**: Not built-in; caller must throttle.  
**Timezone**: `published_at` is Unix epoch (UTC) — consumer must add `+08:00`.

### Aggressiveness Profile
- **Browser**: None (pure HTTP + local JS signing)
- **Signing**: `a_bogus` / `X-Bogus` via `py_mini_racer` (embedded JS)
- **Auth**: Cookie file (manual export)
- **Anti-bot**: Relies on valid cookies + correct signing; residential proxies recommended for scale

---

## 4. Runner-Up: Evil0ctal/Douyin_TikTok_Download_API (GitHub, Most Mature)

**Name**: Douyin_TikTok_Download_API  
**Source**: GitHub — https://github.com/Evil0ctal/Douyin_TikTok_Download_API  
**Type**: FastAPI + HTTPX + PyWebIO (Docker-ready)  
**License**: MIT

### PRD Coverage
Identical to hhy5562877 — covers all PRD fields via same private endpoints.

### How to Use
```bash
git clone https://github.com/Evil0ctal/Douyin_TikTok_Download_API
cd Douyin_TikTok_Download_API
pip install -r requirements.txt

# Configure cookies in config.yaml (or use chrome-cookie-sniffer/)
# Run: python start.py
# API: /api/hybrid/video_data?url=...&minimal=false
#      /api/douyin/web/fetch_user_videos_by_sec_uid?sec_uid=...
```

**Advantages over hhy5562877**:
- ~13.5k stars, 1100+ commits, actively maintained 2026-07
- Built-in Chromium cookie sniffer (`chrome-cookie-sniffer/`)
- Docker-ready, REST API (not MCP) — easier for non-MCP consumers
- Modular `APIDownloadStrategy` + `BrowserStrategy` fallback

**Disadvantages**:
- REST API, not MCP (requires wrapper for AI-agent workflows)
- Larger codebase, more moving parts

---

## 5. Gaps (Across All Sites)

| Gap | Severity | Details |
|-----|----------|---------|
| **No nickname → sec_uid resolver** | Critical | All OSS tools require `sec_uid`/`unique_id` upfront. The 302 redirect `v.douyin.com/<short>` → `iesdouyin.com/share/user/<sec_uid>` is the only path; no package wraps this. PRD requires this binding. |
| **No Smithery Douyin server** | High | `site:smithery.ai douyin` = 0 results. If deployment target is Smithery-only, no drop-in exists. |
| **Only 1 Glama server (downloader)** | High | `@yzfly/douyin-mcp-server` is share-link → video only. Best PRD fit (hhy5562877) not indexed. |
| **Signature maintenance burden** | High | X-Bogus / a_bogus / _signature rotate with app updates. Evil0ctal maintains `X-Bogus.js`; hhy5562877 embeds JS. Both break without updates. |
| **No official API access for most** | Structural | `douyin-api` (PyPI) wraps official Open Platform but requires ByteDance approval (business license, use-case review). |
| **Followers/total_likes/post_count not wrapped as tools** | Medium | `get_user_info` returns raw payload with these fields but no dedicated MCP tools — consumer must unpack. |
| **is_pinned/is_promoted/is_repost flags not surfaced** | Medium | Exist in raw aweme payload (`aweme_control`, `commerce_info`) but no MCP server exposes them explicitly. |
| **Timezone normalization missing** | Medium | `create_time` is Unix UTC; `+08:00` conversion is consumer-side. |
| **No browser-automation fallback in hhy5562877** | Medium | Pure HTTP signing; if signing breaks, no Playwright fallback. bigdong89 has both strategies. |
| **Glama search broken** | Operational | `?q=douyin` returns generic list; must use sitemap to enumerate. |

---

## 6. Key Technical Trade-offs Table

| Dimension | hhy5562877/douyin_mcp | Evil0ctal/Douyin_API | bigdong89/Downloader | douyin-api (Official) | @ethanchen/tikhub-client | @sparanoid/eop-extractor |
|-----------|----------------------|---------------------|---------------------|----------------------|--------------------------|--------------------------|
| **Coverage (PRD)** | ★★★★★ | ★★★★★ | ★★★★☆ | ★★★★★ | ★★★★★ | ★★★★☆ |
| **Identity resolution** | ❌ Needs sec_uid | ❌ Needs sec_uid | ❌ Needs sec_uid | ✅ Official search | ✅ API resolves | ❌ Needs unique_id |
| **Maintenance** | Low (2 commits, stale risk) | High (active, 13.5k★) | High (active fork) | ByteDance maintains | Vendor maintains | Medium (Mar 2024) |
| **Aggressiveness** | High (cookie + local JS sig) | High (cookie + X-Bogus.js) | High (API + Playwright) | Low (OAuth2) | None (HTTPS) | High (Puppeteer) |
| **License risk** | MIT | MIT | MIT | Official ToS | Commercial | MIT |
| **Output** | MCP tools (stdio) | REST API (FastAPI) | CLI / JSON | Python SDK | TypeScript SDK | JSON from DOM |
| **Deployment** | Self-host MCP | Docker / Server | CLI / Server | Python package | npm package | npm package |
| **Best for** | AI-agent (MCP) | Bulk REST collection | Bulk CLI + fallback | Legal/compliance | Multi-platform paid | Quick DOM extraction |

---

## 7. Recommendation

| Use Case | Recommended Stack |
|----------|-------------------|
| **AI-agent / MCP workflow** | Submit `hhy5562877/douyin_mcp` to Glama (`glama.ai/submit`) → use as MCP server. Or self-host + custom nickname→sec_uid resolver. |
| **Bulk scheduled collection (server)** | Evil0ctal/Douyin_TikTok_Download_API (Docker) + cron + cookie rotation |
| **Legal/compliance required** | `douyin-api` (PyPI) — apply for ByteDance Open Platform approval |
| **Multi-platform (Douyin + TikTok + XHS + Weibo)** | `@ethanchen/tikhub-client` (npm) — commercial, reliable, typed |
| **One-off / low-volume** | bigdong89/Douyin-Downloader (modular, Playwright fallback) |
| **Quick extraction from share links** | @yzfly/douyin-mcp-server (Glama) — but profile/post list not supported |

**Critical path for PRD compliance**: 
1. Build `nickname → sec_uid` resolver (capture 302 from `v.douyin.com/<short>` or scrape `douyin.com/user/<unique_id>`)
2. Wrap chosen collector with `+08:00` timezone normalization
3. Implement cookie rotation (daily refresh via headless login or cookie pool)
4. Add `is_pinned`/`is_promoted`/`is_repost` extraction from raw aweme payload