"""CASE-001（null 与 0）、CASE-005（中文数字单位）、CASE-011（字段覆盖率）。

全部离线、确定性，直接调用 normalize 纯函数：
- parse_metric：页面显示 0 → 0（visible）；页面未显示 → None（hidden）。
- parse_metric：中文单位 万/亿 → 整数换算。
- compute_metric_coverage：各指标在有效样本中非 null 比例。
"""
import normalize


# ---------------------------------------------------------------------------
# CASE-001：null 与 0 必须区分
# ---------------------------------------------------------------------------
def test_likes_shown_zero_is_zero_not_null():
    value, status = normalize.parse_metric("0")
    assert value == 0
    assert status == "visible"  # 页面明确显示 0 → 真实零值，非 hidden


def test_views_missing_is_null():
    value, status = normalize.parse_metric(None)
    assert value is None
    assert status == "hidden"  # 未显示该字段 → null，绝不写 0


def test_likes_zero_int_passthrough():
    value, status = normalize.parse_metric(0)
    assert value == 0
    assert status == "visible"


# ---------------------------------------------------------------------------
# CASE-005：中文数字单位转换
# ---------------------------------------------------------------------------
def test_chinese_wan_1_2():
    value, _ = normalize.parse_metric("1.2万")
    assert value == 12000


def test_chinese_wan_10():
    value, _ = normalize.parse_metric("10万")
    assert value == 100000


def test_chinese_yi_3_4():
    value, _ = normalize.parse_metric("3.4亿")
    assert value == 340000000


def test_chinese_wan_with_noise():
    # 含「播放」「赞」等噪声字符时仍正确换算
    value, status = normalize.parse_metric("12.3万播放")
    assert value == 123000
    assert status == "visible"


# ---------------------------------------------------------------------------
# CASE-011：字段覆盖率（各指标非 null 比例）
# ---------------------------------------------------------------------------
def _row_with_visibility(overrides):
    vis = {f: "hidden" for f in normalize.METRIC_FIELDS}
    vis.update(overrides)
    return {"_visibility": vis}


def test_field_coverage_present_rate():
    rows = [
        _row_with_visibility({"views": "visible", "likes": "visible"}),
        _row_with_visibility({"views": "visible"}),
        _row_with_visibility({}),  # 全 hidden
    ]
    cov = normalize.compute_metric_coverage(rows)
    assert cov["views"]["present"] == 2
    assert cov["views"]["missing"] == 1
    assert cov["views"]["missing_rate"] == round(1 / 3, 4)
    assert cov["likes"]["present"] == 1
    assert cov["likes"]["missing"] == 2


def test_field_coverage_all_hidden():
    rows = [_row_with_visibility({}), _row_with_visibility({})]
    cov = normalize.compute_metric_coverage(rows)
    for f in normalize.METRIC_FIELDS:
        assert cov[f]["present"] == 0
        assert cov[f]["missing_rate"] == 1.0


def test_field_coverage_via_normalize_pipeline():
    # 端到端走 normalize_post：likes=0 算 visible，views 缺失算 hidden
    raw_posts = [
        {"platform": "bilibili", "post_id": "1", "views": 100, "likes": 0},
        {"platform": "bilibili", "post_id": "2"},  # views/likes 均未给
    ]
    rows = [normalize.normalize_post(p)[0] for p in raw_posts]
    cov = normalize.compute_metric_coverage(rows)
    # views: 1 条 visible，1 条 hidden
    assert cov["views"]["present"] == 1 and cov["views"]["missing"] == 1
    # likes: 0 是真实零值，仍计入 present
    assert cov["likes"]["present"] == 1 and cov["likes"]["missing"] == 1
