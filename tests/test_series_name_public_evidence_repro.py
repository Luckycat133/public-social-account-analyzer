"""iter-2 eval-3 / CASE-021 / FR-021 —— B 站 series_name 必须绑定公开证据。

本测试对应 `docs/acceptance/offline-acceptance.md` 的 B站栏目名离线协议。
离线、不联网、不修改产物；只验证实现是否在父作品缺少公开 `series_name`
时拒绝任何分类端的猜测值。

依据 iter-2 反馈：把"必须拒绝猜测值"这一条规则从纯文本规范升级为脚本级断言，
任何后续代码改动若打破它，本测试必须失败。
"""

from __future__ import annotations

import pytest

from analysis import analyze


def _bilibili_parent_without_series_name(post_id: str = "BV_offline_probe") -> dict:
    """构造父作品：平台 B 站、公开字段里没有 series_name（值为 None）。"""
    return {
        "platform": "bilibili",
        "post_id": post_id,
        "is_repost": None,
        "platform_metrics": {},  # 公开字段里没有 series_name
    }


def _classification_with_guessed_series_name(post_id: str = "BV_offline_probe") -> list:
    """构造分类结果：series_name 是从标题猜的、其余必填字段合法。"""
    return [{
        "post_id": post_id,
        "topic": "unknown",
        "format": "other",
        "funnel_stage": "unknown",
        "hook_type": "unknown",
        "series_name": "标题猜测栏目",  # ← 违规值：可能从标题臆测
        "is_original": None,
        "has_product_placement": None,
        "analysis_labels": [],
        "classification_confidence": 0.0,
    }]


def test_bilibili_series_name_must_bind_to_public_evidence():
    """父作品的 platform_metrics.series_name 为 null、分类端写了猜测值：
    实现必须抛 ValueError,且错误信息必须同时提示 series_name 与 public evidence 两个关键字段。
    """
    parent_posts = [_bilibili_parent_without_series_name()]
    classification_results = _classification_with_guessed_series_name()

    with pytest.raises(ValueError) as exc_info:
        analyze.validate_classification_results(parent_posts, classification_results)

    message = str(exc_info.value)
    # 关键字段前缀断言（不锁死完整字符串,以便实现微调措辞时不误报）
    assert "series_name" in message, (
        "ValueError 消息应当提到 series_name 以便于排错；实际消息: "
        f"{message!r}"
    )
    assert "public evidence" in message, (
        "ValueError 消息应当明确说明 series_name 必须绑定 public evidence, "
        f"实际消息: {message!r}"
    )


def test_bilibili_series_name_null_parent_null_child_is_accepted():
    """反向断言：父作品公开字段为 null、分类端也写 null 时不得被误拒。
    本测试用来防止我们把规则约束过头。
    """
    parent_posts = [_bilibili_parent_without_series_name()]
    classification_results = [_classification_with_guessed_series_name()[0]]
    classification_results[0]["series_name"] = None  # 显式 null

    try:
        analyze.validate_classification_results(parent_posts, classification_results)
    except ValueError as e:
        # 若实现抛了 ValueError,必须不是关于 series_name 与 public evidence 的,
        # 否则等于把合法 null 误拒。
        message = str(e)
        assert "series_name" not in message, (
            "合法的 null 分类结果不应触发关于 series_name 的 ValueError,"
            f"实际: {message!r}"
        )
