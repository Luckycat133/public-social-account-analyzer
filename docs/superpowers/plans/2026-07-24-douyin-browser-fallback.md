# Douyin Browser Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Douyin public-post collection work through an automatic, zero-Python-dependency Chrome/CDP fallback while preserving compliance boundaries and partial results.

**Architecture:** Keep the existing `urllib`/SSR path as the fast path. Add platform-neutral CDP page/event APIs to `BrowserSession`, then add a Douyin-only transport that observes public JSON responses and falls back to visible DOM cards. `DouyinCollector` remains the field-mapping layer; `collect.py` owns CLI policy and task persistence.

**Tech Stack:** Python 3.9+ standard library, Chrome DevTools Protocol, the repository's standard-library WebSocket client, pytest as a development-only dependency, Markdown.

## Global Constraints

- Runtime dependencies remain exactly `[]`; do not add pip or npm runtime packages.
- A system Chrome, Chromium, Edge, or Brave binary is an optional prerequisite discovered through `BROWSER_BIN`, `CHROME_BIN`, or existing candidates.
- Every task uses a new temporary browser profile and removes it on exit; never attach to the user's normal profile or login state.
- Never reproduce signatures, solve challenges, rotate proxies, or retry through login, CAPTCHA, slider, or rate-limit protections.
- Never persist cookies, request headers, signed query strings, full response bodies, or media.
- Unknown public metrics remain `None`, never inferred or replaced with zero.
- Browser collection limits: 90 seconds, 20 scroll rounds, 3 consecutive idle rounds, and at most 100 posts.
- Public `stop_reason` values remain unchanged. Browser absence is a sanitized `BROWSER_UNAVAILABLE` diagnostic and public `PARSER_FAILED`.
- Development-only pytest installation is allowed via `python3 -m pip install -e ".[dev]"`.

---

## File Map

- Modify `skill/scripts/collectors/browser_backend.py`: generic event-safe CDP page APIs.
- Create `skill/scripts/collectors/_douyin_browser_transport.py`: Douyin response/DOM parsing and bounded browser loop.
- Modify `skill/scripts/collectors/douyin.py`: automatic fallback, shared mapping, partial-result errors.
- Modify `skill/scripts/collect.py`: CLI policy and partial-result persistence.
- Modify `tests/test_browser_backend.py`; create `tests/test_douyin.py`.
- Modify `README.md`, `USAGE.md`, `ROADMAP.md`, `CHANGELOG.md`, and `skill/references/platform-douyin.md`.
- Create `docs/observations/douyin-browser-fallback-acceptance.md` after live validation.

---

### Task 1: Event-Safe CDP Page APIs

**Files:**
- Modify: `skill/scripts/collectors/browser_backend.py:19-28,268-416`
- Modify: `tests/test_browser_backend.py`

**Interfaces:**
- Consumes: `_WSClient.recv_message()`, `BrowserSession._send_cdp()`.
- Produces: `navigate`, `evaluate`, `poll_event`, `drain_events`, `get_response_body`, `scroll_by`, and `page_text`.

- [ ] **Step 1: Write failing event and response-body tests**

Add imports `json`, `socket`, and `deque`, then append:

```python
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
```

- [ ] **Step 2: Run RED**

Run: `python3 -m pytest tests/test_browser_backend.py::test_send_cdp_preserves_async_events tests/test_browser_backend.py::test_get_response_body_decodes_base64 -v`

Expected: FAIL because event preservation and response-body APIs do not exist.

- [ ] **Step 3: Implement event preservation**

Add `from collections import deque`, initialize `self._events = deque()`, add `_WSClient.set_timeout`, and replace the command loop:

```python
def set_timeout(self, timeout: float) -> None:
    self._timeout = timeout
    if self._sock is not None:
        self._sock.settimeout(timeout)

def _send_cdp(self, method: str, params: dict) -> dict:
    assert self._ws is not None
    self._cmd_id += 1
    cid = self._cmd_id
    self._ws.send_text(json.dumps({"id": cid, "method": method, "params": params}))
    while True:
        msg = self._ws.recv_message()
        if msg is None:
            raise BrowserError("浏览器连接在处理 CDP 指令时关闭")
        if msg.get("method"):
            self._events.append(msg)
            continue
        if msg.get("id") != cid:
            continue
        if "error" in msg:
            raise BrowserError(f"CDP {method} 失败: {msg['error']}")
        return msg.get("result", {})

def poll_event(self, timeout: float = 1.0) -> Optional[dict]:
    if self._events:
        return self._events.popleft()
    assert self._ws is not None
    self._ws.set_timeout(timeout)
    try:
        while True:
            msg = self._ws.recv_message()
            if msg is None:
                raise BrowserError("浏览器连接在等待 CDP 事件时关闭")
            if msg.get("method"):
                return msg
    except socket.timeout:
        return None
    finally:
        self._ws.set_timeout(self._startup_timeout)

def drain_events(self, method: Optional[str] = None) -> list[dict]:
    matched, remaining = [], deque()
    while self._events:
        event = self._events.popleft()
        (matched if method is None or event.get("method") == method else remaining).append(event)
    self._events = remaining
    return matched
```

- [ ] **Step 4: Add page APIs**

Enable `Page.enable` in `_connect`, refactor `fetch_text` through `evaluate`, and add:

```python
def evaluate(self, expression: str, await_promise: bool = False) -> Any:
    result = self._send_cdp("Runtime.evaluate", {
        "expression": expression, "awaitPromise": await_promise,
        "returnByValue": True, "userGesture": False,
    })
    if "exceptionDetails" in result:
        raise BrowserError(f"浏览器脚本执行失败: {result['exceptionDetails'].get('text')}")
    return result.get("result", {}).get("value")

def navigate(self, url: str, timeout: float = 30.0) -> None:
    result = self._send_cdp("Page.navigate", {"url": url})
    if result.get("errorText"):
        raise BrowserError(f"页面导航失败: {result['errorText']}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = self.poll_event(min(1.0, deadline - time.monotonic()))
        if event and event.get("method") == "Page.loadEventFired":
            return
    raise BrowserError(f"页面加载超时: {url}")

def get_response_body(self, request_id: str) -> str:
    result = self._send_cdp("Network.getResponseBody", {"requestId": request_id})
    body = result.get("body", "")
    if result.get("base64Encoded"):
        return base64.b64decode(body).decode("utf-8", errors="replace")
    return body

def scroll_by(self, viewports: int = 1) -> None:
    self.evaluate(f"window.scrollBy(0, window.innerHeight * {max(1, int(viewports))}); true")

def page_text(self) -> str:
    value = self.evaluate("document.body ? document.body.innerText : ''")
    return value if isinstance(value, str) else ""
```

- [ ] **Step 5: Run GREEN and commit**

Run: `python3 -m pytest tests/test_browser_backend.py -v`

Expected: all browser-backend tests pass without launching a real browser.

```bash
git add skill/scripts/collectors/browser_backend.py tests/test_browser_backend.py
git commit -m "feat: add event-safe CDP page APIs"
```

---

### Task 2: Pure Douyin Response and DOM Parsers

**Files:**
- Create: `skill/scripts/collectors/_douyin_browser_transport.py`
- Create: `tests/test_douyin.py`

**Interfaces:**
- Produces `DouyinBrowserResult`, `detect_restriction`, `sanitize_response_url`, `extract_aweme_items`, and `extract_dom_items`.

- [ ] **Step 1: Write failing parser tests**

```python
import json
import pytest

from collectors._constants import STOP_LOGIN, STOP_VERIFICATION

AWEME = {
    "aweme_id": "7001", "desc": "公开作品 #测试",
    "create_time": 1700000000,
    "statistics": {"digg_count": 12, "comment_count": 3},
    "video": {"duration": 9000},
}

def test_extract_aweme_items_deduplicates_nested_lists():
    from collectors._douyin_browser_transport import extract_aweme_items
    data = {"data": {"aweme_list": [AWEME, dict(AWEME)]}}
    assert [x["aweme_id"] for x in extract_aweme_items(data)] == ["7001"]

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

def test_restriction_priority_and_url_sanitization():
    from collectors._douyin_browser_transport import detect_restriction, sanitize_response_url
    assert detect_restriction("请先登录并完成滑动验证") == STOP_VERIFICATION
    assert detect_restriction("登录后查看") == STOP_LOGIN
    assert sanitize_response_url("https://www.douyin.com/aweme/post/?secret=1#x") == (
        "https://www.douyin.com/aweme/post/"
    )
```

- [ ] **Step 2: Run RED**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: import failure for the new module.

- [ ] **Step 3: Implement the pure model and parsers**

Create the module with a standard-library dataclass, ordered restriction regexes, query/fragment removal through `urllib.parse.urlsplit/urlunsplit`, recursive traversal limited to depth 10 for keys `aweme_list`, `awemeList`, `post_list`, `aweme_detail`, and `awemeDetail`, and deduplication by `aweme_id` or `aweme_id_str`.

Use this exact result contract:

```python
@dataclass
class DouyinBrowserResult:
    profile_raw: dict[str, Any] | None = None
    aweme_items: list[dict[str, Any]] = field(default_factory=list)
    source: str = "network"
    restriction: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
```

DOM items must be shaped exactly as:

```python
{
    "aweme_id": post_id,
    "desc": visible_text,
    "share_url": sanitized_post_url,
    "statistics": {},
    "_collection_source": "dom",
}
```

Reject non-`/video/<digits>` and non-`/note/<digits>` links.

Implement the helpers with these exact shapes:

```python
def detect_restriction(text: str) -> str | None:
    for pattern, reason in _RESTRICTIONS:
        if pattern.search(text or ""):
            return reason
    return None

def sanitize_response_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

def extract_aweme_items(data: Any) -> list[dict[str, Any]]:
    found = []
    def walk(value: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"aweme_list", "awemeList", "post_list"} and isinstance(child, list):
                    found.extend(x for x in child if isinstance(x, dict) and (x.get("aweme_id") or x.get("aweme_id_str")))
                elif key in {"aweme_detail", "awemeDetail"} and isinstance(child, dict):
                    if child.get("aweme_id") or child.get("aweme_id_str"):
                        found.append(child)
                else:
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)
    walk(data)
    unique = {}
    for item in found:
        unique.setdefault(str(item.get("aweme_id") or item.get("aweme_id_str")), item)
    return list(unique.values())

def extract_dom_items(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for card in cards:
        href = str(card.get("href") or "")
        match = re.search(r"/(?:video|note)/(\d+)", href)
        if not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        out.append({
            "aweme_id": match.group(1),
            "desc": str(card.get("text") or "").strip(),
            "share_url": sanitize_response_url(href),
            "statistics": {},
            "_collection_source": "dom",
        })
    return out
```

- [ ] **Step 4: Run GREEN and commit**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: three tests pass.

```bash
git add skill/scripts/collectors/_douyin_browser_transport.py tests/test_douyin.py
git commit -m "feat: add Douyin browser response parsers"
```

---

### Task 3: Bounded Browser Collection Loop

**Files:**
- Modify: `skill/scripts/collectors/_douyin_browser_transport.py`
- Modify: `tests/test_douyin.py`

**Interfaces:**
- Consumes Task 1 browser APIs and Task 2 parsers.
- Produces `collect_account_page(url, *, limit, date_range=None, session_factory=BrowserSession, monotonic=time.monotonic, sleep=time.sleep)`.

- [ ] **Step 1: Add a fake browser and failing loop tests**

The fake must implement context management, `navigate`, `poll_event`, `get_response_body`, `page_text`, `scroll_by`, and `evaluate`. Add three tests:

1. A `Network.responseReceived` event with an allowed Douyin host and JSON body returns `AWEME`, and diagnostics contain only the URL without query/fragment.
2. A later page text containing “滑动验证” returns `restriction=VERIFICATION_REQUIRED` while retaining the already captured item.
3. No network items plus an evaluated DOM card returns `source="dom"`.

Use this event:

```python
{
    "method": "Network.responseReceived",
    "params": {
        "requestId": "r1", "type": "Fetch",
        "response": {
            "url": "https://www.douyin.com/aweme/v1/web/aweme/post/?signed=secret",
            "mimeType": "application/json",
        },
    },
}
```

- [ ] **Step 2: Run RED**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: FAIL because `collect_account_page` does not exist.

- [ ] **Step 3: Implement allowed-response filtering**

Accept only `douyin.com` and `iesdouyin.com` hosts (including subdomains), and only JSON, XHR, or Fetch responses. Return `(request_id, sanitized_url)`; never store query strings.

- [ ] **Step 4: Implement the bounded loop**

Use constants `MAX_SECONDS=90.0`, `MAX_SCROLLS=20`, and `MAX_IDLE_ROUNDS=3`. The loop must:

- clamp `limit` to 1–100;
- navigate once;
- poll events and JSON-decode response bodies in memory;
- deduplicate by post ID;
- check `page_text()` after each poll;
- stop immediately on a restriction;
- scroll only after an idle poll, wait a fixed 1.0 seconds, and never add randomized anti-detection behavior;
- perform one DOM-card extraction after the network loop when not restricted;
- return only sanitized counts, response paths, scroll rounds, and stop condition in diagnostics.

Use this DOM expression:

```javascript
Array.from(document.querySelectorAll('a[href*="/video/"],a[href*="/note/"]')).map(a => ({
  href: a.href,
  text: (a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || '').trim()
}))
```

Keep `date_range` in the interface; normalized date filtering remains authoritative in Task 4 because DOM cards may not expose dates.

The central loop must follow this implementation pattern:

```python
def collect_account_page(url, *, limit, date_range=None, session_factory=BrowserSession,
                         monotonic=time.monotonic, sleep=time.sleep):
    requested = max(1, min(int(limit), 100))
    started, items, safe_paths = monotonic(), {}, []
    restriction, scrolls, idle = None, 0, 0
    with session_factory() as session:
        session.navigate(url, timeout=30.0)
        while len(items) < requested and scrolls <= MAX_SCROLLS:
            if monotonic() - started >= MAX_SECONDS:
                break
            before = len(items)
            event = session.poll_event(timeout=1.0)
            candidate = _allowed_response(event or {})
            if candidate:
                request_id, safe_url = candidate
                try:
                    decoded = json.loads(session.get_response_body(request_id))
                except (ValueError, TypeError, UnicodeError, RuntimeError):
                    decoded = None
                for item in extract_aweme_items(decoded):
                    key = str(item.get("aweme_id") or item.get("aweme_id_str"))
                    items.setdefault(key, item)
                if decoded is not None and safe_url not in safe_paths:
                    safe_paths.append(safe_url)
            restriction = detect_restriction(session.page_text())
            if restriction or len(items) >= requested:
                break
            if event is None:
                idle = idle + 1 if len(items) == before else 0
                if idle >= MAX_IDLE_ROUNDS:
                    break
                session.scroll_by(1)
                scrolls += 1
                sleep(1.0)
        network_count = len(items)
        if not restriction and len(items) < requested:
            for item in extract_dom_items(_dom_cards(session)):
                items.setdefault(str(item["aweme_id"]), item)
    final = list(items.values())[:requested]
    dom_count = sum(x.get("_collection_source") == "dom" for x in final)
    source = "network+dom" if network_count and dom_count else "dom" if dom_count else "network"
    return DouyinBrowserResult(
        aweme_items=final, source=source, restriction=restriction,
        diagnostics={"scroll_rounds": scrolls, "candidate_response_count": len(safe_paths),
                     "response_paths": safe_paths,
                     "stop_condition": restriction or ("limit" if len(final) >= requested else "idle_or_timeout")},
    )
```

- [ ] **Step 5: Run GREEN and commit**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: parser and fake-browser tests pass without a real browser.

```bash
git add skill/scripts/collectors/_douyin_browser_transport.py tests/test_douyin.py
git commit -m "feat: observe Douyin posts through bounded CDP"
```

---

### Task 4: Integrate Automatic Fallback and Partial Results

**Files:**
- Modify: `skill/scripts/collectors/douyin.py:75-82,171-176,383-426`
- Modify: `tests/test_douyin.py`

**Interfaces:**
- Consumes `DouyinBrowserResult`.
- Produces injectable `DouyinCollector(browser_fallback=True, browser_collect=collect_account_page)` and `DouyinError.partial_posts`.

- [ ] **Step 1: Add failing adapter tests**

Add tests proving:

- a valid SSR fixture never calls the browser;
- missing SSR calls the injected browser and maps `AWEME` through existing `_build_post_raw`/`normalize_post`;
- `browser_fallback=False` keeps `PARSER_FAILED`;
- a browser result with one item plus `VERIFICATION_REQUIRED` raises `DouyinError` whose `partial_posts[0]["post_id"] == "7001"`.

- [ ] **Step 2: Run RED**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: constructor and partial-result assertions fail.

- [ ] **Step 3: Extend the error and collector constructors**

```python
class DouyinError(Exception):
    def __init__(
        self, stop_reason: str, message: str, raw: Any = None,
        partial_posts: list[dict[str, Any]] | None = None,
        diagnostic_code: str | None = None,
    ):
        super().__init__(message)
        self.stop_reason, self.message, self.raw = stop_reason, message, raw
        self.partial_posts = list(partial_posts or [])
        self.diagnostic_code = diagnostic_code

class DouyinCollector(BaseCollector):
    platform = "douyin"

    def __init__(self, browser_fallback: bool = True, browser_collect=None):
        if browser_collect is None:
            from ._douyin_browser_transport import collect_account_page
            browser_collect = collect_account_page
        self.browser_fallback = bool(browser_fallback)
        self._browser_collect = browser_collect
```

- [ ] **Step 4: Replace the immediate missing-SSR failure**

When `data is None`:

1. If disabled, raise `PARSER_FAILED`.
2. Call the injected browser transport.
3. Map every returned raw item through existing mapping functions.
4. Apply existing `_filter_by_date` and limit.
5. If restricted, raise `DouyinError(..., partial_posts=posts, raw=result.diagnostics)`.
6. If empty and unrestricted, raise `PARSER_FAILED`.
7. Wrap browser startup errors as `PARSER_FAILED` with `BROWSER_UNAVAILABLE` when the message says no browser was found, otherwise `BROWSER_TRANSPORT_FAILED`.

Do not create a second field-mapping implementation.

Use this branch in `collect_post_list`:

```python
if data is None:
    if not self.browser_fallback:
        raise DouyinError(STOP_PARSER_FAILED, "账号主页无 RENDER_DATA，且浏览器降级已禁用")
    try:
        result = self._browser_collect(url=url, limit=limit, date_range=date_range)
    except Exception as exc:
        code = "BROWSER_UNAVAILABLE" if "未找到可用的浏览器" in str(exc) else "BROWSER_TRANSPORT_FAILED"
        raise DouyinError(STOP_PARSER_FAILED, f"抖音浏览器降级失败: {exc}", diagnostic_code=code) from exc
    posts = [
        self.normalize_post(self._build_post_raw(url, item, source=result.source))
        for item in result.aweme_items if isinstance(item, dict)
    ]
    if date_range:
        posts = self._filter_by_date(posts, date_range)
    posts = posts[:limit]
    if result.restriction:
        raise DouyinError(result.restriction, f"浏览器采集中止: {result.restriction}",
                          raw=result.diagnostics, partial_posts=posts)
    if not posts:
        raise DouyinError(STOP_PARSER_FAILED, "浏览器未识别到可验证的作品结构",
                          raw=result.diagnostics)
    return posts
```

- [ ] **Step 5: Run GREEN and commit**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: all explicit `DouyinCollector` tests pass.

```bash
git add skill/scripts/collectors/douyin.py tests/test_douyin.py
git commit -m "feat: integrate automatic Douyin browser fallback"
```

---

### Task 5: CLI Policy and Partial-Post Persistence

**Files:**
- Modify: `skill/scripts/collect.py:47-78,354-455,559-613`
- Modify: `tests/test_douyin.py`

**Interfaces:**
- Produces `_load_adapters(douyin_browser_fallback=True)`, `run(..., browser_fallback=None)`, `--no-browser-fallback`, and `SOCIAL_BROWSER_FALLBACK`.

- [ ] **Step 1: Add failing orchestration tests**

Add one test that calls `_load_adapters(douyin_browser_fallback=False)` and asserts the Douyin instance is disabled.

Add one fake Douyin adapter whose `collect_post_list` raises:

```python
DouyinError(STOP_VERIFICATION, "验证", partial_posts=[{
    "platform": "douyin", "post_id": "7001",
    "post_url": "https://www.douyin.com/video/7001",
    "collection_status": "SUCCESS",
}])
```

Patch `_load_adapters`, call `collect.run(..., out_dir=str(tmp_path))`, and assert:

- return code is 0;
- `task_status == "PARTIAL"`;
- `stop_reason == "VERIFICATION_REQUIRED"`;
- `source/posts.jsonl` contains one row.

- [ ] **Step 2: Run RED**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: policy parameter is unknown and partial posts are discarded.

- [ ] **Step 3: Thread policy through adapter loading**

Resolve policy in `run`:

```python
env_value = os.environ.get("SOCIAL_BROWSER_FALLBACK")
douyin_enabled = browser_fallback if browser_fallback is not None else env_value != "0"
adapters = _load_adapters(douyin_browser_fallback=douyin_enabled)
```

Construct `DouyinCollector(browser_fallback=douyin_browser_fallback)`; keep Bilibili and Weibo construction unchanged.

- [ ] **Step 4: Preserve partial posts before status calculation**

At the start of the list-collection exception branch:

```python
partial_posts = getattr(e, "partial_posts", None)
if isinstance(partial_posts, list):
    posts = partial_posts[:limit]
diagnostic_code = getattr(e, "diagnostic_code", None)
```

Only add a non-empty `diagnostic_code` to the sanitized error-log dictionary. Never log `e.raw`. Determine `PARTIAL` after assigning posts.

- [ ] **Step 5: Add exact CLI precedence**

Use a mutually exclusive group with `--browser-fallback` storing `True`, `--no-browser-fallback` storing `False`, and parser default `None`. Pass it to `run`.

Precedence: explicit flag > `SOCIAL_BROWSER_FALLBACK` > default enabled. Continue setting `BILIBILI_BROWSER_FALLBACK=1` only for an explicit positive legacy flag.

Add the flags exactly as follows:

```python
browser_group = ap.add_mutually_exclusive_group()
browser_group.add_argument("--browser-fallback", dest="browser_fallback",
                           action="store_true",
                           help="显式启用系统浏览器传输层降级。")
browser_group.add_argument("--no-browser-fallback", dest="browser_fallback",
                           action="store_false",
                           help="禁止启动系统浏览器；仅使用 HTTP/SSR 快速路径。")
ap.set_defaults(browser_fallback=None)
```

- [ ] **Step 6: Run GREEN and commit**

Run: `python3 -m pytest tests/test_douyin.py tests/test_collectors.py tests/test_incremental.py -v`

Expected: all selected tests pass and partial output is persisted.

```bash
git add skill/scripts/collect.py tests/test_douyin.py
git commit -m "feat: retain partial Douyin browser results"
```

---

### Task 6: Truthful Documentation and Experimental Status

**Files:**
- Modify: `README.md:59-65`
- Modify: `USAGE.md:15-55,95-103,150-165`
- Modify: `ROADMAP.md:1-4,40-49`
- Modify: `CHANGELOG.md:8-20`
- Modify: `skill/references/platform-douyin.md:126-155`
- Modify: `tests/test_douyin.py`

**Interfaces:** Documents the exact Task 5 behavior without claiming live acceptance.

- [ ] **Step 1: Add a failing documentation assertion**

```python
def test_docs_describe_zero_python_dependency_browser_fallback():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    usage = (root / "USAGE.md").read_text()
    platform = (root / "skill/references/platform-douyin.md").read_text()
    assert "实验性支持" in readme
    assert "--no-browser-fallback" in usage
    assert "SOCIAL_BROWSER_FALLBACK" in usage
    assert "不新增 pip" in platform
    assert "临时用户目录" in platform
```

Run: `python3 -m pytest tests/test_douyin.py::test_docs_describe_zero_python_dependency_browser_fallback -v`

Expected: FAIL on current green/undocumented status.

- [ ] **Step 2: Update maturity and usage**

- README: mark Douyin `🟡 P0（实验性支持）`; describe SSR → CDP network → DOM.
- Roadmap: remove the unqualified “all P0 completed and verified” claim until live acceptance.
- USAGE: document default automatic fallback, `--no-browser-fallback`, `SOCIAL_BROWSER_FALLBACK=0|1`, precedence, optional system Chrome, temporary profiles, and no login-state reuse.
- Platform reference: replace the currently inaccurate “flag loads complete DOM” claim with implemented network observation plus DOM fallback; document `BROWSER_UNAVAILABLE`.
- CHANGELOG Unreleased: record feature, explicit Douyin tests, partial-result preservation, temporary profiles, sanitized diagnostics, and no signature reproduction. Do not claim production readiness.

Use these exact examples:

```bash
python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --limit 30
python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --limit 30 --no-browser-fallback
SOCIAL_BROWSER_FALLBACK=0 python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --limit 30
```

- [ ] **Step 3: Run GREEN and commit**

Run: `python3 -m pytest tests/test_douyin.py -v`

Expected: all tests, including docs assertions, pass.

```bash
git add README.md USAGE.md ROADMAP.md CHANGELOG.md skill/references/platform-douyin.md tests/test_douyin.py
git commit -m "docs: describe experimental Douyin fallback"
```

---

### Task 7: Full Regression and Two-Account Live Acceptance

**Files:**
- Create: `docs/observations/douyin-browser-fallback-acceptance.md`
- Conditionally modify after two PASS verdicts: `README.md`, `ROADMAP.md`, `CHANGELOG.md`
- Do not commit: `workspace/douyin-acceptance-*`

**Interfaces:** Produces the evidence-based maturity decision.

- [ ] **Step 1: Run the full offline suite**

Run: `python3 -m pytest -q`

Expected: all tests pass. Fix regressions before live access.

- [ ] **Step 2: Verify a system browser is discoverable**

```bash
python3 -c 'import sys; sys.path.insert(0,"skill/scripts"); from collectors.browser_backend import find_browser; p=find_browser(); assert p, "BROWSER_UNAVAILABLE"; print(p)'
```

Expected: an absolute browser executable path. Never pass a user profile.

- [ ] **Step 3: Run the institution account end to end**

```bash
python3 skill/scripts/collect.py "https://www.douyin.com/user/MS4wLjABAAAAfBrtKO3L5CW-kdNFdvJRe1hLXSEziX84aElIaBBRJpu2utwVrr777u8ctiEyU4F7" --limit 30 --out workspace/douyin-acceptance-government
python3 skill/scripts/normalize.py --input workspace/douyin-acceptance-government
python3 skill/scripts/analyze.py --input workspace/douyin-acceptance-government --platform douyin --requested-limit 30
python3 skill/scripts/render_report.py --input workspace/douyin-acceptance-government
```

Expected when unobstructed: 30 posts or the explicit public maximum, plus CSV/JSON/Markdown/HTML. If a platform restriction appears, record it and do not bypass it.

- [ ] **Step 4: Run the personal creator end to end**

Use the public “大漠叔叔” profile:

```bash
python3 skill/scripts/collect.py "https://www.douyin.com/user/MS4wLjABAAAA7BDbZk0LjnEMcDDsLag5mDrMc157hD3x0SMhH1HaCM8" --limit 30 --out workspace/douyin-acceptance-creator
python3 skill/scripts/normalize.py --input workspace/douyin-acceptance-creator
python3 skill/scripts/analyze.py --input workspace/douyin-acceptance-creator --platform douyin --requested-limit 30
python3 skill/scripts/render_report.py --input workspace/douyin-acceptance-creator
```

Apply the same pass/stop rules as Step 3.

- [ ] **Step 5: Verify artifacts and sensitive-data absence**

For each workspace, assert these files exist: `source/profile.json`, `source/posts.jsonl`, `normalized-posts.csv`, `account-analysis-report.md`, `dashboard.html`, and `analysis.json`.

Search generated text and fail if it contains `Cookie:`, `sessionid=`, `passport_csrf_token`, or `X-Bogus=`.

- [ ] **Step 6: Manually check 10 non-pinned posts per account**

Compare publicly visible `post_url`, title/text, published time when visible, likes, comments, favorites, shares, and pinned status. Count only publicly displayed fields. Passing accuracy is at least 95%; unknown fields must be null.

Create the acceptance document with date/timezone, OS/browser version, exact URLs, requested/collected counts, task status, stop reason, network/DOM source, field coverage, checked/correct counts, accuracy, artifact result, sensitive-data result, and verdict `PASS`, `PARTIAL-BLOCKED-BY-PLATFORM`, or `FAIL`. Do not paste raw responses or signed URLs.

- [ ] **Step 7: Apply the maturity gate**

Only if both verdicts are `PASS`, change README to `🟢 P0（已完成两账号验收）`, add the acceptance date to Roadmap, and summarize evidence in CHANGELOG. Otherwise keep yellow experimental status and record the exact blocker without weakening criteria.

- [ ] **Step 8: Final verification and commit**

Run:

```bash
python3 -m pytest -q
git diff --check
```

Expected: all tests pass and no whitespace errors.

```bash
git add docs/observations/douyin-browser-fallback-acceptance.md README.md ROADMAP.md CHANGELOG.md
git commit -m "test: validate Douyin fallback on public accounts"
```

Do not add raw workspace directories.

---

## Plan Self-Review Results

- **Spec coverage:** Tasks 1–5 cover CDP events, network/DOM collection, partial results, CLI policy, errors, cleanup, and zero runtime dependencies. Task 6 covers truthful docs. Task 7 covers regression, two account types, 30-post targets, 95% accuracy, artifacts, privacy, and maturity gates.
- **Placeholder scan:** No deferred implementation markers remain. `<sec_uid>` is only documented URL syntax; live steps use exact public URLs.
- **Type consistency:** `DouyinBrowserResult.aweme_items/source/restriction/diagnostics`, `DouyinError.partial_posts/diagnostic_code`, and `collect_account_page` are consistent across tasks.
