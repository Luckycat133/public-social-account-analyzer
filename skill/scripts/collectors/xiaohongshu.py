"""Xiaohongshu public-page collector with a no-bypass evidence contract.

The collector reads only JSON state already embedded in a directly opened
public profile or note page.  It never calls signed/private endpoints, follows
no share redirects, and stops when the page requires login or verification.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from ._constants import BEIJING_TZ, PUBLIC_LIMIT_DEFAULT, validate_public_limit
from ._utils import extract_hashtags, now_iso, parse_int, ts_to_iso
from .base import BaseCollector
from .url_policy import canonical_item_url, canonical_profile_url


PLATFORM = "xiaohongshu"
LOGIN_REQUIRED = "LOGIN_REQUIRED"
VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
PARSER_FAILED = "PARSER_FAILED"
NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_STATE_SCRIPT = re.compile(
    r"<script[^>]+id=[\"'](?:__XHS_INITIAL_STATE__|__NEXT_DATA__)[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_NON_VISIBLE_BLOCK = re.compile(
    r"<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")


class XiaohongshuError(RuntimeError):
    """Structured public-page failure for safe orchestration stop reasons."""

    def __init__(self, stop_reason: str, message: str):
        super().__init__(f"[{stop_reason}] {message}")
        self.stop_reason = stop_reason


def _cookie_header(cookie_records: tuple[dict[str, Any], ...]) -> str | None:
    """Build one in-memory Cookie header without persisting session values."""
    values = [
        f"{record['name']}={record['value']}"
        for record in cookie_records
        if isinstance(record, dict)
        and isinstance(record.get("name"), str)
        and isinstance(record.get("value"), str)
    ]
    return "; ".join(values) or None


def _http_get_text(
    url: str, cookie_records: tuple[dict[str, Any], ...] = ()
) -> str:
    """Fetch one direct page with an optional in-memory user session, never bypassing protection."""
    headers = dict(_HEADERS)
    cookie_header = _cookie_header(cookie_records)
    if cookie_header is not None:
        headers["Cookie"] = cookie_header
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise XiaohongshuError(
                LOGIN_REQUIRED, f"小红书公开页面要求登录或验证 (HTTP {error.code})"
            ) from error
        if error.code == 404:
            raise XiaohongshuError(ACCOUNT_UNAVAILABLE, "小红书账号或笔记不存在") from error
        raise XiaohongshuError(
            ACCESS_RESTRICTED,
            f"小红书公开页面访问受限 (HTTP {error.code})",
        ) from error
    except urllib.error.URLError as error:
        raise XiaohongshuError(ACCESS_RESTRICTED, "小红书公开页面网络不可达") from error


def _browser_rendered_html(
    url: str, cookie_records: tuple[dict[str, Any], ...]
) -> str:
    """Render one direct page in a temporary browser without API retries."""
    from .browser_backend import BrowserError, BrowserSession

    try:
        with BrowserSession() as session:
            session.set_cookie_records(cookie_records)
            return session.navigate_and_get_html(url)
    except BrowserError as error:
        raise XiaohongshuError(
            ACCESS_RESTRICTED, "小红书浏览器页面无法加载"
        ) from error


def _page_protection_reason(page: str) -> str | None:
    """Classify visible page protection before attempting any state parsing."""
    visible = html.unescape(_TAG.sub(" ", _NON_VISIBLE_BLOCK.sub(" ", page)))
    lowered = visible.lower()
    if any(marker in visible or marker in lowered for marker in (
        "验证码", "滑块", "captcha",
    )):
        return VERIFICATION_REQUIRED
    if any(marker in visible or marker in lowered for marker in (
        "请登录", "登录后", "扫码登录", "sign in", "log in",
    )):
        return LOGIN_REQUIRED
    return None


def _find_state(value: Any) -> dict[str, Any] | None:
    """Find one page-state object containing a public user and/or note list."""
    if isinstance(value, dict):
        if (
            isinstance(value.get("user"), dict)
            and isinstance(value.get("notes"), list)
        ):
            return value
        for child in value.values():
            state = _find_state(child)
            if state is not None:
                return state
    elif isinstance(value, list):
        for child in value:
            state = _find_state(child)
            if state is not None:
                return state
    return None


def _parse_page_state(page: str) -> dict[str, Any]:
    protection_reason = _page_protection_reason(page)
    if protection_reason is not None:
        raise XiaohongshuError(protection_reason, "小红书页面要求登录或验证")
    for match in _STATE_SCRIPT.finditer(page):
        try:
            parsed = json.loads(html.unescape(match.group(1)).strip())
        except json.JSONDecodeError:
            continue
        state = _find_state(parsed)
        if state is not None:
            return state
    raise XiaohongshuError(
        PARSER_FAILED, "小红书公开页面未提供可核验的嵌入账号与笔记数据"
    )


def _page_state(
    profile_url: str,
    cookie_records: tuple[dict[str, Any], ...] = (),
    browser_fallback: bool = True,
) -> dict[str, Any]:
    try:
        if cookie_records:
            return _parse_page_state(_http_get_text(profile_url, cookie_records))
        return _parse_page_state(_http_get_text(profile_url))
    except XiaohongshuError as error:
        if not (
            cookie_records
            and browser_fallback
            and error.stop_reason in {LOGIN_REQUIRED, PARSER_FAILED}
        ):
            raise
    return _parse_page_state(_browser_rendered_html(profile_url, cookie_records))


def _note_id(note: dict[str, Any]) -> str | None:
    value = note.get("noteId", note.get("id"))
    if not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _published_at(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ts_to_iso(value)
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ).isoformat()


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if (
        isinstance(value, str)
        and value.strip().lower() in {"0", "1", "true", "false"}
    ):
        return value.strip().lower() in {"1", "true"}
    return None


def _raw_note(note: dict[str, Any]) -> dict[str, Any] | None:
    note_id = _note_id(note)
    if note_id is None:
        return None
    note_url = canonical_item_url(
        PLATFORM, f"https://www.xiaohongshu.com/explore/{note_id}", note_id
    )
    if note_url is None:
        return None
    title = note.get("title") if isinstance(note.get("title"), str) else None
    text = note.get("desc", note.get("content"))
    text = text if isinstance(text, str) else None
    note_type = note.get("type")
    content_type = "video" if note_type in {"video", "vide"} else "image_text"
    views = parse_int(note.get("viewCount"))
    likes = parse_int(note.get("likedCount", note.get("likeCount")))
    favorites = parse_int(note.get("collectedCount", note.get("collectCount")))
    comments = parse_int(note.get("commentCount"))
    shares = parse_int(note.get("shareCount"))
    return {
        "platform": PLATFORM,
        "post_id": note_id,
        "post_url": note_url,
        "published_at": _published_at(note.get("time", note.get("publishTime"))),
        "content_type": content_type,
        "title": title,
        "text": text,
        "duration_seconds": parse_int(note.get("duration")),
        "hashtags": extract_hashtags(title, text),
        "is_pinned": _optional_bool(note.get("isTop")),
        "is_repost": _optional_bool(note.get("isRepost")),
        "is_promoted": _optional_bool(note.get("isPromoted")),
        "views": views,
        "likes": likes,
        "comments": comments,
        "favorites": favorites,
        "shares": shares,
        "coins": None,
        "danmaku": None,
        "collection_status": "SUCCESS",
        "collected_at": now_iso(),
        "source_url": note_url,
        "field_visibility": {
            "views": "visible" if views is not None else "hidden",
            "likes": "visible" if likes is not None else "hidden",
            "comments": "visible" if comments is not None else "hidden",
            "favorites": "visible" if favorites is not None else "hidden",
            "shares": "visible" if shares is not None else "hidden",
        },
        "platform_metrics": {"note_type": note_type},
    }


class XiaohongshuCollector(BaseCollector):
    """Collect public fields embedded in one directly opened profile page."""

    platform = PLATFORM

    def __init__(
        self,
        cookie_records: tuple[dict[str, Any], ...] = (),
        browser_fallback: bool = True,
    ):
        """Use an already-sanitized, user-authorized session only in memory."""
        self._cookie_records = tuple(cookie_records)
        self._browser_fallback = bool(browser_fallback)

    def _page_state(self, profile_url: str) -> dict[str, Any]:
        return _page_state(
            profile_url,
            self._cookie_records,
            browser_fallback=self._browser_fallback,
        )

    def _get_text(self, url: str) -> str:
        if self._cookie_records:
            return _http_get_text(url, self._cookie_records)
        return _http_get_text(url)

    def supports(self, url: str) -> bool:
        return canonical_profile_url(PLATFORM, url) is not None

    def check_access(self, url: str) -> dict[str, Any]:
        canonical = canonical_profile_url(PLATFORM, url)
        if canonical is None:
            raise XiaohongshuError(ACCOUNT_UNAVAILABLE, "不支持的小红书公开账号 URL")
        state = self._page_state(canonical)
        if not state.get("user"):
            raise XiaohongshuError(ACCOUNT_UNAVAILABLE, "小红书公开页面未提供账号资料")
        return {"accessible": True, "status": "ok", "stop_reason": None}

    def collect_profile(self, url: str) -> dict[str, Any]:
        canonical = canonical_profile_url(PLATFORM, url)
        if canonical is None:
            raise XiaohongshuError(ACCOUNT_UNAVAILABLE, "不支持的小红书公开账号 URL")
        user = self._page_state(canonical).get("user")
        if not isinstance(user, dict):
            raise XiaohongshuError(ACCOUNT_UNAVAILABLE, "小红书公开页面未提供账号资料")
        followers = parse_int(user.get("fans", user.get("followerCount")))
        post_count = parse_int(user.get("noteCount", user.get("notesCount")))
        return self.normalize_profile({
            "platform": PLATFORM,
            "account_id": str(user.get("userId") or user.get("id") or "") or None,
            "account_name": user.get("nickname", user.get("name")),
            "profile_url": canonical,
            "bio": user.get("desc", user.get("description")),
            "verified": _optional_bool(user.get("verified")),
            "followers": followers,
            "post_count": post_count,
            "platform_metrics": {
                "following": parse_int(
                    user.get("follows", user.get("followingCount"))
                ),
                "red_id": user.get("redId"),
            },
            "field_visibility": {
                "followers": "visible" if followers is not None else "hidden",
                "post_count": "visible" if post_count is not None else "hidden",
            },
            "collected_at": now_iso(),
        })

    def collect_post_list(
        self,
        url: str,
        limit: int = PUBLIC_LIMIT_DEFAULT,
        date_range: tuple[str | None, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        canonical = canonical_profile_url(PLATFORM, url)
        if canonical is None:
            raise XiaohongshuError(ACCOUNT_UNAVAILABLE, "不支持的小红书公开账号 URL")
        limit = validate_public_limit(limit)
        notes = self._page_state(canonical).get("notes")
        if not isinstance(notes, list):
            raise XiaohongshuError(PARSER_FAILED, "小红书公开页面未提供笔记列表")
        posts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for note in notes:
            if not isinstance(note, dict):
                continue
            raw = _raw_note(note)
            if raw is None or raw["post_id"] in seen:
                continue
            published_at = raw.get("published_at")
            if date_range and published_at is not None:
                start, end = date_range
                if (start and published_at < start) or (end and published_at > end):
                    continue
            seen.add(raw["post_id"])
            posts.append(self.normalize_post(raw))
            if len(posts) >= limit:
                break
        if not posts:
            raise XiaohongshuError(NO_PUBLIC_CONTENT, "小红书公开页面没有可核验笔记")
        return posts

    def collect_post_detail(self, post_url: str) -> dict[str, Any]:
        canonical = canonical_item_url(PLATFORM, post_url)
        if canonical is None:
            raise XiaohongshuError(PARSER_FAILED, "不支持的小红书公开笔记 URL")
        page = self._get_text(canonical)
        state = _parse_page_state(page)
        notes = state.get("notes")
        if not isinstance(notes, list):
            raise XiaohongshuError(PARSER_FAILED, "小红书公开笔记页面未提供可核验数据")
        note_id = canonical.rsplit("/", 1)[-1]
        for note in notes:
            if isinstance(note, dict) and _note_id(note) == note_id:
                raw = _raw_note(note)
                if raw is not None:
                    return self.normalize_post(raw)
        raise XiaohongshuError(ACCESS_RESTRICTED, "小红书公开笔记详情不可见")

    def collect_comments(self, post_url: str, limit: int = 20) -> list[dict[str, Any]]:
        if canonical_item_url(PLATFORM, post_url) is None:
            raise XiaohongshuError(PARSER_FAILED, "不支持的小红书公开笔记 URL")
        raise XiaohongshuError(
            "COMMENTS_UNAVAILABLE", "小红书公开页面未提供可核验评论列表"
        )
