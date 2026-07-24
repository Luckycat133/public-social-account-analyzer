"""Pure helpers for collecting public Douyin browser data.

This module deliberately contains no browser control or persistence.  It only
normalizes already-observed public response data and visible DOM card data.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

from ._constants import STOP_LOGIN, STOP_VERIFICATION
from .browser_backend import BrowserSession


_RESTRICTIONS = [
    (
        re.compile(r"滑动验证|人机验证|安全验证|verify you are human|please verify", re.I),
        STOP_VERIFICATION,
    ),
    (
        re.compile(r"登录后查看|请先登录|登录抖音|需登录|登录后访问|扫码登录", re.I),
        STOP_LOGIN,
    ),
]

_ITEM_LIST_KEYS = {"aweme_list", "awemeList", "post_list"}
_ITEM_DETAIL_KEYS = {"aweme_detail", "awemeDetail"}
_POST_PATH = re.compile(r"/(?:video|note)/(\d+)")
MAX_SECONDS = 90.0
MAX_SCROLLS = 20
MAX_IDLE_ROUNDS = 3

_ALLOWED_RESPONSE_HOSTS = ("douyin.com", "iesdouyin.com")
_DOM_CARDS_EXPRESSION = """Array.from(document.querySelectorAll('a[href*="/video/"],a[href*="/note/"]')).map(a => ({
  href: a.href,
  text: (a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || '').trim()
}))"""


@dataclass
class DouyinBrowserResult:
    """Sanitized public browser collection output for the collector layer."""

    profile_raw: Optional[dict[str, Any]] = None
    aweme_items: list[dict[str, Any]] = field(default_factory=list)
    source: str = "network"
    restriction: Optional[str] = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def detect_restriction(text: str) -> Optional[str]:
    """Return the first public-access restriction indicated by visible text."""
    for pattern, reason in _RESTRICTIONS:
        if pattern.search(text or ""):
            return reason
    return None


def sanitize_response_url(url: str) -> str:
    """Remove sensitive query and fragment components from an observed URL."""
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _item_id(item: dict[str, Any]) -> Optional[str]:
    value = item.get("aweme_id") or item.get("aweme_id_str")
    return str(value) if value else None


def extract_aweme_items(data: Any) -> list[dict[str, Any]]:
    """Find and de-duplicate post objects from known response shapes.

    Traversal is intentionally shallowly bounded: response JSON can contain
    arbitrary nested payloads, whereas valid post lists live under a small,
    documented set of keys.
    """
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
                        if isinstance(item, dict) and _item_id(item)
                    )
                elif key in _ITEM_DETAIL_KEYS and isinstance(child, dict):
                    if _item_id(child):
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
        if item_id is not None:
            unique.setdefault(item_id, item)
    return list(unique.values())


def extract_dom_items(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert only visible post-card links into minimal public post objects."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        href = str(card.get("href") or "")
        match = _POST_PATH.fullmatch(urllib.parse.urlsplit(href).path)
        if not match or match.group(1) in seen:
            continue
        post_id = match.group(1)
        seen.add(post_id)
        out.append(
            {
                "aweme_id": post_id,
                "desc": str(card.get("text") or "").strip(),
                "share_url": sanitize_response_url(href),
                "statistics": {},
                "_collection_source": "dom",
            }
        )
    return out


def _is_allowed_host(host: str) -> bool:
    """Return whether an observed response belongs to a public Douyin host."""
    host = host.lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_RESPONSE_HOSTS)


def _allowed_response(event: dict[str, Any]) -> Optional[tuple[str, str]]:
    """Return a request id and query-free URL for eligible public responses."""
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
    parsed = urllib.parse.urlsplit(url)
    if not _is_allowed_host(parsed.hostname or ""):
        return None
    resource_type = str(params.get("type") or "").lower()
    mime_type = str(response.get("mimeType") or "").lower()
    if resource_type not in {"xhr", "fetch"} and "json" not in mime_type:
        return None
    return request_id, sanitize_response_url(url)


def _dom_cards(session: BrowserSession) -> list[dict[str, Any]]:
    """Read visible candidate post cards without retaining page HTML."""
    cards = session.evaluate(_DOM_CARDS_EXPRESSION)
    if not isinstance(cards, list):
        return []
    return [card for card in cards if isinstance(card, dict)]


def collect_account_page(
    url: str,
    *,
    limit: int,
    date_range: Any = None,
    session_factory=BrowserSession,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> DouyinBrowserResult:
    """Observe bounded public Douyin post responses and visible DOM cards.

    Response bodies exist only long enough to parse a known public post shape;
    diagnostics contain counts and query-free paths only.
    """
    del date_range  # Date normalization/filtering belongs to the collector layer.
    requested = max(1, min(int(limit), 100))
    started = monotonic()
    items: dict[str, dict[str, Any]] = {}
    safe_paths: list[str] = []
    restriction: Optional[str] = None
    scrolls = 0
    idle = 0

    with session_factory() as session:
        session.navigate(url, timeout=30.0)
        while len(items) < requested:
            if monotonic() - started >= MAX_SECONDS:
                break
            before = len(items)
            event = session.poll_event(timeout=1.0)
            candidate = _allowed_response(event or {})
            if candidate:
                request_id, safe_url = candidate
                try:
                    decoded = json.loads(session.get_response_body(request_id))
                except (ValueError, TypeError, UnicodeError, RuntimeError):
                    decoded = None
                if decoded is not None:
                    for item in extract_aweme_items(decoded):
                        item_id = _item_id(item)
                        if item_id is not None:
                            items.setdefault(item_id, item)
                    if safe_url not in safe_paths:
                        safe_paths.append(safe_url)
            restriction = detect_restriction(session.page_text())
            if restriction or len(items) >= requested:
                break
            if event is None:
                idle = idle + 1 if len(items) == before else 0
                if idle >= MAX_IDLE_ROUNDS or scrolls >= MAX_SCROLLS:
                    break
                session.scroll_by(1)
                scrolls += 1
                sleep(1.0)

        network_count = len(items)
        if not restriction and len(items) < requested:
            for item in extract_dom_items(_dom_cards(session)):
                items.setdefault(str(item["aweme_id"]), item)

    final = list(items.values())[:requested]
    dom_count = sum(item.get("_collection_source") == "dom" for item in final)
    source = "network+dom" if network_count and dom_count else "dom" if dom_count else "network"
    return DouyinBrowserResult(
        aweme_items=final,
        source=source,
        restriction=restriction,
        diagnostics={
            "scroll_rounds": scrolls,
            "candidate_response_count": len(safe_paths),
            "response_paths": safe_paths,
            "stop_condition": restriction
            or ("limit" if len(final) >= requested else "idle_or_timeout"),
        },
    )
