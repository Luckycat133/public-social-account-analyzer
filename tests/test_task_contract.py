"""Direct regression coverage for shared task contracts."""

from __future__ import annotations

import re

import pytest

import task_contract as contract


def test_taxonomy_constants_public():
    assert getattr(contract, "TAX_FORMAT", None) == {
        "talking_head",
        "tutorial",
        "commentary",
        "interview",
        "vlog",
        "news",
        "review",
        "compilation",
        "animation",
        "gameplay",
        "image_text",
        "live_clip",
        "other",
    }
    assert getattr(contract, "TAX_FUNNEL", None) == {
        "awareness",
        "education",
        "engagement",
        "conversion",
        "retention",
        "unknown",
    }
    assert getattr(contract, "TAX_HOOK", None) == {
        "question",
        "contradiction",
        "result_first",
        "pain_point",
        "controversy",
        "list",
        "curiosity",
        "authority",
        "story",
        "none",
        "unknown",
    }


def test_task_and_stop_reason_contracts_are_consistent():
    assert contract.TASK_STATUSES == {
        "CREATED",
        "COLLECTING",
        "NORMALIZING",
        "ANALYZING",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
    }
    assert contract.ANALYZABLE_TASK_STATUSES == {"COMPLETED", "PARTIAL"}
    assert contract.ANALYZABLE_TASK_STATUSES < contract.TASK_STATUSES
    assert "LOGIN_REQUIRED" in contract.STOP_REASONS
    assert "ACCESS_RESTRICTED" in contract.STOP_REASONS
    assert contract.LABEL_MISSING == "null"
    assert contract.LABEL_UNKNOWN == "INVALID"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        ("LOGIN_REQUIRED", "LOGIN_REQUIRED"),
        ("not-real", "INVALID"),
        (1, "INVALID"),
    ],
)
def test_safe_stop_reason_label(value, expected):
    assert contract.safe_stop_reason_label(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        ("COMPLETED", "COMPLETED"),
        ("not-real", "INVALID"),
        (1, "INVALID"),
    ],
)
def test_safe_task_status_label(value, expected):
    assert contract.safe_task_status_label(value) == expected


def test_validate_analysis_goal_normalizes_nfkc():
    assert contract.validate_analysis_goal(None) is None
    assert contract.validate_analysis_goal("  ＡＢＣ  ") == "ABC"


def test_validate_analysis_goal_bytes_bound():
    assert contract.MAX_ANALYSIS_GOAL_BYTES == 500
    assert contract.validate_analysis_goal("界" * 166) == "界" * 166
    assert contract.validate_analysis_goal("x" * 500) == "x" * 500
    with pytest.raises(contract.TaskContractError):
        contract.validate_analysis_goal("界" * 167)


@pytest.mark.parametrize(
    "value",
    [1, "", "   ", "x" * 501, "界" * 167, "line\nfeed", "nul\x00byte"],
)
def test_validate_analysis_goal_rejects_invalid_values(value):
    with pytest.raises(contract.TaskContractError):
        contract.validate_analysis_goal(value)


def test_new_task_id_is_valid_unique_and_platform_bound():
    first = contract.new_task_id("bilibili")
    second = contract.new_task_id("bilibili")
    assert first != second
    assert re.fullmatch(
        r"bilibili-\d{8}T\d{12}Z-[0-9a-f]{16}", first
    )
    with pytest.raises(contract.TaskContractError):
        contract.new_task_id("Bilibili!")


@pytest.mark.parametrize(
    ("platform", "url", "identity"),
    [
        ("bilibili", "https://space.bilibili.com/12345", "12345"),
        ("douyin", "https://www.douyin.com/user/sec_uid", "sec_uid"),
        ("weibo", "https://weibo.com/u/67890", "67890"),
    ],
)
def test_account_output_key_hashes_all_platform_identities(
    platform, url, identity
):
    key = contract.account_output_key(platform, url)
    assert re.fullmatch(r"[0-9a-f]{12}", key)
    assert key != identity
