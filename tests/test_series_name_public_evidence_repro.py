"""FR-021 / CASE-021 / iter-2 eval-16 — B站 series_name 必须绑定公开证据。

Replicates the protocol documented in `skill/SKILL.md` §"可复现契约断言"
so a regression in `analyze.validate_classification_results` is caught
automatically.

离线、不联网、不修改产物；只验证实现是否在父作品缺少公开 series_name 时
拒绝任何分类端的猜测值。
"""

from __future__ import annotations

import pytest

import analyze


def _bilibili_parent_without_series_name(post_id: str = "BVseries") -> dict:
    return {
        "platform": "bilibili",
        "post_id": post_id,
        "is_repost": None,
        "platform_metrics": {},  # 公开字段中没有 series_name
    }


def _classification_with_guessed_series_name(post_id: str = "BVseries") -> list:
    return [{
        "post_id": post_id,
        "topic": "unknown",
        "format": "other",
        "funnel_stage": "unknown",
        "hook_type": "unknown",
        "series_name": "标题猜测栏目",  # ← 违规:从标题猜出的栏目名
        "is_original": None,
        "has_product_placement": None,
        "analysis_labels": [],
        "classification_confidence": 0.0,
    }]


def test_bilibili_series_name_must_bind_to_public_evidence():
    """当父作品的 platform_metrics.series_name 为 null,分类端的 series_name
    也必须为 null。猜测值必须被拒绝,并报 ValueError 绑定到 public evidence 约束。"""

    parent_posts = [_bilibili_parent_without_series_name()]
    classification_results = _classification_with_guessed_series_name()

    with pytest.raises(ValueError) as exc_info:
        analyze.validate_classification_results(parent_posts, classification_results)

    message = str(exc_info.value)
    # 错误信息应明确指向 series_name 与 public evidence 的冲突,便于定位根因;
    # 只断言关键字段前缀,不绑定完整字符串以免实现微调时误报。
    assert "series_name" in message, (
        f"ValueError message should mention 'series_name'; got: {message!r}"
    )
    assert "public evidence" in message, (
        f"ValueError message should mention 'public evidence' binding; got: {message!r}"
    )


def test_bilibili_series_name_null_parent_null_child_is_accepted():
    """当父作品的 platform_metrics.series_name 为 null 且分类端也写 null 时,
    不得误报。这是上面那条断言的反面,确保我们没有把规则搞过头。"""

    parent_posts = [_bilibili_parent_without_series_name()]
    classification_results = [_classification_with_guessed_series_name()[0]]
    classification_results[0]["series_name"] = None  # 显式 null

    # 不应抛出与 series_name 相关的 ValueError
    try:
        analyze.validate_classification_results(parent_posts, classification_results)
    except ValueError as e:
        message = str(e)
        # 如果实现抛了 ValueError,必须不是关于 series_name 的
        assert "series_name" not in message, (
            f"unexpected ValueError about series_name for legit null: {message!r}"
        )
