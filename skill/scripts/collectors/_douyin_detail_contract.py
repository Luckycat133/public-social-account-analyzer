"""Shared, allowlisted completeness contract for public Douyin post details."""

from __future__ import annotations

import math
from typing import Any, Iterable


P0_DETAIL_FIELDS = ("title", "published_at", "duration_seconds", "hashtags")
MISSING_P0_DETAIL = "missing_p0_detail"
OTHER_PARTIAL = "other_partial"

_PARTIAL_REASON_ORDER = (
    MISSING_P0_DETAIL,
    "restricted",
    "login_required",
    "verification_required",
    "access_restricted",
    "parser_failed",
    "detail_unavailable",
    OTHER_PARTIAL,
)
_ALLOWED_PARTIAL_REASONS = frozenset(_PARTIAL_REASON_ORDER)


def detail_value_is_observed(
    field: str,
    value: Any,
    *,
    content_type: Any = None,
) -> bool:
    """Return whether a P0 field has explicit, structurally valid evidence."""
    if field == "title":
        return isinstance(value, str) and bool(value.strip())
    if field == "published_at":
        return isinstance(value, str) and bool(value.strip())
    if field == "duration_seconds":
        if content_type == "image_text":
            return True
        return bool(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        )
    if field == "hashtags":
        return isinstance(value, list) and all(
            isinstance(tag, str) for tag in value
        )
    return False


def missing_detail_fields(
    post: dict[str, Any],
    *,
    observed_fields: Iterable[str] = (),
) -> list[str]:
    """Compute missing P0 fields, distinguishing known-empty hashtag arrays."""
    observed = frozenset(observed_fields)
    missing: list[str] = []
    for field in P0_DETAIL_FIELDS:
        value = post.get(field)
        if field == "hashtags" and value == [] and field not in observed:
            missing.append(field)
            continue
        if not detail_value_is_observed(
            field,
            value,
            content_type=post.get("content_type"),
        ):
            missing.append(field)
    return missing


def sanitize_missing_detail_fields(value: Any) -> list[str] | None:
    """Return a stable allowlisted field list, or None for absent metadata."""
    if value is None:
        return None
    if not isinstance(value, list):
        return list(P0_DETAIL_FIELDS)
    if any(
        not isinstance(item, str) or item not in P0_DETAIL_FIELDS
        for item in value
    ):
        return list(P0_DETAIL_FIELDS)
    supplied = set(value)
    return [field for field in P0_DETAIL_FIELDS if field in supplied]


def sanitize_partial_reasons(value: Any) -> list[str]:
    """Normalize known reasons and collapse arbitrary values to a safe marker."""
    if value is None:
        return []
    if not isinstance(value, list):
        return [OTHER_PARTIAL]
    normalized: set[str] = set()
    unknown = False
    for item in value:
        if not isinstance(item, str):
            unknown = True
            continue
        reason = item.strip().lower()
        if reason in _ALLOWED_PARTIAL_REASONS:
            normalized.add(reason)
        else:
            unknown = True
    if unknown:
        normalized.add(OTHER_PARTIAL)
    return [reason for reason in _PARTIAL_REASON_ORDER if reason in normalized]


def derive_detail_contract(
    post: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Reconcile declared metadata with actual fields without unsafe upgrades."""
    metrics = post.get("platform_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    declared_missing = sanitize_missing_detail_fields(
        metrics.get("missing_detail_fields")
    )
    observed = (
        set(P0_DETAIL_FIELDS) - set(declared_missing)
        if declared_missing is not None
        else set()
    )
    actual_missing = missing_detail_fields(post, observed_fields=observed)

    reasons = sanitize_partial_reasons(metrics.get("partial_reasons"))
    declared_missing_reason = MISSING_P0_DETAIL in reasons
    if actual_missing and MISSING_P0_DETAIL not in reasons:
        reasons.insert(0, MISSING_P0_DETAIL)
    if not actual_missing:
        reasons = [reason for reason in reasons if reason != MISSING_P0_DETAIL]
    if (
        post.get("collection_status") == "PARTIAL"
        and not reasons
        and not declared_missing_reason
    ):
        reasons.append(OTHER_PARTIAL)
    reasons = sanitize_partial_reasons(reasons)
    return actual_missing, reasons


def set_detail_contract(
    post: dict[str, Any],
    missing: Iterable[str],
    reasons: Iterable[str],
) -> dict[str, Any]:
    """Persist only ordered allowlisted detail metadata on one normalized post."""
    metrics = post.get("platform_metrics")
    clean_metrics = dict(metrics) if isinstance(metrics, dict) else {}
    clean_metrics["missing_detail_fields"] = sanitize_missing_detail_fields(
        list(missing)
    ) or []
    clean_metrics["partial_reasons"] = sanitize_partial_reasons(list(reasons))
    post["platform_metrics"] = clean_metrics
    return clean_metrics
