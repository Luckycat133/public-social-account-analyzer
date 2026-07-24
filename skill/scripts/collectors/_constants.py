"""采集器共享常量。

仅聚合各平台适配器共用的枚举值与时区常量，不引入业务逻辑。
所有字符串值严格对齐 skill/references/exceptions.md §9.2 枚举。
"""
from __future__ import annotations

from datetime import timezone, timedelta

# 北京时间（中国平台默认时区，见 references/data-schema.md §1）
BEIJING_TZ = timezone(timedelta(hours=8))

# --------------------------------------------------------------------------
# stop_reason 枚举（严格对齐 references/exceptions.md §9.2 / data-schema.md §9.2）
# --------------------------------------------------------------------------
STOP_UNSUPPORTED = "UNSUPPORTED_PLATFORM"
STOP_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
STOP_LOGIN = "LOGIN_REQUIRED"
STOP_VERIFICATION = "VERIFICATION_REQUIRED"
STOP_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
STOP_ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
STOP_PARSER_FAILED = "PARSER_FAILED"
STOP_NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"
STOP_INTERNAL = "INTERNAL_ERROR"

# 已知 stop_reason 集合（用于从异常消息前缀 [REASON] 兜底识别）
KNOWN_STOP_REASONS = frozenset({
    STOP_UNSUPPORTED, STOP_ADAPTER_UNAVAILABLE, STOP_LOGIN, STOP_VERIFICATION,
    STOP_ACCOUNT_UNAVAILABLE, STOP_ACCESS_RESTRICTED, STOP_PARSER_FAILED,
    STOP_NO_PUBLIC_CONTENT, STOP_INTERNAL,
})
