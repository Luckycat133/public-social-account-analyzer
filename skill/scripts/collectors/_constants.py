"""Shared public collection stop-reason constants.

Keep the common values independent from individual platform collectors so
browser transports can report restrictions without importing a collector.
"""

STOP_LOGIN = "LOGIN_REQUIRED"
STOP_VERIFICATION = "VERIFICATION_REQUIRED"
