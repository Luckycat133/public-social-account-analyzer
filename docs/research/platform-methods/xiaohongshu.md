# Xiaohongshu (小红书 / RedNote) — Consolidated Platform Reference

> **Source aggregation**: GitHub (8 repos), Clawhub (2 skills), PyPI (1 package). No Glama/Smithery or npm listings found as of 2026-08-05.

---

## 1. Executive Summary

| Dimension | Assessment |
|-----------|------------|
| **Best overall method** | **NanmiCoder/MediaCrawler** (GitHub) — de-facto standard multi-platform crawler (~30k stars), full PRD coverage for profile/posts/metrics, active maintenance 2025-2026. |
| **Runner-up** | **ReaJason/xhs** (GitHub + PyPI `xhs` package) — cleanest TypeScript/Python reference for X-s/X-t signing, structured JSON output, easier programmatic integration. |
| **Key trade-off** | MediaCrawler = maximum coverage + highest aggressiveness (CDP + QR login + monkey-patched signatures). ReaJason/xhs = cleaner API + lower maintenance surface but still requires cookie management. Both share the same fundamental fragility: X-s/X-t signature rotation every 30-60 days. |
| **MCP option** | **xpzouying/xiaohongshu-mcp** (Go + Rod) — most forked MCP, exposes 13 tools via MCP protocol, QR-code auto-login. Best for AI-agent workflows. |
| **Critical gap** | **Views field** — xhs note view counts are gated server-side; no public scraper reliably returns `views` (treat as nullable per PRD). **No nickname → red_id resolver** — all tools require numeric `red_id`/`user_id` upfront. |

---

## 2. Site-by-Site Findings Table

| Site | Best Finding | Aggressiveness | PRD Coverage (Profile/Post/Metrics) | Confidence | Notes |
|------|--------------|----------------|-------------------------------------|------------|-------|
| **GitHub** | NanmiCoder/MediaCrawler (~30k★) | Very High (CDP, monkey-patched sig, QR login, proxy pool) | ✅ Profile (bio, follows, followers, post_count, red_id, likes_and_favorites)<br>✅ Post (id, title, text, type, published_at, hashtags)<br>✅ Metrics (likes, favs, comments, shares; views limited) | High | De-facto standard; exports CSV/Excel/SQLite; account-ban risk acknowledged |
| | ReaJason/xhs (~3.2k★) | Medium-High (Cookie + X-s/X-t signing; browser mode) | ✅ Profile (name, red_id, bio, followers, follows, post_count, likes_and_favorites)<br>✅ Post (note_id, title, text, type, published_at, hashtags, ip_location)<br>✅ Metrics (likes, comments, shares, favorites; views partial) | High | Cleanest X-s/X-t reference; CLI returns structured JSON; `xhs-browser` for cookie mgmt |
| | xpzouying/xiaohongshu-mcp (~5k★) | High (QR login, Rod/CDP, signed cookies, MCP) | ✅ Profile (via `get_user_profile`: red_id, name, fan, follow, post_count, bio)<br>✅ Post (search, detail, feed: note_id, title, content, images, type, time, hashtags)<br>✅ Metrics (likes, comments, share_count; views partial) | High | Most-forked MCP; Docker-ready; 7+ downstream forks |
| **Clawhub** | `xhs-content-creator` (only live skill) | High (Playwright, login-session) | ❌ Profile<br>❌ Post (read)<br>❌ Metrics | Low | Publisher-only (Feishu DM → auto-publish); no read/collection tools |
| | `borye/xiaohongshu-mcp` (ghost) | High (XR-SN signing, cookie, MCP) | Likely ✅ Profile (via `user_profile`)<br>Likely ✅ Post (via `search_feeds`/`get_note`)<br>Likely ✅ Metrics (per-note) | Medium | Record not in public catalog (`skills:getBySlug`=null); README only via CSDN mirrors |
| **PyPI** | `xhs` v0.2.13 (ReaJason) | High (cookies + Playwright + Docker sign server) | ✅ Profile (`get_user_info`, `get_self_info`)<br>✅ Post (`get_note_by_id`, `get_user_notes`, `search`)<br>✅ Metrics (`get_note_comments`; likes/favs/shares/views in payload) | High | Only PyPI package; MIT; docs at reajason.github.io/xhs; last release 2024-04 |
| **Glama/Smithery** | *No xiaohongshu servers indexed* | — | — | — | No entries found on either registry |
| **npm** | *No xiaohongshu packages found* | — | — | — | Search returns zero relevant packages |

---

## 3. Best Method Detailed: NanmiCoder/MediaCrawler

**Name**: MediaCrawler  
**Source**: GitHub — https://github.com/NanmiCoder/MediaCrawler  
**Type**: Python + Playwright + AsyncIO + Redis multi-platform crawler  
**License**: MIT (assumed; no explicit license file but open source)

### PRD Coverage
| PRD Block | Fields | Coverage |
|-----------|--------|----------|
| **Profile** | `account_id` (red_id), `account_name`, `bio`, `followers`, `following`, `post_count`, `platform_metrics.likes_and_favorites`, `platform_metrics.red_id` | ✅ All via `--type creator` |
| **Post** | `post_id` (note_id), `post_url`, `title`, `content_type`, `published_at`, `text`, `hashtags`, `is_pinned` | ✅ All via `--type detail` / `--type search` |
| **Metrics** | `likes`, `favorites`, `comments`, `shares`, `views` | ⚠️ `views` limited (xhs rarely exposes); others ✅ |

### How to Use
```bash
# Setup
uv sync
uv run playwright install

# Search notes by keyword
python main.py --platform xhs --lt qrcode --type search --keyword "your keyword"

# Get single note detail (comments + metrics)
python main.py --platform xhs --lt qrcode --type detail --note_id "note_id_here"

# Get all posts by creator (profile + post list)
python main.py --platform xhs --lt qrcode --type creator --user_id "red_id_here"
```
**Output**: CSV / Excel / SQLite per run.  
**Auth**: QR-code login (scans via embedded Chrome). Cookie persistence supported.  
**Rate limits**: Built-in delays; proxy pool recommended for scale.  
**Maintenance**: Active (commits 2025-2026). Signature drift tracked via issues.

### Aggressiveness Profile
- **Browser**: Real Chrome via CDP (Playwright)
- **Signing**: Monkey-patches third-party signature libs at runtime
- **Login**: QR-code (no password handling)
- **Anti-bot**: IP proxy pool support; explicit account-ban warning in README

---

## 4. Runner-Up: ReaJason/xhs (GitHub + PyPI `xhs`)

**Name**: xhs (TypeScript toolkit) / `xhs` (PyPI package)  
**Source**: GitHub — https://github.com/ReaJason/xhs | PyPI — https://pypi.org/project/xhs/  
**Type**: TypeScript CLI + Python SDK (same author)  
**License**: MIT

### PRD Coverage
| PRD Block | Coverage |
|-----------|----------|
| Profile | ✅ All fields via `user` / `creator` commands |
| Post | ✅ All fields via `note` / `search` / `creator` commands |
| Metrics | ✅ likes, comments, shares, favorites; ⚠️ views sometimes gated |

### How to Use (TypeScript CLI)
```bash
npm install
# Cookie management via companion `xhs-browser` or env
npx xhs note <note_id>           # Single note detail
npx xhs user <user_id>           # Profile
npx xhs creator <user_id>        # Profile + post list
npx xhs comments <note_id>       # Comments
npx xhs search <keyword>         # Keyword search
```
**Output**: Structured JSON (maps cleanly to PRD).  
**Auth**: Cookie-based (`xhs-browser` manages Chrome profile).  
**Signing**: Pure-TS reverse-engineered X-s/X-t implementation (reference quality).  
**Maintenance**: Active 2025-2026; tracks signature changes via issues.

### Why Runner-Up
- Cleaner programmatic interface (JSON output, TypeScript types)
- Lower aggressiveness than MediaCrawler (no CDP monkey-patching)
- Same fundamental fragility (X-s/X-t rotation)
- PyPI package `xhs` provides Python binding with identical coverage

---

## 5. Gaps (Across All Sites)

| Gap | Severity | Details |
|-----|----------|---------|
| **Views field unavailable** | High | xhs note view counts gated server-side; no public endpoint returns it. PRD must treat as nullable. |
| **No nickname → red_id resolver** | High | All tools require numeric `red_id`/`user_id`. The `https://www.xiaohongshu.com/user/profile/<red_id>` URL works but nickname search is not a first-class feature in any repo. |
| **Signature drift (X-s/X-t)** | High | Payload dictionary (~44 fields) rotates every 30-60 days. Any solution older than ~60 days risks `-100 X-Sign-Verify-Fail`. ReaJason and xpzouying track via issues. |
| **Account-ban risk** | Medium | MediaCrawler explicitly warns aggressive crawls burn accounts. PRD allows aggressive but expect 429, CAPTCHA, silent X-s failures. |
| **English documentation** | Low | Almost all docs Chinese (CSDN, cnblogs); English coverage is third-party blogs only. |
| **No official API route** | Structural | All methods reverse-engineered against web bundle/mini-app. No GraphQL/REST public API exists. |
| **MCP servers prioritize write over read** | Medium | Most MCP forks (jansfer, T-bagwell, flippancy, puyujian, tclawde) focus on publish/comment/like; profile/analytics tools are secondary. |
| **Glama/Smithery/npm empty** | Medium | No registry listings for xiaohongshu; ecosystem entirely GitHub-centric. |

---

## 6. Key Technical Trade-offs Table

| Dimension | MediaCrawler | ReaJason/xhs (TS) | xhs (PyPI) | xpzouying/xiaohongshu-mcp |
|-----------|--------------|-------------------|------------|---------------------------|
| **Coverage (PRD fields)** | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★☆ |
| **Identity resolution** | ❌ Requires red_id | ❌ Requires red_id | ❌ Requires red_id | ❌ Requires red_id |
| **Maintenance burden** | High (multi-platform, large codebase) | Medium (focused, clean TS) | Medium (Python wrapper) | Medium (Go + Rod, active forks) |
| **Aggressiveness** | Very High (CDP, monkey-patch, proxy) | Medium-High (cookie + custom signing) | High (Playwright + sign server) | High (QR login, Rod browser) |
| **License risk** | MIT | MIT | MIT | MIT |
| **Output format** | CSV/Excel/SQLite | JSON (CLI) | Python objects / JSON | MCP protocol (tools) |
| **Best for** | Bulk collection, multi-platform | Programmatic integration, type safety | Python pipelines | AI-agent workflows (MCP) |
| **Deployment** | Local/Server (Python) | Local/Server (Node/Python) | Python package | Docker (MCP server) |
| **Signature tracking** | Via issues (community) | Via issues (author maintains) | Same as TS | Via forks/issues |

---

## 7. Recommendation

| Use Case | Recommended Stack |
|----------|-------------------|
| **One-off bulk collection** | MediaCrawler (`--type creator` + `--type detail`) |
| **Scheduled pipeline (Python)** | PyPI `xhs` package + cookie rotation cron |
| **Scheduled pipeline (TypeScript/Node)** | ReaJason/xhs CLI + `xhs-browser` cookie manager |
| **AI-agent / LLM tooling** | xpzouying/xiaohongshu-mcp (Docker) + MCP client |
| **Minimal maintenance** | ReaJason/xhs (cleanest signing reference; easiest to patch) |

**Critical path for PRD compliance**: Build a `nickname → red_id` resolver (scrape `https://www.xiaohongshu.com/search_result?keyword=<nickname>` or use MediaCrawler's search) and wrap the chosen collector with a `views: null` default.