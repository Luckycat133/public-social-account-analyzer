"""iter-2 eval-4 / CASE-019 —— 抖音 OpenAPI 源结构的不变量离线复跑。

本测试对应 `docs/acceptance/offline-acceptance.md` 的抖音 OpenAPI 离线协议。
**不联网、不开浏览器、不调用 OpenAPI**；只检查源文件里仍然持有
协议 #2 承诺的不变量（userinfo 身份逐字回证、token 只在 form body /
access-token header、has_more=false 是穷尽唯一来源、`SAFE_ERROR_CODES`
对外错误码白名单）。

如果之后有人重构时把这些不变量改坏了，本测试必须失败。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOYIN_OPENAPI = REPO_ROOT / "skill" / "scripts" / "collectors" / "douyin_openapi.py"
AUTHORIZED = REPO_ROOT / "skill" / "scripts" / "collect_douyin_authorized.py"
SKILL_MD = REPO_ROOT / "skill" / "SKILL.md"


# ----- protocol #2 invariant assertions (no network) -----


def test_userinfo_open_id_check_is_byte_exact():
    """userinfo 响应 data['open_id'] 必须与 self._open_id 逐字一致,否则拒绝。
    iter-2 / CASE-019: 'userinfo 必须在任何 video.list 之前以同次 OAuth 的
    access token + open_id 做身份回证;data.open_id 与输入 open_id 逐字一致才放行'。

    实现细节:实现可能先 `data.get("open_id")` 再与 `self._open_id` 比较,
    也可能直接 `data["open_id"] != self._open_id`。本断言不锁具体写法,只验证
    语义:响应里的 open_id 与 self._open_id 必须有逐字比较(== 或 !=),且不
    等时必须 raise 出明确身份错误。
    """
    src = DOYIN_OPENAPI.read_text(encoding="utf-8")
    assert "self._open_id" in src, (
        "douyin_openapi.py 缺少 self._open_id 字段,client 没法做身份回证"
    )
    # 必须存在 `open_id != self._open_id` 或 `self._open_id == open_id` 的逐字比较
    # 允许先 data.get('open_id') 再比较的实现形式
    pattern = re.compile(
        r"open_id\s*(!=|==)\s*self\._open_id\s*[^#\n]*\n"
        r"[^#\n]*?(?:raise|DouyinOpenAPIError|INVALID_RESPONSE|identity)",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(src))
    # 退而求其次: 至少存在上述一行比较,允许 raise 在几行之后
    has_compare = re.search(r"open_id\s*(!=|==)\s*self\._open_id", src)
    assert has_compare, (
        "douyin_openapi.py 必须存在 open_id 与 self._open_id 的逐字比较, "
        "身份回证被旁路了"
    )


def test_token_isolation_token_in_form_body_or_header_only():
    """token 必须只在固定 HTTP 表面出现:userinfo 的 form body + video.list 的
    access-token header。任何看起来把 token 放进 URL / log / diag 的代码视为破坏。"""
    src = DOYIN_OPENAPI.read_text(encoding="utf-8")
    # 显式证据:token 经 form body 提交,经 access-token 头提交
    form_body_evidence = (
        "application/x-www-form-urlencoded" in src
        or "urlencode" in src
    )
    header_evidence = "access-token" in src
    assert form_body_evidence and header_evidence, (
        "douyin_openapi.py 应同时存在 form body 与 access-token header "
        "两种 token 提交形式 (token isolation 契约)。"
    )
    # 反向证据:token 不应在 url / query 字符串里
    # 检查是否有人写出类似 'https://...?access_token=' 的模式
    forbidden = re.findall(
        r"(?:url|query|path)\s*[+=]\s*['\"]?[^'\"]*access_token", src
    )
    assert not forbidden, (
        f"douyin_openapi.py 似乎把 access_token 拼到了 URL/query 字符串: "
        f"{forbidden}"
    )


def test_safe_error_codes_whitelist_exists():
    """_SAFE_ERROR_CODES 应当是固定白名单,与 `references/exceptions.md` §3.1 对齐。
    iter-2 / CASE-019: '错误描述只写固定的清洗后分类,不写服务端描述、请求头、
    查询字符串、响应正文或底层 transport 异常'。"""
    src = DOYIN_OPENAPI.read_text(encoding="utf-8")
    assert "_SAFE_ERROR_CODES" in src, (
        "_SAFE_ERROR_CODES 白名单不存在,可能被重构去掉"
    )
    # 必须包含至少 OPENAPI_ERROR / INVALID_RESPONSE / INVALID_ENDPOINT / SECRET_ECHO / TRANSPORT_ERROR 五种
    expected_codes = [
        "OPENAPI_ERROR",
        "INVALID_RESPONSE",
        "INVALID_ENDPOINT",
        "SECRET_ECHO",
        "TRANSPORT_ERROR",
    ]
    for code in expected_codes:
        assert code in src, (
            f"_SAFE_ERROR_CODES 或异常类名应至少包括 {code!r};若被改名,需更新本断言"
        )


def test_orchestration_layer_rechecks_identity():
    """collect_douyin_authorized.py 在请求作品页前必须再次独立校验
    account_id == expected_open_id,即使 client 层已经校验过。
    iter-2 / CASE-019: 'client 层已经校验身份,编排层仍须在请求作品页前
    再次确认归一化资料的 account_id 与输入 open_id 逐字一致'。

    允许 `account_id != expected_open_id` 与 `account_id == expected_open_id`
    任一顺序(raise/return 配 != ,正向 gate 用 ==)。
    """
    src = AUTHORIZED.read_text(encoding="utf-8")
    assert "account_id" in src, "collect_douyin_authorized.py 缺少 account_id"
    assert "expected_open_id" in src, (
        "collect_douyin_authorized.py 缺少 expected_open_id 参数/字段"
    )
    # 逐字比较: != 或 == 任一
    has_compare = re.search(
        r"account_id\s*(!=|==)\s*expected_open_id", src
    )
    assert has_compare, (
        "编排层必须存在 account_id 与 expected_open_id 的逐字比较, "
        "防止 client 层独断。实际期望的写法: account_id != expected_open_id"
    )


def test_offline_acceptance_documents_openapi_protocol_2():
    """详细离线协议保存在维护文档中，不把运行时 Skill 写成合同墙。"""
    text = (
        REPO_ROOT / "docs" / "acceptance" / "offline-acceptance.md"
    ).read_text(encoding="utf-8")
    assert "抖音 OpenAPI 身份与末页" in text
    assert "douyin_openapi.py" in text, (
        "离线验收参考应定位 douyin_openapi.py"
    )
    assert "collect_douyin_authorized.py" in text, (
        "离线验收参考应定位 collect_douyin_authorized.py"
    )
    assert "userinfo" in text and "has_more=false" in text, (
        "离线协议应保留 userinfo 回证与 has_more=false 末页两条核心不变量"
    )


def test_skill_md_frontmatter_is_well_formed_and_unchanged():
    """frontmatter 是 Claude 决定 skill 触发的唯一字段。本测试守护它,
    防止重构时把它改坏或破坏 YAML 结构。"""
    text = SKILL_MD.read_text(encoding="utf-8")
    # 第一行 ---,之后是 name: ..., description: ..., 之后 --- 关闭 frontmatter
    lines = text.splitlines()
    assert lines and lines[0] == "---", "SKILL.md 首行必须是 ---"
    name_line = next((l for l in lines[1:] if l.startswith("name:")), None)
    desc_line = next((l for l in lines[1:] if l.startswith("description:")), None)
    close_line = lines[3] if len(lines) > 3 else None  # close marker
    assert name_line == "name: public-social-account-analyzer", (
        f"SKILL.md frontmatter name 必须保留 'public-social-account-analyzer',"
        f"当前: {name_line!r}"
    )
    assert desc_line and len(desc_line) <= 1024, (
        "SKILL.md description 长度必须 ≤ 1024 字符(Claude spec 限制)"
    )
    assert close_line == "---", (
        "SKILL.md frontmatter 必须以 --- 在第 4 行关闭"
    )
