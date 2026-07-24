"""Bounded, zero-Python-dependency collection of public Douyin page data.

The browser follows the public page normally.  This module observes eligible
CDP responses after they finish loading and, when needed, reads only visible
DOM-card fields.  It never constructs signed requests or handles challenges.
"""

from __future__ import annotations

import copy
import json
import re
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ._constants import DOUYIN_PAGE_STATE_PATTERNS
from .browser_backend import (
    BrowserError,
    BrowserSession,
    _sanitize_cleanup_diagnostics,
)


_ITEM_LIST_KEYS = {"aweme_list", "awemeList", "post_list"}
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
_DOM_CARDS_EXPRESSION = r"""Array.from(
  document.querySelectorAll('a[href*="/video/"],a[href*="/note/"]')
).map(a => {
  const root = a.closest('[data-e2e="user-post-item"],li') || a.parentElement || a;
  const visibleText = selector => {
    const node = root.querySelector(selector);
    if (!node || node.getClientRects().length === 0) return null;
    return (node.getAttribute('aria-label') || node.innerText || '').trim() || null;
  };
  const pinNode = root.querySelector('[data-e2e="video-card-top"],[aria-label="置顶"]');
  const isPinned = pinNode && pinNode.getClientRects().length > 0 ? true : null;
  return {
    href: a.href,
    text: (a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || '').trim(),
    is_pinned: isPinned,
    statistics: {
      digg_count: visibleText('[data-e2e="video-like-count"],[aria-label^="点赞"]'),
      comment_count: visibleText('[data-e2e="video-comment-count"],[aria-label^="评论"]'),
      collect_count: visibleText('[data-e2e="video-collect-count"],[aria-label^="收藏"]'),
      share_count: visibleText('[data-e2e="video-share-count"],[aria-label^="分享"]')
    }
  };
})"""


@dataclass
class DouyinBrowserResult:
    """Sanitized public browser collection output for the collector layer."""

    profile_raw: Optional[dict[str, Any]] = None
    aweme_items: list[dict[str, Any]] = field(default_factory=list)
    source: str = "network"
    restriction: Optional[str] = None
    diagnostic_code: Optional[str] = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


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


def _dom_cards(session: BrowserSession, timeout: float) -> list[dict[str, Any]]:
    cards = _call_with_timeout(
        session.evaluate,
        _DOM_CARDS_EXPRESSION,
        timeout=timeout,
    )
    if not isinstance(cards, list):
        return []
    return [card for card in cards if isinstance(card, dict)]


def _date_lower_bound(date_range: Any) -> Optional[float]:
    if not date_range or not isinstance(date_range, (tuple, list)):
        return None
    raw = date_range[0] if date_range else None
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


def _date_relation(item: dict[str, Any], lower_bound: Optional[float]) -> str:
    """Classify a new ID for early-stop purposes without inferring dates."""
    if lower_bound is None:
        return "unknown"
    raw = item.get("create_time")
    if raw is None:
        return "unknown"
    try:
        created = float(raw)
    except (TypeError, ValueError):
        return "unknown"
    if created > 100_000_000_000:
        created /= 1000.0
    if created >= lower_bound:
        return "in_range"
    if bool(item.get("is_top") or item.get("is_top_aweme")):
        return "unknown"
    return "past_lower_bound"


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
    session_factory=BrowserSession,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> DouyinBrowserResult:
    """Observe public response bodies within hard time/scroll/idle boundaries."""
    requested = max(1, min(int(limit), 100))
    started = monotonic()
    deadline = started + MAX_SECONDS
    lower_bound = _date_lower_bound(date_range)
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

    def remaining() -> float:
        return max(0.0, deadline - monotonic())

    def store_network_item(raw_item: dict[str, Any]) -> None:
        nonlocal in_range_since_boundary, past_lower_bound_since_boundary
        item_id = _item_id(raw_item)
        if item_id is None:
            return
        incoming = copy.deepcopy(raw_item)
        incoming["_collection_source"] = "network"
        if item_id in items:
            _merge_missing(items[item_id], incoming)
            return
        items[item_id] = incoming
        relation = _date_relation(incoming, lower_bound)
        if relation == "in_range":
            in_range_since_boundary = True
        elif relation == "past_lower_bound":
            past_lower_bound_since_boundary = True

    def read_pending(request_id: str, session: BrowserSession) -> bool:
        """Try once; temporary body errors leave the candidate retryable."""
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
        safe_url = candidate["safe_url"]
        if safe_url not in safe_paths:
            safe_paths.append(safe_url)
        before = len(items)
        for item in extract_aweme_items(decoded):
            store_network_item(item)
        return len(items) > before

    def flush_pending(session: BrowserSession) -> None:
        # Header-only fakes do not emit loadingFinished.  A quiet boundary is a
        # bounded compatibility retry; production candidates remain pending
        # after temporary body errors and can succeed on a later finish/idle.
        for request_id in list(pending):
            read_pending(request_id, session)
            if len(items) >= requested or remaining() <= 0:
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

        while not deadline_expired and len(items) < requested:
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
            restriction = detect_restriction(visible_text)
            if restriction:
                stop_condition = restriction
                break
            if len(items) >= requested:
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

            if scrolls >= MAX_SCROLLS:
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
        if (
            not restriction
            and len(items) < requested
            and not deadline_expired
        ):
            budget = remaining()
            if budget > 0:
                for item in extract_dom_items(_dom_cards(session, budget)):
                    item_id = str(item["aweme_id"])
                    if item_id not in items:
                        items[item_id] = item
                    else:
                        _merge_missing(items[item_id], item)
            else:
                deadline_expired = True
                stop_condition = "timeout"

    final = list(items.values())[:requested]
    dom_count = sum(item.get("_collection_source") == "dom" for item in final)
    source = (
        "network+dom"
        if network_count and dom_count
        else "dom"
        if dom_count
        else "network"
    )
    if restriction:
        stop_condition = restriction
    elif len(final) >= requested:
        stop_condition = "limit"
    elif stop_condition is None:
        stop_condition = "timeout" if deadline_expired else "idle"
    return DouyinBrowserResult(
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
    )
