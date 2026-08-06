# Weibo (微博 / Sina Weibo) — Consolidated Platform Reference

> **Source aggregation**: GitHub (8 repos), Clawhub (2 skills), Glama (0) / Smithery (3), PyPI (5 packages), npm (6 packages).

---

## 1. Executive Summary

| Dimension | Assessment |
|-----------|------------|
| **Best overall method (unofficial, aggressive)** | **Python3WebSpider/WeiboCrawler** (GitHub) — production-grade Scrapy, mobile PWA headers (`MWeibo-Pwa:1`), containerid refinement (`100505{uid}` + `107603{uid}`), long-text fallback, Docker + cookie pool. Best PRD coverage for profile/posts/metrics. |
| **Best overall method (official/legal)** | **weibo-mcp** (npm, `wangcch/weibo-mcp`) — only package using official Weibo OpenAPI (OAuth2). Full PRD coverage, sustainable, but requires developer approval (app_id/secret). |
| **Best MCP server (unofficial)** | **@mseep/mcp-server-weibo** (npm, via MseeP) — auto visitor-pass cookie acquisition, MCP-native tools (`get_profile`, `get_feeds`, `search_users`), anti-detection delays. |
| **Best TypeScript library** | **@hkai-ai/weibo-api** (npm) — typed wrapper around `m.weibo.cn` mobile AJAX, `searchForUserUID()` resolves nickname→UID, active Jun 2025. |
| **Best PyPI package** | **weibo-spider** (dataabc/weiboSpider, v0.3.0) — cookie + mobile AJAX, accepts `weibo.com/u/<uid>` OR `weibo.com/<name>`, resolves name→UID via profile page scrape, downloads media. Last release 2021. |
| **Key trade-off** | **Official API** (weibo-mcp) = legal, stable, rate-limited, requires approval. **Mobile AJAX** (Python3WebSpider, @hkai-ai, @mseep) = full data access, no approval, but cookies rotate (~24h), endpoints undocumented, may break. **HTML scrape** (dataabc, Clawhub weibo-scraper) = no login needed for posts, but no metrics, fragile selectors. |
| **Critical gap** | **Views (播放量) not exposed by any package** — Weibo hides view counts on web; only available via private `statuses/show` with special params or internal API. **No package validates nickname→UID via SSR + profile/info domain match** (PRD identity binding). **No active maintenance** — latest PyPI release Dec 2021; npm/GitHub more current but unofficial. |

---

## 2. Site-by-Site Findings Table

| Site | Best Finding | Aggressiveness | PRD Coverage (Profile/Post/Metrics) | Confidence | Notes |
|------|--------------|----------------|-------------------------------------|------------|-------|
| **GitHub** | Python3WebSpider/WeiboCrawler | High (m.weibo.cn PWA headers, containerid refinement, long-text fallback, cookie pool, Docker) | ✅ Profile (100505 container: id, name, verified, followers, friends, statuses, description)<br>✅ Post (id, text, created_at, source, reposts, comments, attitudes, pics, video, retweeted_status)<br>✅ Metrics (reposts, comments, attitudes; views nullable) | High | Cui Qingcai (Python3WebSpider author); Scrapy; container-pairing pattern matches PRD domain match |
| | nghuyong/WeiboSpider (~6.5k★) | High (cookie pool, IP pool, m.weibo.cn AJAX, Docker distributed) | ✅ Profile (all fields)<br>✅ Post (all fields incl. long_text, retweeted_status)<br>✅ Metrics (reposts, comments, attitudes; views ❌) | High | De-facto reference; master/simple branches; cookie pool via login.py; slowing 2023 |
| | dataabc/weibo-crawler (~6.1k★) | Medium (cookie-free browse mode for posts, optional cookie for fan list) | ✅ Profile (all + birthday, location, education, work)<br>✅ Post (all + Live Photo, first-level comments)<br>✅ Metrics (reposts, comments, attitudes; views ❌) | High | CSV/JSON/MySQL/MongoDB/SQLite; media downloads; UID-input only |
| | qinyuanpei/mcp-server-weibo | Medium (MCP, cookie-based, auto-cookie acquisition claimed) | ⚠️ Profile (partial)<br>⚠️ Post (partial)<br>⚠️ Metrics (partial) | Medium | ~50 stars, 2025; lacks PWA headers, containerid refinement, long-text fallback |
| **Clawhub** | weibo-scraper (rrrrrredy) | Medium (visitor cookie + Playwright, no login) | ❌ Profile (overview only)<br>⚠️ Post (text + time + media indicator)<br>❌ Metrics | Medium | Bing search `@username site:weibo.com` → extract UID → Playwright render. No SSR domain match. |
| | multi-post (jeffchang2024) | High (Chrome user-profile, publishing only) | N/A (publisher) | Low | Multi-platform publisher; Weibo compose page; 140 char display / 2000 actual |
| **Glama** | *No Weibo servers indexed* | — | — | — | 0 results on glama.ai |
| **Smithery** | @kinh0ly/weibo-mcp-server | Low (public HTML scrape, lxml+requests) | ⚠️ Unknown<br>⚠️ Unknown<br>⚠️ Unknown | Low | Tiny repo, 0 releases, sparse README; do not rely without code audit |
| | @lowin/weibo-api-mcp-server | None (likely legacy OpenAPI) | ⚠️ Partial (open API fields)<br>⚠️ Partial<br>⚠️ Partial | Low | No public GitHub mirror; inferred from name; open API deprecated |
| | @qingyun/mcp-server-weibo-trending | None (trending only) | ❌ Profile<br>❌ Post<br>❌ Metrics | Medium | Narrow scope: hot-search list only; not useful for PRD |
| **PyPI** | weibo-spider (v0.3.0) | Medium (cookie + m.weibo.cn AJAX) | ✅ Profile (all)<br>✅ Post (all incl. long_text)<br>✅ Metrics (attitudes, comments, reposts; views/favs ❌) | Medium | Last release Dec 2021; accepts `weibo.com/u/<uid>` OR `weibo.com/<name>`; avoids viewer-UID trap |
| | weibo-crawler (v1.0) | Medium (cookie + web AJAX endpoints) | ✅ Profile (basic)<br>✅ Post (date-range filter)<br>✅ Metrics (attitudes, comments, reposts) | Low | Single release May 2021; minimal docs; no DB/media download |
| | weibo / sinaweibopy3 / weibopy | None (official API v2, deprecated) | ✅ Profile (if UID known)<br>✅ Post (if UID known)<br>✅ Metrics (attitudes, comments, reposts) | Low | API v2 shut down 2020+; abandoned 2014-2019; Python 2.7 era |
| **npm** | weibo-mcp (wangcch/weibo-mcp) | Low (official OAuth2) | ✅✅✅ Full PRD (views nullable) | High | Only official API package; requires app_id/secret; auto token refresh |
| | @hkai-ai/weibo-api | Medium (m.weibo.cn mobile AJAX, cookies) | ✅ Profile (searchForUserUID resolves name→UID)<br>✅ Post (rawText, pics, retweetWeiboInfo)<br>✅ Metrics (attitudes, comments, retweets; views/favs null) | Medium | TypeScript; active Jun 2025; visitor pass or browser cookies |
| | @mseep/mcp-server-weibo | Medium (auto visitor-pass + web scraping) | ✅ Profile (get_profile)<br>✅ Post (get_feeds)<br>✅ Metrics (likes, comments, shares; views/favs null) | Medium | MCP-native; auto-cookie; "learning/research only" disclaimer |

---

## 3. Best Method Detailed: Python3WebSpider/WeiboCrawler (GitHub)

**Name**: WeiboCrawler  
**Source**: GitHub — https://github.com/Python3WebSpider/WeiboCrawler  
**Author**: Cui Qingcai (崔庆才, Python3WebSpider)  
**Type**: Scrapy spider (production-grade)  
**License**: MIT (assumed)

### PRD Coverage
| PRD Block | Fields | Coverage |
|-----------|--------|----------|
| **Profile** | `account_id` (UID), `account_name`, `bio` (description), `verified` (verified_type), `followers` (followers_count), `following` (friends_count), `post_count` (statuses_count), `gender`, `location`, `birthday` | ✅ via `100505{uid}` container (user block) |
| **Post** | `post_id` (mid/idstr), `post_url`, `published_at` (+08:00 needed), `content_type` (detect: text/image/video), `text` (HTML-stripped), `hashtags` (parse from text), `is_repost` (retweeted_status), `is_pinned` (heuristic), `is_promoted` (❌) | ✅ via `107603{uid}` container + long-text fallback |
| **Metrics** | `likes` (attitudes_count), `comments` (comments_count), `shares` (reposts_count), `views` (❌), `favorites` (null per PRD) | ✅ reposts/comments/attitudes; ❌ views |

### Key Technical Approach
- **Endpoints**: `m.weibo.cn/api/container/getIndex?containerid=100505{uid}` (profile) + `107603{uid}` (posts)
- **Headers**: `MWeibo-Pwa: 1`, `X-Requested-With: XMLHttpRequest` (critical for JSON response)
- **Containerid refinement**: Parses `tabsInfo.tabs` to get correct `containerid` (handles tab changes)
- **Long-text fallback**: `https://m.weibo.cn/detail/{bid}` HTML scrape + `/api/statuses/longtext` API
- **Auth**: Cookie pool (Docker + Redis ready); `SUB` + `SUBP` cookies required
- **Identity binding**: Uses both containers; `data.cards[].mblog.user.id` matches requested UID — implements PRD domain match implicitly

### How to Use
```bash
git clone https://github.com/Python3WebSpider/WeiboCrawler
cd WeiboCrawler
pip install -r requirements.txt

# Configure cookie and user_id_list in settings
# cookie: valid SUB/SUBP from logged-in weibo.com session
# user_id_list: ["1234567890", "..."]

scrapy crawl weibo
# Output: JSON Lines per user (profile + posts + metrics)
```

**Aggressiveness**: High — mobile PWA headers, containerid refinement, long-text fallback, cookie pool, Docker.  
**Maintenance**: Active (2024 commits); author maintains Python3WebSpider ecosystem.  
**Output**: JSON Lines (structured, maps to PRD).  
**Timezone**: `created_at` = "Wed Aug 05 09:09 +0800 2026" — needs ISO-8601 +08:00 normalization.

---

## 4. Runner-Up: weibo-mcp (npm, Official OpenAPI)

**Name**: weibo-mcp  
**Source**: npm — https://npmjs.com/package/weibo-mcp  
**GitHub**: https://github.com/wangcch/weibo-mcp  
**Type**: MCP server wrapping Weibo Open Platform REST APIs  
**License**: MIT

### PRD Coverage
| PRD Block | Coverage |
|-----------|----------|
| **Profile** | ✅ All fields via `users/show` + search |
| **Post** | ✅ All fields via `statuses/*` (incl. `is_pinned`, `is_repost`, `is_promoted`, `hashtags`) |
| **Metrics** | ✅ `views` (nullable), `likes`, `comments`, `shares`; `favorites`=null |
| **Identity binding** | ✅ Supports `https://weibo.com/u/<uid>` and `https://weibo.com/<name>` via official search + `users/show` |

### How to Use
```bash
# Requires Weibo Open Platform app (developer approval)
# Get app_id, app_secret, then OAuth2 flow for access_token

npx weibo-mcp  # or add to MCP client config
{
  "mcpServers": {
    "weibo": {
      "command": "npx",
      "args": ["-y", "weibo-mcp"],
      "env": {
        "WEIBO_APP_ID": "your_app_id",
        "WEIBO_APP_SECRET": "your_app_secret",
        "WEIBO_ACCESS_TOKEN": "oauth_token"
      }
    }
  }
}
```

**Advantages**: Legal, sustainable, official support, auto token refresh, full PRD fields.  
**Disadvantages**: Requires ByteDance-level developer approval (business license, use-case review); rate-limited; no aggressive collection.

---

## 5. Gaps (Across All Sites)

| Gap | Severity | Details |
|-----|----------|---------|
| **Views (播放量) not collected** | Critical | Weibo mobile/web APIs do not expose `views_count` on profile posts container. Only post-detail page (`/detail/{bid}`) sometimes returns it. No repo scrapes detail page systematically. |
| **No SSR + profile/info domain match** | High | PRD requires `weibo.com/<name>` → SSR → `weibo.com/u/<uid>` → verify `data.user.id` matches. No package implements this full chain. Python3WebSpider comes closest (container pairing) but doesn't assert equality. |
| **Nickname → UID resolution fragile** | High | All unofficial methods: Bing search (Clawhub), profile page scrape (dataabc), container pairing (Python3WebSpider). None are robust against privacy-restricted or non-indexed accounts. |
| **No active PyPI maintenance** | High | Latest PyPI release Dec 2021 (`weibo-spider` v0.3.0). GitHub/npm more current but unofficial. |
| **+08:00 timezone normalization missing** | Medium | Weibo returns `created_at` as localized string ("Wed Aug 05 09:09 +0800 2026"). No repo emits ISO-8601 with explicit `+08:00`. |
| **is_promoted (ad) detection absent** | Medium | No repo parses promoted/ad banner from HTML. `mblog` JSON has no `promotion` field. |
| **hashtags extraction regex-only** | Medium | `mblog.text` contains HTML `<a href="/n/topic/...">` for hashtags; no repo parses to structured array. |
| **No browser-automation fallback** | Medium | All repos use cookie/UA tricks; none use Playwright/Selenium for search, fan-list pagination, or profile-page HTML for views. |
| **Cookie sustainability** | Medium | Visitor pass / browser cookies rotate (~24h). Only `weibo-mcp` (official) has sustainable auth. |
| **Glama: 0 Weibo servers** | Operational | No Weibo MCP on glama.ai; must use Smithery (3 servers, low confidence) or self-host. |
| **Smithery servers unverifiable** | Operational | Direct fetch blocked; details inferred from snippets + GitHub cross-ref. Code audit required. |
| **Favorites/bookmarks** | Low | PRD mandates `null`; correctly unimplemented. |
| **Historical pagination limited** | Medium | Only `weibo-client` (CLI) and `@mseep/mcp-server-weibo` support deep cursor pagination; others return latest ~10. |

---

## 6. Key Technical Trade-offs Table

| Dimension | Python3WebSpider (GitHub) | nghuyong/WeiboSpider (GitHub) | dataabc/weibo-crawler (GitHub) | weibo-mcp (npm, Official) | @hkai-ai/weibo-api (npm) | @mseep/mcp-server-weibo (npm) | weibo-spider (PyPI) |
|-----------|---------------------------|------------------------------|-------------------------------|---------------------------|--------------------------|------------------------------|---------------------|
| **Coverage (PRD)** | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★☆ |
| **Identity resolution** | Container pairing (implicit) | UID only (name→UID external) | UID + name (profile scrape) | ✅ Official search + users/show | ✅ `searchForUserUID()` | ✅ `search_users()` | ✅ Profile page scrape |
| **Maintenance** | High (2024, active author) | Medium (slowing 2023) | High (2023, active) | High (official) | High (Jun 2025) | Medium (2025, research only) | Low (Dec 2021) |
| **Aggressiveness** | High (PWA headers, containerid, long-text) | High (cookie/IP pool, Docker) | Medium (cookie-free browse) | Low (OAuth2) | Medium (mobile AJAX, cookies) | Medium (visitor pass + scrape) | Medium (cookie + AJAX) |
| **License** | MIT | MIT | MIT | MIT | MIT | MIT | MIT |
| **Output** | JSON Lines (Scrapy) | CSV / MongoDB | CSV / JSON / SQL / Mongo | MCP tools | TypeScript SDK | MCP tools | TXT/CSV/JSON/SQL |
| **Deployment** | Scrapy / Docker | Python / Docker | Python | npm / MCP | npm / MCP | npm / MCP | Python |
| **Views metric** | ❌ | ❌ | ❌ | ⚠️ Nullable | ❌ | ❌ | ❌ |
| **Best for** | Production pipeline (Scrapy) | Distributed bulk (master branch) | Simple one-off + media | Legal/compliance | TS/Node pipelines | AI-agent (MCP) | Quick Python script |

---

## 7. Recommendation

| Use Case | Recommended Stack |
|----------|-------------------|
| **Production Python pipeline (max data)** | **Python3WebSpider/WeiboCrawler** — Scrapy, PWA headers, container pairing, long-text fallback, Docker-ready |
| **AI-agent / MCP workflow** | **@mseep/mcp-server-weibo** (npm) — auto visitor-pass, MCP tools, anti-detection; or self-host **qinyuanpei/mcp-server-weibo** (GitHub) with PWA headers added |
| **Legal/compliance required** | **weibo-mcp** (npm) — official OpenAPI, full PRD, sustainable; apply for Weibo Open Platform approval |
| **TypeScript/Node pipeline** | **@hkai-ai/weibo-api** — typed, `searchForUserUID()`, mobile AJAX, active Jun 2025 |
| **One-off collection + media download** | **dataabc/weibo-crawler** — cookie-free browse mode, CSV/JSON/SQL, downloads images/videos/Live Photo |
| **Distributed bulk (high volume)** | **nghuyong/WeiboSpider (master branch)** — cookie pool, IP pool, MongoDB+Redis, Docker |

**Critical path for PRD compliance**:
1. Implement `nickname → UID` resolver: `https://m.weibo.cn/n/{screen_name}` → 302 → extract UID → verify via `100505{uid}` container `user.id` match
2. Add `+08:00` to `created_at` (parse localized string → ISO-8601 with offset)
3. Extract `hashtags` from `mblog.text` HTML anchors (`/n/topic/...`)
4. Add `is_promoted` heuristic: check `mblog.promotion` or HTML banner on detail page
5. For `views`: accept `null` (PRD nullable) — no reliable source exists
6. Cookie rotation: schedule daily headless login or maintain cookie pool (Redis)
7. For `is_pinned`: check `mblog.isTop` or profile page `top` field