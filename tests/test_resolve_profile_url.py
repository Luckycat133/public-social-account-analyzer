"""Canonical public-profile URL resolution contracts."""

from __future__ import annotations

import pytest

import task_contract


def test_canonical_bilibili_profile_does_not_call_redirect_transport():
    calls = []

    result = task_contract.resolve_profile_url(
        "https://space.bilibili.com/514527835/",
        redirect_resolver=lambda url: calls.append(url) or "unexpected",
    )

    assert result == "https://space.bilibili.com/514527835"
    assert calls == []


def test_b23_short_link_accepts_only_canonical_bilibili_profile_redirect():
    result = task_contract.resolve_profile_url(
        "https://b23.tv/lNbEfZt",
        redirect_resolver=lambda _url: (
            "https://space.bilibili.com/514527835?spm_id_from=333.1007.0.0"
        ),
    )

    assert result == "https://space.bilibili.com/514527835"


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/514527835",
        "https://www.bilibili.com/video/BV1bad",
        "https://space.bilibili.com/not-a-number",
        "http://space.bilibili.com/514527835",
    ],
)
def test_b23_short_link_rejects_redirects_outside_exact_profile_shape(target):
    with pytest.raises(ValueError, match="supported public profile"):
        task_contract.resolve_profile_url(
            "https://b23.tv/lNbEfZt",
            redirect_resolver=lambda _url: target,
        )
