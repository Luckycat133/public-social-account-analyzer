"""CASE-002（同平台同 post_id 去重）、CASE-003（跨平台相同 post_id 保留）。

验证 normalize.dedup_posts 按 (platform, post_id) 唯一键去重：
- 同平台同 post_id → 只保留首条，duplicate_count 计数。
- 跨平台同 post_id → 两条均保留（见 data-schema.md §1：「platform + post_id 唯一」）。
"""
import normalize


# ---------------------------------------------------------------------------
# CASE-002：同平台同 post_id 去重
# ---------------------------------------------------------------------------
def test_same_platform_same_post_id_dedup():
    raw = [
        {"platform": "bilibili", "post_id": "BV123", "title": "first"},
        {"platform": "bilibili", "post_id": "BV123", "title": "dup"},
        {"platform": "bilibili", "post_id": "BV456"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 2
    assert dup == 1
    # 保留的是首次出现的那条
    assert kept[0]["title"] == "first"
    ids = [(p["platform"], p["post_id"]) for p in kept]
    assert ids == [("bilibili", "BV123"), ("bilibili", "BV456")]


# ---------------------------------------------------------------------------
# CASE-003：跨平台相同 post_id 不去重
# ---------------------------------------------------------------------------
def test_cross_platform_same_post_id_kept():
    raw = [
        {"platform": "bilibili", "post_id": "123"},
        {"platform": "douyin", "post_id": "123"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 2
    assert dup == 0
    platforms = sorted(p["platform"] for p in kept)
    assert platforms == ["bilibili", "douyin"]


# ---------------------------------------------------------------------------
# 边界：无重复 / 缺失 post_id 不互判重复
# ---------------------------------------------------------------------------
def test_no_duplicate_when_unique():
    raw = [
        {"platform": "bilibili", "post_id": "BV1"},
        {"platform": "bilibili", "post_id": "BV2"},
        {"platform": "douyin", "post_id": "DV1"},
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 3
    assert dup == 0


def test_missing_post_id_not_collapsed():
    # 缺失 post_id 的行用哨兵键保活，不应互相判重
    raw = [
        {"platform": "bilibili"},  # 无 post_id
        {"platform": "bilibili"},  # 无 post_id
    ]
    kept, dup = normalize.dedup_posts(raw)
    assert len(kept) == 2
    assert dup == 0
