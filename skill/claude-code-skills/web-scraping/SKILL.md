---
name: web-scraping
description: Public web scraping and collection for public-social-account-analyzer. Use for platform collection adapters, Cookie handling, URL allowlist/canonicalization, browser fallback, rate limiting, and retry strategies.
---

# Web Scraping Skill

Scope: `skill/scripts/collect.py`, `skill/scripts/collectors/` adapters, `skill/scripts/collectors/cookie_loader.py`/`_cookie_storage.py`, `skill/scripts/collectors/browser_backend.py`, `skill/scripts/collectors/url_policy.py`, `skill/references/cookie-guide.md`.

## Invariants

- Collection adapters: `collectors/bilibili.py` (medialist + WBI `arc/search` fallback), `douyin.py` (SSR variants + `--all` bounded scrolling + optional browser fallback), `douyin_openapi.py` (post-OAuth), `weibo.py` (env-gated `WEIBO_COLLECTOR_ENABLED`), `xiaohongshu.py` (account-bound legacy/modern embedded profile state).
- Cookie handling: platform-isolated Cookie validation plus opt-in atomic `0600` cache storage and revocation (`cookie_loader.py`, `_cookie_storage.py`).
- Browser fallback: headless browser transport only, never persists cookies/headers/bodies (`browser_backend.py`, `_douyin_browser_transport.py`).
- URL allowlist/canonicalization: `url_policy.py`.
- Rate limiting and retry: bounded attempts via `bounded_attempt_runner.py`; platform-protection responses abort the current task (never invent success).
- `_canon_status_with_source`: missing/invalid `collection_status` → `PARTIAL` (never invented success).

## When to use

- Changing platform collection logic or adding a new platform adapter.
- Touching Cookie storage/revocation, URL policy, or browser fallback.
- Modifying rate-limiting, retry, or bounded-complete collection behavior.

## Verification

- `python3 -m pytest tests/ -q` full regression (platform tests mocked, no live network required).
- Local smoke (real network, public pages only): `python3 skill/scripts/collect.py <url> --limit 5 --out workspace/smoke`.
- `git diff --check` before commit. Never commit Cookies, OAuth tokens, or raw private data.
