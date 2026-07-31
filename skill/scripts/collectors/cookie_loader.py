"""Route user-authorized Cookie files to the platform-specific validator."""

from __future__ import annotations

from os import PathLike
from typing import Any

from .douyin_cookies import load_douyin_cookie_file
from .platform_cookies import load_platform_cookie_file


_PLATFORM_DOMAINS = {
    "bilibili": "bilibili.com",
    "weibo": "weibo.com",
    "xiaohongshu": "xiaohongshu.com",
}


def load_cookie_records(
    path: str | PathLike[str], platform: str
) -> tuple[dict[str, Any], ...]:
    """Load one bounded Cookie input without exposing credential values."""
    if platform == "douyin":
        return load_douyin_cookie_file(path)
    domain = _PLATFORM_DOMAINS.get(platform)
    if domain is None:
        raise ValueError("unsupported Cookie platform")
    return load_platform_cookie_file(path, domain)
