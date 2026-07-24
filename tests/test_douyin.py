"""Offline tests for the pure Douyin browser-response parsers."""

from collectors._constants import STOP_LOGIN, STOP_VERIFICATION


AWEME = {
    "aweme_id": "7001",
    "desc": "公开作品 #测试",
    "create_time": 1700000000,
    "statistics": {"digg_count": 12, "comment_count": 3},
    "video": {"duration": 9000},
}


def test_extract_aweme_items_deduplicates_nested_lists():
    from collectors._douyin_browser_transport import extract_aweme_items

    data = {"data": {"aweme_list": [AWEME, dict(AWEME)]}}
    assert [item["aweme_id"] for item in extract_aweme_items(data)] == ["7001"]


def test_extract_dom_items_only_keeps_post_links():
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://www.douyin.com/video/7002?x=1", "text": "作品二"},
        {"href": "https://www.douyin.com/search?q=x", "text": "搜索"},
    ]
    result = extract_dom_items(cards)
    assert result[0]["aweme_id"] == "7002"
    assert result[0]["statistics"] == {}
    assert result[0]["_collection_source"] == "dom"


def test_extract_dom_items_requires_exact_post_path():
    from collectors._douyin_browser_transport import extract_dom_items

    cards = [
        {"href": "https://www.douyin.com/video/7002/extra", "text": "无效"},
        {"href": "https://www.douyin.com/note/7003?x=1#part", "text": "有效"},
    ]

    result = extract_dom_items(cards)

    assert [item["aweme_id"] for item in result] == ["7003"]
    assert result[0]["share_url"] == "https://www.douyin.com/note/7003"


def test_restriction_priority_and_url_sanitization():
    from collectors._douyin_browser_transport import (
        detect_restriction,
        sanitize_response_url,
    )

    assert detect_restriction("请先登录并完成滑动验证") == STOP_VERIFICATION
    assert detect_restriction("登录后查看") == STOP_LOGIN
    assert sanitize_response_url("https://www.douyin.com/aweme/post/?secret=1#x") == (
        "https://www.douyin.com/aweme/post/"
    )
