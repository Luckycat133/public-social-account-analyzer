"""Bounded, zero-Python-dependency collection of public Douyin page data.

The browser follows the public page normally.  This module observes eligible
CDP responses after they finish loading and, when needed, reads only visible
DOM-card fields.  It never constructs signed requests or handles challenges.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ._constants import (
    DOUYIN_PAGE_STATE_PATTERNS,
    PUBLIC_ALL_DEFAULT_MAX_SCROLLS,
    PUBLIC_ALL_DEFAULT_MAX_SECONDS,
    validate_public_all_budgets,
    validate_public_limit,
)
from .browser_backend import (
    BrowserError,
    BrowserSession,
    _sanitize_cleanup_diagnostics,
)
from .url_policy import canonical_profile_url


_ITEM_LIST_KEYS = ("aweme_list", "awemeList", "post_list")
_ITEM_DETAIL_KEYS = {"aweme_detail", "awemeDetail"}
_POST_PATH = re.compile(r"/(?P<kind>video|note)/(?P<post_id>\d+)")
_POST_ID = re.compile(r"\d+")
_VISIBLE_METRIC_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?\s*[万亿]?")
_KNOWN_STATISTICS = {
    "play_count",
    "digg_count",
    "comment_count",
    "collect_count",
    "share_count",
}
_KNOWN_VIDEO_FIELDS = {"duration", "play_addr", "cover", "origin_cover"}
MAX_SECONDS = 90.0
MAX_SCROLLS = 20
MAX_IDLE_ROUNDS = 3

_ALLOWED_RESPONSE_HOSTS = ("douyin.com", "iesdouyin.com")
_DOM_CARDS_EXPRESSION = r"""(() => {
const visibleText = (root, selector) => {
  const node = root.querySelector(selector);
  if (!node || node.getClientRects().length === 0) return null;
  return (node.getAttribute('aria-label') || node.innerText || '').trim() || null;
};
const cards = Array.from(
  document.querySelectorAll('a[href*="/video/"],a[href*="/note/"]')
).map(a => {
  const root = a.closest('[data-e2e="user-post-item"],li') || a.parentElement || a;
  const pinNode = root.querySelector('[data-e2e="video-card-top"],[aria-label="置顶"]');
  const isPinned = pinNode && pinNode.getClientRects().length > 0 ? true : null;
  return {
    href: a.href,
    text: (a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || '').trim(),
    is_pinned: isPinned,
    statistics: {
      digg_count: visibleText(root, '[data-e2e="video-like-count"],[aria-label^="点赞"]'),
      comment_count: visibleText(root, '[data-e2e="video-comment-count"],[aria-label^="评论"]'),
      collect_count: visibleText(root, '[data-e2e="video-collect-count"],[aria-label^="收藏"]'),
      share_count: visibleText(root, '[data-e2e="video-share-count"],[aria-label^="分享"]')
    }
  };
});
const page = document.body || document.documentElement;
const pathMatch = location.pathname.match(/^\/(?:user|share\/user)\/([A-Za-z0-9_-]+)\/?$/);
const verifiedNode = document.querySelector(
  '[data-e2e="user-info-verify"],[data-e2e="user-info-authentication"],[aria-label*="认证"]'
);
return {
  cards,
  profile: {
    profile_url: location.href,
    sec_uid: pathMatch ? pathMatch[1] : null,
    nickname: visibleText(page, '[data-e2e="user-title"],h1'),
    signature: visibleText(page, '[data-e2e="user-signature"]'),
    follower_count: visibleText(page, '[data-e2e="user-info-follower"]'),
    aweme_count: visibleText(page, '[data-e2e="user-info-post-count"]'),
    total_favorited: visibleText(page, '[data-e2e="user-info-like"]'),
    verified: verifiedNode && verifiedNode.getClientRects().length > 0 ? true : null
  }
};
})()"""

_PROFILE_HINT_KEYS = {
    "account_id",
    "account_name",
    "profile_url",
    "sec_uid",
    "unique_id",
    "uid",
    "nickname",
    "signature",
    "followers",
    "follower_count",
    "post_count",
    "aweme_count",
    "total_favorited",
    "verified",
    "custom_verify",
    "enterprise_verify_reason",
}


@dataclass
class DouyinBrowserResult:
    """Sanitized public browser collection output for the collector layer."""

    profile_raw: Optional[dict[str, Any]] = None
    aweme_items: list[dict[str, Any]] = field(default_factory=list)
    source: str = "network"
    restriction: Optional[str] = None
    diagnostic_code: Optional[str] = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostPageObservation:
    """Ephemeral metadata from a dictionary that owns a recognized post list."""

    items: list[dict[str, Any]] = field(default_factory=list)
    has_more: Optional[bool] = None
    cursor: Any = None


def detect_restriction(text: str) -> Optional[str]:
    """Return the highest-priority visible restriction or explicit empty state."""
    for pattern, reason in DOUYIN_PAGE_STATE_PATTERNS:
        if pattern.search(text or ""):
            return reason
    return None


def sanitize_response_url(url: str) -> str:
    """Remove credentials, query, and fragment from an observed diagnostic URL."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    hostname = parsed.hostname
    if not hostname:
        authority = ""
    else:
        authority = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is not None:
            authority = f"{authority}:{port}"
    return urllib.parse.urlunsplit((parsed.scheme, authority, parsed.path, "", ""))


def canonical_post_url(post_id: Any, kind: str = "video") -> str:
    """Build a query-free public evidence URL from a validated Douyin post ID."""
    value = str(post_id or "")
    if not _POST_ID.fullmatch(value) or kind not in {"video", "note"}:
        return ""
    return f"https://www.douyin.com/{kind}/{value}"


def _item_id(item: dict[str, Any]) -> Optional[str]:
    value = item.get("aweme_id") or item.get("aweme_id_str")
    text = str(value) if value is not None else ""
    return text if _POST_ID.fullmatch(text) else None


def _is_trustworthy_aweme(item: dict[str, Any]) -> bool:
    """Require an ID plus at least one credible public post field group."""
    if _item_id(item) is None:
        return False
    if isinstance(item.get("desc"), str):
        return True
    if item.get("create_time") is not None:
        try:
            float(item["create_time"])
        except (TypeError, ValueError):
            pass
        else:
            return True
    statistics = item.get("statistics")
    if isinstance(statistics, dict) and any(
        key in statistics for key in _KNOWN_STATISTICS
    ):
        return True
    video = item.get("video")
    if isinstance(video, dict) and any(key in video for key in _KNOWN_VIDEO_FIELDS):
        return True
    images = item.get("images")
    return isinstance(images, list) and bool(images)


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _merge_missing(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Recursively fill only absent values, preserving earlier reliable data."""
    for key, value in incoming.items():
        if key not in existing or _is_missing(existing[key]):
            existing[key] = copy.deepcopy(value)
            continue
        if isinstance(existing[key], dict) and isinstance(value, dict):
            _merge_missing(existing[key], value)


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    """Return the first present value without discarding explicit zero/false."""
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


def _public_text(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text or None


def _public_count(value: Any) -> Optional[int]:
    """Parse a displayed public count while rejecting booleans and structures."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if math.isfinite(value) and value >= 0 else None
    match = _VISIBLE_METRIC_NUMBER.search(str(value))
    if match is None:
        return None
    text = match.group(0).replace(" ", "").replace(",", "")
    multiplier = 100_000_000 if "亿" in text else 10_000 if "万" in text else 1
    try:
        parsed = float(text.replace("亿", "").replace("万", ""))
    except ValueError:
        return None
    return int(parsed * multiplier) if math.isfinite(parsed) and parsed >= 0 else None


def _public_verified(value: dict[str, Any]) -> bool | str | None:
    enterprise = _public_text(value.get("enterprise_verify_reason"))
    if enterprise is not None:
        return enterprise
    custom = _public_text(value.get("custom_verify"))
    if custom is not None:
        return custom
    verified = value.get("verified")
    if isinstance(verified, bool):
        return verified
    if isinstance(verified, str):
        return _public_text(verified)
    verification_type = value.get("verification_type")
    if isinstance(verification_type, (int, float)) and not isinstance(
        verification_type, bool
    ):
        return verification_type not in (0, -1)
    return None


def sanitize_profile_raw(
    value: Any,
    requested_url: str,
) -> Optional[dict[str, Any]]:
    """Bind one profile candidate to the requested account and allowlist fields.

    This function is deliberately safe to call again at the collector boundary:
    it accepts either a public user object or an already-sanitized profile, but
    never copies arbitrary keys, nested objects, response URLs, or transport data.
    """
    canonical_url = canonical_profile_url("douyin", requested_url)
    if canonical_url is None or not isinstance(value, dict):
        return None
    requested_sec_uid = canonical_url.rstrip("/").rsplit("/", 1)[-1]
    supplied_metrics = value.get("platform_metrics")
    metrics = supplied_metrics if isinstance(supplied_metrics, dict) else {}
    supplied_sec_uid = _public_text(
        _first_present(value, "sec_uid")
        if "sec_uid" in value
        else metrics.get("sec_uid")
    )
    supplied_url = _first_present(value, "profile_url", "share_url")
    supplied_canonical = (
        canonical_profile_url("douyin", supplied_url)
        if isinstance(supplied_url, str)
        else None
    )

    # Any public association evidence must agree; a contradiction is never
    # papered over by a second matching field.
    if supplied_sec_uid is not None and supplied_sec_uid != requested_sec_uid:
        return None
    if supplied_url is not None and supplied_canonical != canonical_url:
        return None
    if supplied_sec_uid is None and supplied_canonical is None:
        return None

    unique_id = _public_text(
        _first_present(value, "unique_id")
        if "unique_id" in value
        else metrics.get("unique_id")
    )
    uid = _public_text(
        _first_present(value, "uid") if "uid" in value else metrics.get("uid")
    )
    account_id = _public_text(value.get("account_id")) or unique_id or supplied_sec_uid
    account_name = _public_text(_first_present(value, "account_name", "nickname"))
    bio = _public_text(_first_present(value, "bio", "signature"))
    followers = _public_count(_first_present(value, "followers", "follower_count"))
    post_count = _public_count(_first_present(value, "post_count", "aweme_count"))
    total_likes = _public_count(
        value.get("total_favorited")
        if "total_favorited" in value
        else metrics.get("total_likes")
    )
    verified = _public_verified(value)
    if verified is None and isinstance(value.get("verified"), bool):
        verified = value["verified"]

    public_metrics = {
        key: metric_value
        for key, metric_value in (
            ("total_likes", total_likes),
            ("sec_uid", supplied_sec_uid),
            ("unique_id", unique_id),
            ("uid", uid),
        )
        if metric_value is not None
    }
    return {
        "platform": "douyin",
        "account_id": account_id,
        "account_name": account_name,
        "profile_url": canonical_url,
        "bio": bio,
        "verified": verified,
        "followers": followers,
        "post_count": post_count,
        "platform_metrics": public_metrics,
        "field_visibility": {
            "account_name": "visible" if account_name is not None else "hidden",
            "bio": "visible" if bio is not None else "hidden",
            "followers": "visible" if followers is not None else "hidden",
            "post_count": "visible" if post_count is not None else "hidden",
        },
    }


def extract_profile_raw(data: Any, requested_url: str) -> Optional[dict[str, Any]]:
    """Extract and merge only account-bound, allowlisted public profile facts."""
    merged: Optional[dict[str, Any]] = None

    def walk(node: Any, depth: int = 0) -> None:
        nonlocal merged
        if depth > 10:
            return
        if isinstance(node, dict):
            if _PROFILE_HINT_KEYS.intersection(node):
                candidate = sanitize_profile_raw(node, requested_url)
                if candidate is not None:
                    if merged is None:
                        merged = candidate
                    else:
                        _merge_missing(merged, candidate)
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)

    walk(data)
    return sanitize_profile_raw(merged, requested_url) if merged is not None else None


def extract_aweme_items(data: Any) -> list[dict[str, Any]]:
    """Find, validate, merge, and de-duplicate known list/detail response shapes."""
    found: list[dict[str, Any]] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _ITEM_LIST_KEYS and isinstance(child, list):
                    found.extend(
                        item
                        for item in child
                        if isinstance(item, dict) and _is_trustworthy_aweme(item)
                    )
                elif key in _ITEM_DETAIL_KEYS and isinstance(child, dict):
                    if _is_trustworthy_aweme(child):
                        found.append(child)
                else:
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    walk(data)
    unique: dict[str, dict[str, Any]] = {}
    for item in found:
        item_id = _item_id(item)
        if item_id is None:
            continue
        if item_id not in unique:
            unique[item_id] = copy.deepcopy(item)
        else:
            _merge_missing(unique[item_id], item)
    return list(unique.values())


def extract_post_page_observations(data: Any) -> list[PostPageObservation]:
    """Extract list-scoped pagination facts without treating nested flags as proof."""
    observations: list[PostPageObservation] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, dict):
            owned_lists = [
                value[key]
                for key in _ITEM_LIST_KEYS
                if key in value and isinstance(value[key], list)
            ]
            for raw_items in owned_lists:
                unique: dict[str, dict[str, Any]] = {}
                for raw_item in raw_items:
                    if not isinstance(raw_item, dict) or not _is_trustworthy_aweme(raw_item):
                        continue
                    item_id = _item_id(raw_item)
                    if item_id is None:
                        continue
                    if item_id not in unique:
                        unique[item_id] = copy.deepcopy(raw_item)
                    else:
                        _merge_missing(unique[item_id], raw_item)
                if raw_items and not unique:
                    continue
                has_more = value.get("has_more")
                if not isinstance(has_more, bool):
                    has_more = None
                cursor = next(
                    (
                        value[key]
                        for key in ("max_cursor", "cursor", "min_cursor")
                        if key in value and value[key] is not None
                    ),
                    None,
                )
                observations.append(
                    PostPageObservation(
                        items=list(unique.values()),
                        has_more=has_more,
                        cursor=cursor,
                    )
                )
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    walk(data)
    return observations


def _cursor_fingerprint(cursor: Any) -> Optional[str]:
    """Return an irreversible correlation token for an in-memory cursor value."""
    if cursor is None:
        return None
    try:
        encoded = json.dumps(
            cursor,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = repr(type(cursor).__name__).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _is_allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _ALLOWED_RESPONSE_HOSTS
    )


def _post_reference_from_public_url(url: str) -> Optional[tuple[str, str]]:
    """Return a validated public post kind and ID without retaining URL secrets."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not _is_allowed_host(parsed.hostname or "")
    ):
        return None
    match = _POST_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    return match.group("kind"), match.group("post_id")


def canonical_post_url_for_item(item: dict[str, Any], post_id: Any) -> str:
    """Prefer an ID-matching safe share path, then infer image notes."""
    value = str(post_id or "")
    if not _POST_ID.fullmatch(value):
        return ""
    reference = _post_reference_from_public_url(str(item.get("share_url") or ""))
    if reference is not None and reference[1] == value:
        return canonical_post_url(value, reference[0])
    note_media = item.get("images") or item.get("image_post_info")
    kind = "note" if isinstance(note_media, (dict, list)) and bool(note_media) else "video"
    return canonical_post_url(value, kind)


def _visible_metric_value(value: Any) -> Any:
    """Keep an explicit displayed number while removing its accessible label."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    match = _VISIBLE_METRIC_NUMBER.search(str(value))
    return match.group(0).replace(" ", "") if match else None


def extract_dom_items(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert allowlisted visible cards into minimal, non-inferred post data."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        reference = _post_reference_from_public_url(str(card.get("href") or ""))
        if reference is None:
            continue
        kind, post_id = reference
        if post_id in seen:
            continue
        seen.add(post_id)
        visible_stats: dict[str, Any] = {}
        supplied_stats = card.get("statistics")
        if isinstance(supplied_stats, dict):
            for key in _KNOWN_STATISTICS:
                value = _visible_metric_value(supplied_stats.get(key))
                if value is not None:
                    visible_stats[key] = value
        out.append(
            {
                "aweme_id": post_id,
                "desc": str(card.get("text") or "").strip(),
                "share_url": canonical_post_url(post_id, kind),
                "statistics": visible_stats,
                "is_top": True if card.get("is_pinned") is True else None,
                "_collection_source": "dom",
            }
        )
    return out


def _allowed_response(event: dict[str, Any]) -> Optional[tuple[str, str]]:
    """Return request id and query-free URL for an eligible response header."""
    if event.get("method") != "Network.responseReceived":
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        return None
    response = params.get("response")
    if not isinstance(response, dict):
        return None
    request_id = params.get("requestId")
    url = response.get("url")
    if not isinstance(request_id, str) or not request_id or not isinstance(url, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not _is_allowed_host(parsed.hostname or "")
    ):
        return None
    resource_type = str(params.get("type") or "").lower()
    mime_type = str(response.get("mimeType") or "").lower()
    if resource_type not in {"xhr", "fetch"} and "json" not in mime_type:
        return None
    return request_id, sanitize_response_url(url)


def _call_with_timeout(method, *args, timeout: float):
    """Pass a deadline to production APIs while retaining simple test fakes."""
    try:
        return method(*args, timeout=timeout)
    except TypeError as exc:
        message = str(exc)
        if "timeout" not in message or "unexpected keyword" not in message:
            raise
        return method(*args)


def _dom_snapshot(
    session: BrowserSession,
    requested_url: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Read one bounded visible snapshot, accepting legacy list-only fakes."""
    snapshot = _call_with_timeout(
        session.evaluate,
        _DOM_CARDS_EXPRESSION,
        timeout=timeout,
    )
    if isinstance(snapshot, list):
        return [card for card in snapshot if isinstance(card, dict)], None
    if not isinstance(snapshot, dict):
        return [], None
    cards = snapshot.get("cards")
    clean_cards = (
        [card for card in cards if isinstance(card, dict)]
        if isinstance(cards, list)
        else []
    )
    return clean_cards, sanitize_profile_raw(snapshot.get("profile"), requested_url)


def _date_bound(raw: Any) -> Optional[float]:
    if not raw:
        return None
    try:
        value = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.timestamp()


def _date_bounds(date_range: Any) -> Optional[tuple[Optional[float], Optional[float]]]:
    if not date_range or not isinstance(date_range, (tuple, list)):
        return None
    lower = _date_bound(date_range[0] if len(date_range) > 0 else None)
    upper = _date_bound(date_range[1] if len(date_range) > 1 else None)
    return (lower, upper)


def _item_timestamp(item: dict[str, Any]) -> Optional[float]:
    raw = item.get("create_time")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        created = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(created) or created < 0:
        return None
    if created > 100_000_000_000:
        created /= 1000.0
    return created


def _date_relation(
    item: dict[str, Any],
    bounds: Optional[tuple[Optional[float], Optional[float]]],
) -> str:
    """Classify a post for target counting and conservative lower-bound stop."""
    if bounds is None:
        return "unknown"
    created = _item_timestamp(item)
    if created is None:
        return "unknown"
    lower, upper = bounds
    if upper is not None and created > upper:
        return "newer_than_range"
    if lower is not None and created < lower:
        if bool(item.get("is_top") or item.get("is_top_aweme")):
            return "unknown"
        return "past_lower_bound"
    return "in_range"


@contextmanager
def _collection_session(session_factory, cleanup_state: dict[str, Any]):
    """Retain collection state when a normal context exit reports cleanup failure."""
    try:
        with session_factory() as session:
            yield session
    except BrowserError as exc:
        if not getattr(exc, "is_cleanup_failure", False):
            raise
        cleanup_state["diagnostic_code"] = "BROWSER_CLEANUP_FAILED"
        cleanup_state["cleanup_codes"] = list(
            _sanitize_cleanup_diagnostics(
                getattr(exc, "cleanup_diagnostics", ())
            )
        )


def collect_account_page(
    url: str,
    *,
    limit: int,
    date_range: Any = None,
    all_posts: bool = False,
    max_seconds: Optional[float] = None,
    max_scrolls: Optional[int] = None,
    session_factory=BrowserSession,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> DouyinBrowserResult:
    """Observe public response bodies within hard time/scroll/idle boundaries."""
    if all_posts:
        seconds_budget = (
            PUBLIC_ALL_DEFAULT_MAX_SECONDS
            if max_seconds is None
            else max_seconds
        )
        scroll_budget = (
            PUBLIC_ALL_DEFAULT_MAX_SCROLLS
            if max_scrolls is None
            else max_scrolls
        )
        requested, seconds_budget, scroll_budget = validate_public_all_budgets(
            limit, seconds_budget, scroll_budget
        )
    else:
        requested = validate_public_limit(limit)
        seconds_budget = MAX_SECONDS if max_seconds is None else max_seconds
        scroll_budget = MAX_SCROLLS if max_scrolls is None else max_scrolls
        _, seconds_budget, scroll_budget = validate_public_all_budgets(
            requested, seconds_budget, scroll_budget
        )
    started = monotonic()
    deadline = started + seconds_budget
    bounds = _date_bounds(date_range)
    items: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, Any]] = {}
    safe_paths: list[str] = []
    candidate_response_count = 0
    cleanup_state: dict[str, Any] = {}
    restriction: Optional[str] = None
    scrolls = 0
    idle = 0
    stop_condition: Optional[str] = None
    deadline_expired = False
    round_in_progress = False
    round_start_count = 0
    in_range_since_boundary = False
    past_lower_bound_since_boundary = False
    date_confirmation_pending = False
    observed_page_count = 0
    terminal_page_observed = False
    cursor_fingerprints: set[str] = set()
    repeated_cursor_count = 0
    profile_raw: Optional[dict[str, Any]] = None

    def remaining() -> float:
        return max(0.0, deadline - monotonic())

    def target_count() -> int:
        if all_posts or bounds is None:
            return len(items)
        return sum(
            _date_relation(item, bounds) == "in_range"
            for item in items.values()
        )

    def store_network_item(raw_item: dict[str, Any]) -> None:
        nonlocal in_range_since_boundary, past_lower_bound_since_boundary
        item_id = _item_id(raw_item)
        if item_id is None:
            return
        incoming = copy.deepcopy(raw_item)
        incoming["_collection_source"] = "network"
        if item_id in items:
            before_relation = _date_relation(items[item_id], bounds)
            _merge_missing(items[item_id], incoming)
            relation = _date_relation(items[item_id], bounds)
            if relation == "in_range" and before_relation != "in_range":
                in_range_since_boundary = True
            elif (
                relation == "past_lower_bound"
                and before_relation != "past_lower_bound"
            ):
                past_lower_bound_since_boundary = True
            return
        items[item_id] = incoming
        relation = _date_relation(incoming, bounds)
        if relation == "in_range":
            in_range_since_boundary = True
        elif relation == "past_lower_bound":
            past_lower_bound_since_boundary = True

    def read_pending(request_id: str, session: BrowserSession) -> bool:
        """Try once; temporary body errors leave the candidate retryable."""
        nonlocal observed_page_count, terminal_page_observed
        nonlocal repeated_cursor_count, stop_condition, profile_raw
        candidate = pending.get(request_id)
        if candidate is None:
            return False
        budget = remaining()
        if budget <= 0:
            return False
        try:
            body = _call_with_timeout(
                session.get_response_body,
                request_id,
                timeout=budget,
            )
        except (BrowserError, KeyError, RuntimeError, TypeError, UnicodeError):
            candidate["attempts"] += 1
            return False
        try:
            decoded = json.loads(body)
        except (json.JSONDecodeError, TypeError, UnicodeError):
            pending.pop(request_id, None)
            return False
        pending.pop(request_id, None)
        discovered_profile = extract_profile_raw(decoded, url)
        if discovered_profile is not None:
            if profile_raw is None:
                profile_raw = discovered_profile
            else:
                _merge_missing(profile_raw, discovered_profile)
        safe_url = candidate["safe_url"]
        if safe_url not in safe_paths:
            safe_paths.append(safe_url)
        before = len(items)
        observations = extract_post_page_observations(decoded)
        if observations:
            for observation in observations:
                observed_page_count += 1
                fingerprint = _cursor_fingerprint(observation.cursor)
                if fingerprint is not None:
                    if fingerprint in cursor_fingerprints:
                        repeated_cursor_count += 1
                        if all_posts and observation.has_more is not False:
                            stop_condition = "repeated_cursor"
                    else:
                        cursor_fingerprints.add(fingerprint)
                if observation.has_more is False:
                    terminal_page_observed = True
                    if all_posts:
                        stop_condition = "terminal_page"
        for item in extract_aweme_items(decoded):
            store_network_item(item)
        return len(items) > before

    def flush_pending(session: BrowserSession) -> None:
        # Header-only fakes do not emit loadingFinished.  A quiet boundary is a
        # bounded compatibility retry; production candidates remain pending
        # after temporary body errors and can succeed on a later finish/idle.
        for request_id in list(pending):
            read_pending(request_id, session)
            if target_count() >= requested or remaining() <= 0:
                break

    with _collection_session(session_factory, cleanup_state) as session:
        budget = remaining()
        if budget <= 0:
            deadline_expired = True
            stop_condition = "timeout"
        else:
            _call_with_timeout(
                session.navigate,
                url,
                timeout=min(30.0, budget),
            )

        while (
            not deadline_expired
            and target_count() < requested
            and not (all_posts and stop_condition in {"terminal_page", "repeated_cursor"})
        ):
            budget = remaining()
            if budget <= 0:
                deadline_expired = True
                stop_condition = "timeout"
                break

            event = session.poll_event(timeout=min(1.0, budget))
            method = event.get("method") if isinstance(event, dict) else None
            params = event.get("params") if isinstance(event, dict) else None
            params = params if isinstance(params, dict) else {}

            candidate = _allowed_response(event or {})
            if candidate:
                candidate_response_count += 1
                request_id, safe_url = candidate
                if safe_url not in safe_paths:
                    safe_paths.append(safe_url)
                pending[request_id] = {
                    "safe_url": safe_url,
                    "ready": False,
                    "attempts": 0,
                }
            elif method == "Network.loadingFinished":
                request_id = params.get("requestId")
                if isinstance(request_id, str) and request_id in pending:
                    pending[request_id]["ready"] = True
                    read_pending(request_id, session)
            elif method == "Network.loadingFailed":
                request_id = params.get("requestId")
                if isinstance(request_id, str):
                    pending.pop(request_id, None)

            if event is None:
                flush_pending(session)

            budget = remaining()
            if budget <= 0:
                deadline_expired = True
                stop_condition = "timeout"
                break
            visible_text = _call_with_timeout(
                session.page_text,
                timeout=budget,
            )
            if remaining() <= 0:
                deadline_expired = True
                stop_condition = "timeout"
                break
            restriction = detect_restriction(visible_text)
            if restriction:
                stop_condition = restriction
                break
            if all_posts and stop_condition in {"terminal_page", "repeated_cursor"}:
                break
            if target_count() >= requested:
                stop_condition = "limit"
                break
            if event is not None:
                continue

            if round_in_progress:
                idle = 0 if len(items) > round_start_count else idle + 1
                if date_confirmation_pending:
                    if not in_range_since_boundary:
                        stop_condition = "date_lower_bound"
                        break
                elif past_lower_bound_since_boundary:
                    date_confirmation_pending = True
                if idle >= MAX_IDLE_ROUNDS:
                    stop_condition = "idle"
                    break
            elif past_lower_bound_since_boundary:
                date_confirmation_pending = True

            if scrolls >= scroll_budget:
                stop_condition = "max_scrolls"
                break

            round_start_count = len(items)
            in_range_since_boundary = False
            past_lower_bound_since_boundary = False
            budget = remaining()
            if budget <= 0:
                deadline_expired = True
                stop_condition = "timeout"
                break
            _call_with_timeout(session.scroll_by, 1, timeout=budget)
            scrolls += 1
            round_in_progress = True
            budget = remaining()
            if budget <= 0:
                deadline_expired = True
                stop_condition = "timeout"
                break
            sleep(min(1.0, budget))

        network_count = sum(
            item.get("_collection_source") == "network" for item in items.values()
        )
        if not restriction and not deadline_expired:
            budget = remaining()
            if budget > 0:
                cards, visible_profile = _dom_snapshot(session, url, budget)
                if remaining() <= 0:
                    deadline_expired = True
                    stop_condition = "timeout"
                else:
                    if visible_profile is not None:
                        if profile_raw is None:
                            profile_raw = visible_profile
                        else:
                            _merge_missing(profile_raw, visible_profile)
                    for item in extract_dom_items(cards):
                        item_id = str(item["aweme_id"])
                        if item_id not in items:
                            items[item_id] = item
                        else:
                            _merge_missing(items[item_id], item)
            else:
                deadline_expired = True
                stop_condition = "timeout"

    observed_items = list(items.values())
    range_items = (
        [item for item in observed_items if _date_relation(item, bounds) == "in_range"]
        if bounds is not None
        else observed_items
    )
    unknown_date_count = (
        sum(_item_timestamp(item) is None for item in observed_items)
        if bounds is not None
        else 0
    )
    if bounds is not None and not all_posts:
        matched_ids = {_item_id(item) for item in range_items}
        remaining_items = [
            item for item in observed_items if _item_id(item) not in matched_ids
        ]
        # Prioritize requested evidence without erasing bounded out-of-range
        # observations that fit in the remaining result budget.
        final = (range_items + remaining_items)[:requested]
    else:
        final = observed_items[:requested]
    dom_count = sum(item.get("_collection_source") == "dom" for item in final)
    source = (
        "network+dom"
        if network_count and dom_count
        else "dom"
        if dom_count
        else "network"
    )
    item_budget_truncated = len(items) > requested
    if restriction:
        stop_condition = restriction
    elif deadline_expired or stop_condition == "timeout":
        stop_condition = "timeout"
    elif all_posts and terminal_page_observed and not item_budget_truncated:
        stop_condition = "terminal_page"
    elif (len(range_items) if bounds is not None and not all_posts else len(final)) >= requested:
        stop_condition = "max_items" if all_posts else "limit"
    elif stop_condition is None:
        stop_condition = "timeout" if deadline_expired else "idle"
    is_exhaustive = bool(
        all_posts
        and terminal_page_observed
        and not item_budget_truncated
        and not deadline_expired
        and not restriction
        and stop_condition == "terminal_page"
    )
    return DouyinBrowserResult(
        profile_raw=profile_raw,
        aweme_items=final,
        source=source,
        restriction=restriction,
        diagnostic_code=cleanup_state.get("diagnostic_code"),
        diagnostics={
            "scroll_rounds": scrolls,
            "candidate_response_count": candidate_response_count,
            "response_paths": safe_paths,
            "pending_response_count": len(pending),
            "stop_condition": stop_condition,
            **(
                {"cleanup_codes": cleanup_state["cleanup_codes"]}
                if cleanup_state.get("cleanup_codes")
                else {}
            ),
        },
        coverage={
            "requested_all": bool(all_posts),
            **({"max_items": requested} if all_posts else {}),
            "is_exhaustive": is_exhaustive,
            "terminal_page_observed": terminal_page_observed,
            "observed_page_count": observed_page_count,
            "observed_post_count": len(observed_items),
            "cursor_fingerprint_count": len(cursor_fingerprints),
            "repeated_cursor_count": repeated_cursor_count,
            "stop_condition": stop_condition,
            "unknown_date_count": unknown_date_count,
            "range_match_count": len(range_items) if bounds is not None else len(final),
            "range_filter_applied": bounds is not None,
            "range_no_match": bool(bounds is not None and observed_items and not range_items),
        },
    )
