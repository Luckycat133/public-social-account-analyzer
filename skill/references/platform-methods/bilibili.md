# Bilibili (哔哩哔哩 / B站) — Consolidated Platform Reference

> **Source aggregation**: GitHub (9 repos + 2 archived canonical), Clawhub (1 skill), Glama (14 servers), PyPI (6 packages), npm (7 packages). Smithery: 0 Bilibili servers.

---

## 1. Executive Summary

| Dimension | Assessment |
|-----------|------------|
| **Best overall method** | **Iseenope/bilibili-mcp-server** (Glama) — 31 tools, full PRD coverage (profile/posts/metrics/collections/danmaku), accepts numeric UID, QR login + cookie auth, active 2026-08. |
| **Runner-up (collection/series specialist)** | **SMYB5431/bilibili-api-mcp-server** (Glama, GitHub: ptbsare/bilibili-mcp-server) — only server exposing 视频合集 (collection/series) APIs with `season_id`/`series_name`; covers `collection_evidence_status`. |
| **Best Python library** | **bilibili-api-python** (PyPI, v17.4.2) — primary SDK, active monthly releases, WBI signing internal, curl_cffi fingerprinting, 400+ endpoints. |
| **Best CLI / agent-friendly** | **bilibili-cli** (PyPI, v0.6.2) — wraps bilibili-api-python, structured YAML/JSON output, 3-tier auth (saved cred → browser cookie extraction → QR login). |
| **Best npm library (read-only)** | **bili-api** (simon300000) — zero auth, public endpoints only, throttled, stable core fields. |
| **Best npm library (full auth)** | **@renmu/bili-api** — cookies + WBI + QR login + upload + collection CRUD; GPL, rapid iteration. |
| **Key trade-off** | **Archived canonicals**: SocialSisterYi/bilibili-API-collect (20.2k★) and Nemo2011/bilibili-api (4.2k★) were C&D'd by Bilibili (2026-01, 2026-07). All live options are smaller MCP servers or forks. Legal risk exists for aggressive scraping. |
| **Critical gap** | **No server accepts `https://space.bilibili.com/<uid>` as single string input** — all require numeric UID extraction by caller. **Coins (`投币`) and `shares` not exposed** by any server. **WBI signing** only explicit in sunwu51; others rely on internal lib behavior. **Live-clip content_type** not typed separately. |

---

## 2. Site-by-Site Findings Table

| Site | Best Finding | Aggressiveness | PRD Coverage (Profile/Post/Metrics) | Confidence | Notes |
|------|--------------|----------------|-------------------------------------|------------|-------|
| **GitHub** | 222wcnm/BiliStalkerMCP | Medium (SESSDATA, QR login, optional cookie refresh, no browser) | ✅ Profile (uid, name, level, followers, followings, bio, verified)<br>✅ Post (BV/AV, video_info, danmaku, subtitle, articles, dynamics, followings)<br>✅ Metrics (views, likes, comments, danmaku, coins, favorites partial) | High | Designed for "analyze specific user"; accepts `user_id_or_username` (numeric UID); explicit tool list |
| | Zijian-Ni/bilibili-mcp-server | Medium (cookies, explicit WBI module, rate limit+retry) | ✅ Profile (search-based)<br>✅ Post (search, video detail, comments, danmaku, favorites)<br>✅ Metrics (views, likes, replies; danmaku full) | Medium-High | PyPI-published; excellent engineering; no direct numeric-UID profile tool |
| | ptbsare/bilibili-mcp-server | Low-Med (cookies optional, no WBI visible) | ⚠️ Profile (search_user only)<br>⚠️ Post (search + danmaku)<br>⚠️ Metrics (search payload only) | Low-Med | Most recent push (2026-08-02) but thinnest coverage |
| **Clawhub** | bilibili-subtitle-download-skill | Low (public subtitle API only) | ❌ Profile<br>⚠️ Post (single BV → subtitle only)<br>❌ Metrics | Low | Only Bilibili skill on Clawhub; subtitle getter, not collector |
| **Glama** | Iseenope/bilibili-mcp-server | High (SESSDATA/QR, 31 tools incl. write: comment/like/follow/upload) | ✅✅✅ Full PRD + dynamics + articles + live + messages + download | High | Largest tool count; TypeScript; updated 2026-08; accepts numeric UID |
| | adoresever/bilibili-mcp | High (QR + cookies, 27 tools incl. publish dynamic + upload video) | ✅✅✅ Full PRD + **content publishing** | High | Only server with `bili_send_dynamic` / `bili_upload_video` |
| | SMYB5431/bilibili-api-mcp-server | Medium (SESSDATA, reads private collection/dynamic endpoints) | ✅ Profile (search)<br>✅ Post + **collections (合集/season)**<br>✅ Metrics + **collection_evidence_status** | High | Only server with 合集 APIs; PyPI `bilibili-api-mcp-server` |
| | 222wcnm/BiliStalkerMCP | Medium (SESSDATA, auto cookie refresh) | ✅ Profile (UID/username)<br>✅ Post (videos/dynamics/articles)<br>✅ Metrics (partial) | High | Same as GitHub entry; on Glama |
| | YunGaoluo/bilibili-mcp-python | High (SESSDATA+JCT+BUVID3, 22 tools incl. private msg) | ✅✅✅ Full | High | Python; private messaging tools unique |
| | masx200/bilibili-mcp-server | High (SESSDATA+buvid3, streamable-http + bearer) | ✅ Profile (uid-based)<br>⚠️ Post (search+retrieve)<br>✅ Metrics (views+likes) | High | Multiple transports |
| **PyPI** | bilibili-api-python (v17.4.2) | High (Credential, WBI internal, curl_cffi fingerprinting) | ✅ Profile (get_user_info)<br>✅ Post (Video, dynamic, article, ugc_season)<br>✅ Metrics (stat: view, like, coin, fav, reply, danmaku, share) | High | Primary SDK; GPL-3.0; Python ≥3.10; active monthly |
| | bilibili-cli (v0.6.2) | High (browser cookie extraction → QR login) | ✅ Profile (user profile)<br>✅ Post (video info, subtitles, comments)<br>✅ Metrics (views, likes, coins, favs, comments, danmaku) | High | MIT; structured YAML/JSON; wraps bilibili-api-python |
| | bili-dl (v0.2.9) | Low (cookie-only, yt-dlp backend) | ❌ Profile<br>⚠️ Post (video URL, title, basic meta via yt-dlp)<br>⚠️ Metrics (views/likes via yt-dlp) | Medium | Apache-2.0; download-focused; no WBI |
| **npm** | bili-api (simon300000) | None (anonymous public APIs) | ✅ Profile (mid, name, bio, level, follower)<br>✅ Post (bvid, title, desc, pubdate, tags)<br>✅ Metrics (view, danmaku, like, coin, fav, share) | High | MIT; zero auth; throttled; last update 2023 |
| | @renmu/bili-api | High (cookies + WBI + QR login + upload) | ✅✅✅ Full PRD + collections + upload + live | High | GPL; Node ≥18; active May 2026; "no stability guarantee" |
| | @yiero/bilibili-api-lib | Medium (cookies + WBI partial) | ⚠️ Profile (basic + video list)<br>✅ Post + **collection/season CRUD**<br>⚠️ Metrics (basic only) | Low | Only lib with `editSeason`/`editSeasonSection`; 7 dl/wk |

---

## 3. Best Method Detailed: Iseenope/bilibili-mcp-server (Glama)

**Name**: bilibili-mcp-server  
**Source**: Glama — https://glama.ai/mcp/servers/Iseenope/bilibili-mcp-server  
**GitHub**: https://github.com/Iseenope/bilibili-mcp-server  
**Type**: TypeScript MCP server (31 tools)  
**License**: MIT (assumed)

### PRD Coverage
| PRD Block | Fields | Coverage |
|-----------|--------|----------|
| **Profile** | `account_id` (UID), `account_name`, `bio` (sign), `verified` (official_verify), `followers`, `following`, `post_count` (archive_count/dynamic_count), `level` | ✅ `bilibili_user_info(uid)` |
| **Post** | `post_id` (BV号/AV号), `post_url`, `title`, `content_type` (video/dynamic/article/live_clip), `published_at` (+08:00), `duration_seconds`, `hashtags` (tags), `is_pinned`, `is_repost`, `is_promoted`, `collection_evidence_status`, `is_in_collection`, `series_name`, `season_id` | ✅ `bilibili_video_info(bvid)`, `bilibili_user_videos(uid)`, `bilibili_user_dynamics(uid)`, `bilibili_user_articles(uid)`, `bilibili_user_followings(uid)` |
| **Metrics** | `views`, `likes`, `coins`, `favorites`, `comments` (reply), `danmaku`, `shares` | ✅ `stat` object in video_info; ⚠️ `coins`/`shares` not in all tool outputs |

### Tools (31) — Key Categories
| Category | Tools |
|----------|-------|
| **User/Profile** | `bilibili_user_info`, `bilibili_user_videos`, `bilibili_user_dynamics`, `bilibili_user_articles`, `bilibili_user_followings`, `bilibili_user_followers`, `bilibili_user_favorites` |
| **Video/Post** | `bilibili_video_info`, `bilibili_video_comments`, `bilibili_video_subtitle`, `bilibili_video_danmaku`, `bilibili_video_hot_comments`, `bilibili_video_download` |
| **Search** | `bilibili_search_video`, `bilibili_search_user`, `bilibili_search_live` |
| **Interactive (Write)** | `bilibili_comment`, `bilibili_comment_reply`, `bilibili_comment_like`, `bilibili_like`, `bilibili_follow`, `bilibili_unfollow` |
| **Content Publishing** | `bilibili_upload_video`, `bilibili_submit_video` |
| **Live** | `bilibili_live_info`, `bilibili_live_screenshot` |
| **Auth/System** | `bilibili_qr_login`, `bilibili_login_status`, `bilibili_refresh_cookie` |

### How to Use
```bash
# Via Glama (recommended)
# 1. Install via Glama UI or copy server config
# 2. Add to MCP client (Claude Code, Cursor, Cline):
{
  "mcpServers": {
    "bilibili": {
      "command": "npx",
      "args": ["-y", "@Iseenope/bilibili-mcp-server"],
      "env": {
        "SESSDATA": "your_sessdata",
        "BILI_JCT": "your_bili_jct",
        "BUVID3": "your_buvid3"
      }
    }
  }
}

# Or QR login (no cookies needed initially):
# Call bilibili_qr_login tool → scan with Bilibili app → credentials auto-saved
```

**Collection entry**: `https://space.bilibili.com/<uid>` → extract numeric `uid` → pass to `bilibili_user_info(uid)`.  
**Aggressiveness**: Full cookie auth (SESSDATA/BILI_JCT/BUVID3) **or** QR login. Write tools (comment, like, follow, upload) make it a 1st-party client equivalent.  
**Maintenance**: Active (updated 2026-08), TypeScript, explicit tool schemas.  
**WBI signing**: Handled internally (not exposed as separate module).

---

## 4. Runner-Up: SMYB5431/bilibili-api-mcp-server (Collection/Series Specialist)

**Name**: bilibili-api-mcp-server (GitHub: ptbsare/bilibili-mcp-server)  
**Source**: Glama — https://glama.ai/mcp/servers/SMYB5431/bilibili-api-mcp-server  
**PyPI**: `bilibili-api-mcp-server`  
**Type**: Python MCP server

### Unique PRD Coverage
| Feature | Coverage |
|---------|----------|
| **视频合集 (Collections/Series)** | ✅ `series_name`, `season_id`, `is_in_collection`, `collection_evidence_status` via 合集 API |
| **Dynamic feeds** | ✅ `bilibili_user_dynamics` with type filter (VIDEO/DRAW/TEXT/REVIEW) |
| **Danmaku** | ✅ Full binary protobuf segment fetch |
| **Recommendations** | ✅ `bilibili_recommend` (feed) |

### Tools
- `video_search`, `recommendations`, `user_search`, `dynamic_feeds`, **`video_collections`**, `danmaku_retrieval`

### Why Runner-Up
- Only server exposing **collection/series (合集/季度) APIs** end-to-end
- Directly satisfies PRD `platform_metrics.collection_evidence_status`, `is_in_collection`, `series_name`, `season_id`
- PyPI-distributed, Python, active
- Lacks write tools, live tools, message tools vs Iseenope

---

## 5. Gaps (Across All Sites)

| Gap | Severity | Details |
|-----|----------|---------|
| **Canonical repos dead (C&D)** | Critical | SocialSisterYi (20.2k★) archived 2026-01-30; Nemo2011 (4.2k★) archived 2026-07-06. Both received lawyer letters (上海市弘安律师事务所). Live code = fragmented MCP servers + forks. |
| **No `space.bilibili.com/<uid>` string input** | High | All servers/tools accept numeric `uid`/`mid` only. Agent must parse URL. |
| **Coins (`投币`) not exposed** | High | No server documents `coins` in tool output (exists in `stat` but not surfaced). |
| **Shares not exposed** | High | No server returns `share` count (exists in API but not in tool schemas). |
| **WBI signing only explicit in sunwu51** | Medium | Most rely on `bilibili-api-python` internal signing; no standalone WBI utility on Glama/npm/PyPI. |
| **is_pinned / is_repost / is_promoted not surfaced** | Medium | Exist in dynamic/item API (`dynamic_type`, `orig_type`, `promotion`); need raw passthrough. |
| **Live-clip content_type not typed** | Medium | Live tools exist (`bilibili_live_info`, `bilibili_live_screenshot`) but output not mapped to `content_type: live_clip`. |
| **No browser automation fallback** | Medium | Only flyerhzm uses Playwright; others = cookie + HTTP signing. If 412/cookies expire, no fallback. |
| **No MCP resource aggregator** | Medium | Each server exposes narrow tools; no single call joins profile+posts+comments. |
| **Smithery: 0 Bilibili servers** | Operational | Despite `smithery.yaml` in repos, none resolve on smithery.ai (Vercel block + 404). |
| **Glama search broken** | Operational | `?q=bilibili` returns generic list; must scrape sitemap (`/sitemaps/mcp-servers/{2,4,5,6,7}.xml`). |
| **Legal risk for aggressive scraping** | Structural | Bilibili 2026 enforcement suggests only cookie-based, narrow-purpose survives. Heavy multi-account scraper = legal exposure. |

---

## 6. Key Technical Trade-offs Table

| Dimension | Iseenope (Glama) | adoresever (Glama) | SMYB5431 (Glama) | bilibili-api-python (PyPI) | bilibili-cli (PyPI) | bili-api (npm) | @renmu/bili-api (npm) |
|-----------|------------------|-------------------|------------------|---------------------------|---------------------|----------------|----------------------|
| **Coverage (PRD)** | ★★★★★ | ★★★★★ | ★★★★★ (collections) | ★★★★★ | ★★★★☆ | ★★★☆☆ (public only) | ★★★★★ |
| **Identity resolution** | UID only | UID only | UID + search | UID only | UID only | UID only | UID only |
| **Maintenance** | High (2026-08, TS) | High (2026-08, Py) | High (PyPI, Py) | High (monthly, GPL) | High (MIT, wraps SDK) | Low (2023, stale risk) | High (GPL, unstable API) |
| **Aggressiveness** | High (QR + cookies + write) | High (QR + cookies + publish) | Medium (read-only, cookies) | High (WBI + fingerprint) | High (browser cookie extract) | None (public API) | High (WBI + QR + upload) |
| **License** | MIT | MIT | MIT | GPL-3.0 | MIT | MIT | GPL |
| **Output** | MCP tools | MCP tools | MCP tools | Python SDK | CLI (YAML/JSON) | JS/TS lib | JS/TS lib |
| **Deployment** | MCP (stdio/SSE) | MCP (stdio/SSE) | MCP (stdio/SSE) | Python pkg | CLI / Python | npm pkg | npm pkg |
| **Unique strength** | 31 tools, write + live | Publish dynamic/video | Collections (合集) | 400+ endpoints | 3-tier auth, structured CLI | Zero auth, simple | Full auth + upload + collections |

---

## 7. Recommendation

| Use Case | Recommended Stack |
|----------|-------------------|
| **AI-agent / MCP workflow (full collection)** | **Iseenope/bilibili-mcp-server** (Glama) — 31 tools, QR login, write capable, active |
| **Collection/series (合集/季度) analysis** | **SMYB5431/bilibili-api-mcp-server** (Glama/PyPI) — only server with 合集 APIs |
| **Python pipeline (max control)** | **bilibili-api-python** (PyPI) — primary SDK, 400+ endpoints, WBI internal |
| **CLI / scheduled jobs (structured output)** | **bilibili-cli** (PyPI) — YAML/JSON, 3-tier auth, wraps SDK |
| **Read-only public data (zero auth)** | **bili-api** (npm) — simple, throttled, core fields only |
| **Full authenticated (Node/TS)** | **@renmu/bili-api** (npm) — WBI, QR, upload, collections; GPL + unstable interfaces |
| **Content publishing (dynamic/video)** | **adoresever/bilibili-mcp** (Glama) — only server with `bili_send_dynamic` + `bili_upload_video` |

**Critical path for PRD compliance**:
1. Parse `https://space.bilibili.com/<uid>` → numeric `uid` (trivial regex)
2. Add `+08:00` to `pubdate`/`published_at` (all APIs return CST Unix seconds)
3. For `coins`/`shares`: extend chosen server/tool to surface `stat.coin` and `stat.share`
4. For `is_pinned`/`is_repost`/`is_promoted`: parse `dynamic_type`/`orig_type`/`promotion` from dynamic/item API
5. For `live_clip`: map `bilibili_live_info` output to `content_type: live_clip`
6. Legal: prefer cookie-based narrow collectors; avoid distributed multi-account architectures