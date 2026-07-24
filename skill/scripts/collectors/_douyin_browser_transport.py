"""Pure helpers for collecting public Douyin browser data.

This module deliberately contains no browser control or persistence.  It only
normalizes already-observed public response data and visible DOM card data.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

from ._constants import STOP_LOGIN, STOP_VERIFICATION


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
