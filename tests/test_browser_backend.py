"""browser_backend 离线测试：仅验证跨平台探测与 WS 帧编解码，绝不真实启动浏览器。

运行：python tests/test_browser_backend.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from collectors.browser_backend import (  # noqa: E402
    BrowserError,
    BrowserSession,
    _free_port,
    _platform_key,
    _WSClient,
    find_browser,
)


# --------------------------------------------------------------------------
# 跨平台浏览器探测（find_browser）
# --------------------------------------------------------------------------
def test_find_browser_explicit(monkeypatch):
    assert find_browser("/some/explicit/chrome") == "/some/explicit/chrome"


def test_find_browser_env_override(monkeypatch):
    monkeypatch.setenv("BROWSER_BIN", "/env/chrome")
    monkeypatch.setattr("collectors.browser_backend.shutil.which", lambda _: None)
    monkeypatch.setattr("collectors.browser_backend.os.path.exists", lambda _: False)
    assert find_browser() == "/env/chrome"


def test_find_browser_darwin_via_absolute_path(monkeypatch):
    monkeypatch.setattr("collectors.browser_backend._platform_key", lambda: "darwin")
    monkeypatch.setenv("BROWSER_BIN", "")
    monkeypatch.setenv("CHROME_BIN", "")
    monkeypatch.setattr("collectors.browser_backend.shutil.which", lambda _: None)

    def _exists(p):
        return p == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    monkeypatch.setattr("collectors.browser_backend.os.path.exists", _exists)
    assert (
        find_browser()
        == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )


def test_find_browser_linux_via_path(monkeypatch):
    monkeypatch.setattr("collectors.browser_backend._platform_key", lambda: "linux")
    monkeypatch.setenv("BROWSER_BIN", "")
    monkeypatch.setenv("CHROME_BIN", "")
    monkeypatch.setattr("collectors.browser_backend.shutil.which", lambda _: None)

    def _exists(p):
        return p == "/usr/bin/google-chrome"

    monkeypatch.setattr("collectors.browser_backend.os.path.exists", _exists)
    assert find_browser() == "/usr/bin/google-chrome"


def test_find_browser_windows_path(monkeypatch):
    monkeypatch.setattr("collectors.browser_backend._platform_key", lambda: "windows")
    monkeypatch.setenv("BROWSER_BIN", "")
    monkeypatch.setenv("CHROME_BIN", "")
    monkeypatch.setattr("collectors.browser_backend.shutil.which", lambda _: None)

    def _exists(p):
        return p == r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    monkeypatch.setattr("collectors.browser_backend.os.path.exists", _exists)
    assert find_browser() == r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def test_find_browser_not_found(monkeypatch):
    monkeypatch.setenv("BROWSER_BIN", "")
    monkeypatch.setenv("CHROME_BIN", "")
    monkeypatch.setattr("collectors.browser_backend.shutil.which", lambda _: None)
    monkeypatch.setattr("collectors.browser_backend.os.path.exists", lambda _: False)
    assert find_browser() is None


# --------------------------------------------------------------------------
# 端口与平台辅助
# --------------------------------------------------------------------------
def test_free_port_bindable():
    port = _free_port()
    assert 1024 < port < 65536
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    finally:
        s.close()


def test_platform_key_values():
    assert _platform_key() in ("darwin", "linux", "windows")


# --------------------------------------------------------------------------
# 无浏览器时的优雅报错（不真实启动）
# --------------------------------------------------------------------------
def test_session_start_no_binary_raises():
    s = BrowserSession(browser_bin="/nonexistent/browser")
    try:
        s.start()
        raise AssertionError("expected BrowserError")
    except BrowserError as e:
        assert "未找到" in str(e) or "浏览器" in str(e)


# --------------------------------------------------------------------------
# WebSocket 帧编解码（纯函数式，使用 FakeSocket，不联网）
# --------------------------------------------------------------------------
class _FakeSock:
    def __init__(self):
        self.sent = bytearray()
        self.to_recv = bytearray()

    def sendall(self, b):
        self.sent += b

    def recv(self, n):
        if not self.to_recv:
            return b""
        out = bytes(self.to_recv[:n])
        del self.to_recv[:n]
        return out

    def close(self):
        pass


def test_ws_client_frame_roundtrip():
    ws = _WSClient("ws://127.0.0.1:1/json")
    ws._sock = _FakeSock()
    # 客户端发文本帧（必须带掩码）
    ws._send_frame(b"hello", opcode=0x1)
    data = bytes(ws._sock.sent)
    assert data[0] == 0x81            # FIN + text
    assert data[1] & 0x80             # masked 位
    # 服务端回一个未掩码文本帧 "world"
    frame = bytearray()
    frame.append(0x81)
    frame.append(5)
    frame += b"world"
    ws._sock.to_recv = bytearray(frame)
    fin, op, payload = ws._read_frame()
    assert fin is True
    assert op == 0x1
    assert bytes(payload) == b"world"


def test_ws_client_fragmented_text():
    ws = _WSClient("ws://127.0.0.1:1/json")
    ws._sock = _FakeSock()
    # 续帧：首帧 FIN=0 opcode=1 "hel"，续帧 FIN=1 opcode=0(continuation) "lo"
    f1 = bytearray([0x01, 0x03]) + b"hel"
    f2 = bytearray([0x80, 0x02]) + b"lo"
    ws._sock.to_recv = bytearray(f1 + f2)
    fin1, op1, p1 = ws._read_frame()
    assert fin1 is False and op1 == 0x1 and bytes(p1) == b"hel"
    fin2, op2, p2 = ws._read_frame()
    assert fin2 is True and op2 == 0x0 and bytes(p2) == b"lo"


# --------------------------------------------------------------------------
# 浏览器降级接线（不联网、不启动浏览器，纯 mock）
# --------------------------------------------------------------------------
def test_get_json_browser_fallback_wiring(monkeypatch):
    from collectors.bilibili import Session, STOP_ACCESS_RESTRICTED, BilibiliError

    monkeypatch.setattr("collectors.bilibili._backoff", lambda _: 0)
    s = Session(browser_fallback=True)
    s._wbi = ("a" * 64, "b" * 64)  # 跳过真实 wbi 刷新（需 64 字符密钥）

    def _boom(*a, **k):
        raise BilibiliError(STOP_ACCESS_RESTRICTED, "WAF -412")

    monkeypatch.setattr(s, "_curl", _boom)
    monkeypatch.setattr(s, "ensure_buvid", lambda *a, **k: None)
    monkeypatch.setattr(
        s, "_fetch_via_browser", lambda full, referer: '{"code":0,"data":{"x":1}}'
    )
    data = s.get_json("/x/space/wbi/arc/search", {"mid": 1}, wbi=True)
    assert data["data"]["x"] == 1


def test_get_json_no_fallback_raises_on_waf(monkeypatch):
    from collectors.bilibili import Session, STOP_ACCESS_RESTRICTED, BilibiliError

    monkeypatch.setattr("collectors.bilibili._backoff", lambda _: 0)
    s = Session(browser_fallback=False)
    s._wbi = ("a" * 64, "b" * 64)

    def _boom(*a, **k):
        raise BilibiliError(STOP_ACCESS_RESTRICTED, "WAF -412")

    monkeypatch.setattr(s, "_curl", _boom)
    monkeypatch.setattr(s, "ensure_buvid", lambda *a, **k: None)
    try:
        s.get_json("/x/space/wbi/arc/search", {"mid": 1}, wbi=True)
        raise AssertionError("expected BilibiliError")
    except BilibiliError as e:
        assert e.stop_reason == STOP_ACCESS_RESTRICTED


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
