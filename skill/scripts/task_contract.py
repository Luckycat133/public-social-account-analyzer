"""Shared task identity and user-supplied analysis-goal contracts."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit


MAX_ANALYSIS_GOAL_LENGTH = 500


class TaskContractError(ValueError):
    """A task field is malformed and must be rejected before side effects."""


def validate_analysis_goal(value: object) -> str | None:
    """Return a normalized optional goal, rejecting unsafe or ambiguous text."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskContractError("analysis_goal 必须是字符串")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise TaskContractError("analysis_goal 不能为空")
    if len(normalized) > MAX_ANALYSIS_GOAL_LENGTH:
        raise TaskContractError("analysis_goal 过长")
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise TaskContractError("analysis_goal 不允许控制字符")
    return normalized


def new_task_id(platform: str) -> str:
    """Create a nonempty, collision-resistant task identifier."""
    if not isinstance(platform, str) or re.fullmatch(
        r"[a-z][a-z0-9_-]{0,31}", platform
    ) is None:
        raise TaskContractError("platform 无法用于 task_id")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{platform}-{timestamp}-{secrets.token_hex(8)}"


def account_output_key(platform: str, canonical_url: str) -> str:
    """Return a non-sensitive stable key for the default task directory."""
    path = urlsplit(canonical_url).path.rstrip("/")
    identity = path.rsplit("/", 1)[-1]
    if platform == "bilibili" and re.fullmatch(r"\d+", identity):
        return identity
    if platform == "douyin" and re.fullmatch(
        r"[A-Za-z0-9_-]{1,512}", identity
    ):
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    material = canonical_url.encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:12]
