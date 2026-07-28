"""Direct deterministic tests for the execution timing ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import execution_timing
from execution_timing import ExecutionTimer


def _monotonic_sequence(monkeypatch, *values):
    readings = iter(values)
    monkeypatch.setattr(execution_timing.time, "monotonic_ns", lambda: next(readings))


def test_snapshot_has_timezone_aware_ordered_wall_bounds(monkeypatch):
    _monotonic_sequence(monkeypatch, 0, 2_000_000)
    timer = ExecutionTimer(wall_timezone=timezone(timedelta(hours=8)))

    snapshot = timer.snapshot()
    started_at = datetime.fromisoformat(snapshot["started_at"])
    ended_at = datetime.fromisoformat(snapshot["ended_at"])

    assert started_at.utcoffset() == timedelta(hours=8)
    assert ended_at.utcoffset() == timedelta(hours=8)
    assert ended_at >= started_at
    assert snapshot["duration_ms"] == 2


def test_repeated_phase_names_accumulate(monkeypatch):
    _monotonic_sequence(
        monkeypatch,
        0,
        0, 1_000_000,
        1_000_000, 3_000_000,
        3_000_000,
    )
    timer = ExecutionTimer()

    with timer.phase("collect"):
        pass
    with timer.phase("collect"):
        pass

    assert timer.snapshot()["phase_durations_ms"] == {"collect": 3}


def test_different_phase_names_are_isolated_and_sorted(monkeypatch):
    _monotonic_sequence(
        monkeypatch,
        0,
        0, 1_000_000,
        1_000_000, 3_000_000,
        3_000_000,
    )
    timer = ExecutionTimer()

    with timer.phase("z-final"):
        pass
    with timer.phase("a-first"):
        pass

    phases = timer.snapshot()["phase_durations_ms"]
    assert phases == {"a-first": 2, "z-final": 1}
    assert list(phases) == ["a-first", "z-final"]


def test_snapshot_does_not_stop_future_measurements(monkeypatch):
    _monotonic_sequence(
        monkeypatch,
        0,
        0, 1_000_000,
        1_000_000,
        1_000_000, 3_000_000,
        3_000_000,
    )
    timer = ExecutionTimer()

    with timer.phase("collect"):
        pass
    first = timer.snapshot()
    with timer.phase("collect"):
        pass
    second = timer.snapshot()

    assert first["phase_durations_ms"] == {"collect": 1}
    assert second["phase_durations_ms"] == {"collect": 3}


def test_phase_milliseconds_sum_to_total_with_fractional_remainder(monkeypatch):
    _monotonic_sequence(
        monkeypatch,
        0,
        0, 1_500_000,
        1_500_000, 3_000_000,
        3_000_000,
    )
    timer = ExecutionTimer()

    with timer.phase("collect"):
        pass
    with timer.phase("persist"):
        pass
    snapshot = timer.snapshot()

    assert snapshot["duration_ms"] == 3
    assert snapshot["phase_durations_ms"] == {"collect": 2, "persist": 1}
    assert sum(snapshot["phase_durations_ms"].values()) == snapshot["duration_ms"]
