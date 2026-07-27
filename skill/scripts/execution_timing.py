"""Small, monotonic execution-timing ledger for committed task artifacts."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone, tzinfo
from typing import Iterator


class ExecutionTimer:
    """Record wall-clock bounds and non-negative phase durations in milliseconds."""

    def __init__(self, *, wall_timezone: tzinfo = timezone.utc) -> None:
        self._wall_timezone = wall_timezone
        self._started_at = datetime.now(wall_timezone)
        self._started_ns = time.monotonic_ns()
        self._phase_durations_ns: dict[str, int] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Measure one phase; repeated uses of the same name are accumulated."""
        started_ns = time.monotonic_ns()
        try:
            yield
        finally:
            elapsed_ns = max(0, time.monotonic_ns() - started_ns)
            self._phase_durations_ns[name] = (
                self._phase_durations_ns.get(name, 0) + elapsed_ns
            )

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-safe snapshot without stopping future measurements."""
        ended_at = datetime.now(self._wall_timezone)
        duration_ns = max(0, time.monotonic_ns() - self._started_ns)
        return {
            "started_at": self._started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": duration_ns // 1_000_000,
            "phase_durations_ms": {
                name: duration_ns // 1_000_000
                for name, duration_ns in sorted(
                    self._phase_durations_ns.items()
                )
            },
        }
