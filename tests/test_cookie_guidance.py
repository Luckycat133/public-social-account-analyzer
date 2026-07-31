from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cookie_guide_instructs_agents_to_accept_generic_chat_paste():
    guide = (ROOT / "skill" / "references" / "cookie-guide.md").read_text(
        encoding="utf-8"
    )

    assert "当前目标平台" in guide
    assert "Cookie: ..." in guide
    assert "Network/网络" in guide
    assert "粘贴到对话" in guide
    assert not (ROOT / "skill" / "references" / "douyin-cookie-guide.md").exists()
