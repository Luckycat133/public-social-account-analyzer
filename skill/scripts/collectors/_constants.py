"""Shared public collection stop reasons and ordered Douyin page states."""

import re

STOP_LOGIN = "LOGIN_REQUIRED"
STOP_VERIFICATION = "VERIFICATION_REQUIRED"
STOP_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
STOP_ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
STOP_PARSER_FAILED = "PARSER_FAILED"
STOP_NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"
STOP_UNSUPPORTED = "UNSUPPORTED_PLATFORM"
STOP_INTERNAL = "INTERNAL_ERROR"


# Order is the public status priority.  Parser failure is deliberately absent:
# callers run these page-state checks before deciding that a structure changed.
DOUYIN_PAGE_STATE_PATTERNS = (
    (
        re.compile(
            r"滑动验证|人机验证|安全验证|verify you are human|please verify",
            re.I,
        ),
        STOP_VERIFICATION,
    ),
    (
        re.compile(
            r"登录后查看|请先登录|登录抖音|需登录|登录后访问|扫码登录",
            re.I,
        ),
        STOP_LOGIN,
    ),
    (
        re.compile(
            r"访问过于频繁|操作过于频繁|请求频率过高|"
            r"网络异常[，, ]?请稍后|访问受限|频繁",
            re.I,
        ),
        STOP_ACCESS_RESTRICTED,
    ),
    (
        re.compile(
            r"账号不存在|用户不存在|该账号已被封禁|账号已注销|帐号不存在|"
            r"用户已注销|账号不可用",
            re.I,
        ),
        STOP_ACCOUNT_UNAVAILABLE,
    ),
    (
        re.compile(
            r"暂无公开作品|暂无作品|还没有发布(?:任何)?(?:公开)?作品|"
            r"尚未发布(?:任何)?作品|没有公开内容",
            re.I,
        ),
        STOP_NO_PUBLIC_CONTENT,
    ),
)
