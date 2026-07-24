"""browser_backend 离线测试：仅验证跨平台探测与 WS 帧编解码，绝不真实启动浏览器。

运行：python tests/test_browser_backend.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
from collections import deque

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_REPO_ROOT, "skill", "scripts"), os.path.join(_REPO_ROOT, "scripts")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

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


def test_session_rejects_user_data_dir_override(tmp_path):
    with pytest.raises(TypeError):
        BrowserSession(port=9222, user_data_dir=str(tmp_path))


def test_start_connect_failure_cleans_owned_resources(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

    proc = FakeProc()
    session = BrowserSession(browser_bin="/fake/browser", port=9222)
    profile_dir = session._user_data_dir
    real_exists = os.path.exists
    monkeypatch.setattr("collectors.browser_backend.os.path.exists", lambda _: True)
    monkeypatch.setattr("collectors.browser_backend.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(session, "_wait_for_devtools", lambda: None)
    monkeypatch.setattr(session, "_connect", lambda: (_ for _ in ()).throw(BrowserError("connect failed")))

    with pytest.raises(BrowserError, match="connect failed"):
        session.start()

    assert proc.terminated is True
    assert not real_exists(profile_dir)


def test_start_preserves_browser_error_when_cleanup_fails(monkeypatch):
    session = BrowserSession(browser_bin="/fake/browser", port=9222)
    real_close = session.close
    monkeypatch.setattr("collectors.browser_backend.os.path.exists", lambda _: True)
    monkeypatch.setattr("collectors.browser_backend.subprocess.Popen", lambda *args, **kwargs: object())
    monkeypatch.setattr(session, "_wait_for_devtools", lambda: None)
    monkeypatch.setattr(session, "_connect", lambda: (_ for _ in ()).throw(BrowserError("connect failed")))
    monkeypatch.setattr(session, "close", lambda: (_ for _ in ()).throw(OSError("cleanup failed")))

    with pytest.raises(BrowserError, match="connect failed"):
        session.start()

    real_close()


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


class QueueWS:
    def __init__(self, messages):
        self.messages, self.sent, self.timeout = list(messages), [], None

    def send_text(self, text):
        self.sent.append(json.loads(text))

    def recv_message(self):
        return self.messages.pop(0) if self.messages else None

    def set_timeout(self, timeout):
        self.timeout = timeout


def test_send_cdp_preserves_async_events():
    from collectors.browser_backend import BrowserSession

    session = BrowserSession.__new__(BrowserSession)
    session._ws = QueueWS([
        {"method": "Network.responseReceived", "params": {"requestId": "r1"}},
        {"id": 1, "result": {"ok": True}},
    ])
    session._cmd_id, session._events = 0, deque()
    assert session._send_cdp("Network.enable", {}) == {"ok": True}
    assert session.drain_events("Network.responseReceived")[0]["params"]["requestId"] == "r1"


def test_get_response_body_decodes_base64():
    from collectors.browser_backend import BrowserSession

    session = BrowserSession.__new__(BrowserSession)
    session._send_cdp = lambda method, params: {
        "body": "eyJhd2VtZV9saXN0IjpbXX0=", "base64Encoded": True
    }
    assert session.get_response_body("r1") == '{"aweme_list":[]}'


def test_poll_event_reads_event_and_restores_timeout():
    session = BrowserSession.__new__(BrowserSession)
    session._ws = QueueWS([{"method": "Page.loadEventFired", "params": {}}])
    session._events, session._startup_timeout = deque(), 20.0

    assert session.poll_event(0.5)["method"] == "Page.loadEventFired"
    assert session._ws.timeout == 20.0


def test_connect_enables_page_domain(monkeypatch):
    class FakeWS:
        def __init__(self, url, timeout):
            self.url, self.timeout = url, timeout

        def connect(self):
            pass

    session = BrowserSession.__new__(BrowserSession)
    session._ws_url, session._startup_timeout = "ws://example.test", 20.0
    enabled = []
    session._send_cdp = lambda method, params: enabled.append(method) or {}
    monkeypatch.setattr("collectors.browser_backend._WSClient", FakeWS)

    session._connect()

    assert enabled == ["Runtime.enable", "Network.enable", "Page.enable"]


def test_evaluate_returns_cdp_value():
    session = BrowserSession.__new__(BrowserSession)
    calls = []
    session._send_cdp = lambda method, params: calls.append((method, params)) or {
        "result": {"value": "ok"}
    }

    assert session.evaluate("1 + 1", await_promise=True) == "ok"
    assert calls == [("Runtime.evaluate", {
        "expression": "1 + 1", "awaitPromise": True,
        "returnByValue": True, "userGesture": False,
    })]


def test_fetch_text_uses_evaluate():
    session = BrowserSession.__new__(BrowserSession)
    calls = []
    session.evaluate = lambda expression, await_promise=False: calls.append(
        (expression, await_promise)
    ) or "response body"

    assert session.fetch_text("https://example.test/api", {"Referer": "https://example.test"}) == "response body"
    assert calls[0][1] is True
    assert "fetch(\"https://example.test/api\"" in calls[0][0]


def test_navigate_waits_for_load_event():
    session = BrowserSession.__new__(BrowserSession)
    calls = []
    session._events = deque()
    session._send_cdp = lambda method, params: calls.append((method, params)) or {}
    session.poll_event = lambda timeout: {"method": "Page.loadEventFired"}

    assert session.navigate("https://example.test") is None
    assert calls == [("Page.navigate", {"url": "https://example.test"})]


def test_navigate_ignores_stale_load_event_but_observes_fresh_one():
    session = BrowserSession.__new__(BrowserSession)
    session._ws = QueueWS([
        {"method": "Page.loadEventFired", "params": {"marker": "fresh"}},
        {"id": 1, "result": {}},
    ])
    session._cmd_id = 0
    session._events = deque([
        {"method": "Page.loadEventFired", "params": {"marker": "stale"}},
    ])
    seen = []
    poll_event = BrowserSession.poll_event

    def record_poll_event(timeout):
        event = poll_event(session, timeout)
        seen.append(event["params"]["marker"])
        return event

    session.poll_event = record_poll_event

    session.navigate("https://example.test")

    assert seen == ["fresh"]


def test_navigate_restores_non_load_events_in_original_order():
    """Network events observed before load stay available to the transport."""
    session = BrowserSession.__new__(BrowserSession)
    network = {
        "method": "Network.responseReceived",
        "params": {"requestId": "first-screen"},
    }
    after_load = {
        "method": "Network.loadingFinished",
        "params": {"requestId": "first-screen"},
    }
    session._events = deque()

    def navigate_command(method, params):
        session._events.extend([
            network,
            {"method": "Page.loadEventFired", "params": {}},
            after_load,
        ])
        return {}

    session._send_cdp = navigate_command

    session.navigate("https://www.douyin.com/user/example")

    assert list(session._events) == [network, after_load]


def test_page_apis_forward_bounded_command_timeouts():
    """Every potentially blocking page command accepts the remaining budget."""
    session = BrowserSession.__new__(BrowserSession)
    calls = []

    def send(method, params, timeout=None):
        calls.append((method, timeout))
        if method == "Runtime.evaluate":
            return {"result": {"value": "visible"}}
        return {"body": "{}", "base64Encoded": False}

    session._send_cdp = send

    assert session.page_text(timeout=0.4) == "visible"
    assert session.get_response_body("r1", timeout=0.3) == "{}"
    session.scroll_by(1, timeout=0.2)

    assert calls == [
        ("Runtime.evaluate", 0.4),
        ("Network.getResponseBody", 0.3),
        ("Runtime.evaluate", 0.2),
    ]


def test_scroll_by_evaluates_at_least_one_viewport():
    session = BrowserSession.__new__(BrowserSession)
    calls = []
    session.evaluate = lambda expression: calls.append(expression)

    session.scroll_by(0)

    assert calls == ["window.scrollBy(0, window.innerHeight * 1); true"]


def test_page_text_returns_only_string_values():
    session = BrowserSession.__new__(BrowserSession)
    session.evaluate = lambda expression: 42

    assert session.page_text() == ""


def test_close_kills_waits_and_retries_profile_cleanup(monkeypatch):
    """A timed-out browser is reaped before its temporary profile is removed."""

    class StuckProc:
        def __init__(self):
            self.calls = []
            self.wait_count = 0

        def terminate(self):
            self.calls.append("terminate")

        def wait(self, timeout):
            self.calls.append(("wait", timeout))
            self.wait_count += 1
            if self.wait_count == 1:
                raise subprocess.TimeoutExpired("chrome", timeout)
            return 0

        def kill(self):
            self.calls.append("kill")

    session = BrowserSession(port=9222)
    proc = StuckProc()
    session._proc = proc
    profile_dir = session._user_data_dir
    real_rmtree = shutil.rmtree
    attempts = []

    def flaky_rmtree(path):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError("profile still locked")
        real_rmtree(path)

    monkeypatch.setattr("collectors.browser_backend.shutil.rmtree", flaky_rmtree)
    monkeypatch.setattr("collectors.browser_backend.time.sleep", lambda _: None)

    session.close()

    assert proc.calls == ["terminate", ("wait", 5), "kill", ("wait", 5)]
    assert attempts == [profile_dir, profile_dir, profile_dir]
    assert session.cleanup_diagnostics == ()
    assert not os.path.exists(profile_dir)


def test_close_reports_sanitized_cleanup_failure_without_raising(monkeypatch):
    """Cleanup failure is observable without disclosing the profile path."""
    session = BrowserSession(port=9222)
    profile_dir = session._user_data_dir
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(
        "collectors.browser_backend.shutil.rmtree",
        lambda path: (_ for _ in ()).throw(PermissionError(path)),
    )
    monkeypatch.setattr("collectors.browser_backend.time.sleep", lambda _: None)

    session.close()

    assert session.cleanup_diagnostics == ("PROFILE_REMOVE_FAILED",)
    assert profile_dir not in repr(session.cleanup_diagnostics)

    # The method remains idempotent and never replaces an active exception.
    session.close()
    real_rmtree(profile_dir)


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
