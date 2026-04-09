"""Tests for SlidingWindowCounter and CooldownTimer in alert.py."""

from __future__ import annotations

from collections.abc import Callable

from alert import CooldownTimer, SlidingWindowCounter
from models import AssessmentResult, Confidence, PatientLocation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unsafe(confidence: Confidence) -> AssessmentResult:
    return AssessmentResult(
        safe=False,
        confidence=confidence,
        reason="Test.",
        patient_location=PatientLocation.OUT_OF_BED,
    )


def _safe(confidence: Confidence = Confidence.MEDIUM) -> AssessmentResult:
    return AssessmentResult(
        safe=True,
        confidence=confidence,
        reason="Test.",
        patient_location=PatientLocation.IN_BED,
    )


def _make_clock(initial: float = 0.0) -> tuple[Callable[[], float], list[float]]:
    """Return (clock_fn, time_container). Advance time_container[0] to move the clock."""
    t = [initial]
    return lambda: t[0], t


# ---------------------------------------------------------------------------
# SlidingWindowCounter
# ---------------------------------------------------------------------------


def test_swc_push_safe_counts_zero():
    w = SlidingWindowCounter(5)
    w.push(_safe())
    assert w.medium_count() == 0
    assert w.low_count() == 0


def test_swc_push_safe_high_confidence_counts_zero():
    """safe=True wins over confidence=HIGH — None is appended, not Confidence.HIGH."""
    w = SlidingWindowCounter(5)
    w.push(_safe(Confidence.HIGH))
    assert w.medium_count() == 0
    assert w.low_count() == 0


def test_swc_push_medium_unsafe_increments_medium():
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.MEDIUM))
    assert w.medium_count() == 1
    assert w.low_count() == 0


def test_swc_push_low_unsafe_increments_low():
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.LOW))
    assert w.low_count() == 1
    assert w.medium_count() == 0


def test_swc_push_high_unsafe_not_counted():
    """HIGH unsafe frames age through the window but do not affect medium/low counts."""
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.HIGH))
    assert w.medium_count() == 0
    assert w.low_count() == 0


def test_swc_window_not_full():
    """Counts are correct when window has fewer entries than maxlen."""
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.MEDIUM))
    w.push(_safe())
    w.push(_unsafe(Confidence.LOW))
    assert w.medium_count() == 1
    assert w.low_count() == 1


def test_swc_window_at_capacity():
    """Counts are correct when exactly window_size frames have been pushed."""
    w = SlidingWindowCounter(5)
    for _ in range(3):
        w.push(_unsafe(Confidence.MEDIUM))
    for _ in range(2):
        w.push(_unsafe(Confidence.LOW))
    assert w.medium_count() == 3
    assert w.low_count() == 2


def test_swc_window_eviction():
    """Oldest entry drops when window_size + 1 frames are pushed."""
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.MEDIUM))  # frame 1 — will be evicted
    for _ in range(5):
        w.push(_safe())  # frames 2–6 fill the window
    # Frame 1 (MEDIUM) is now gone; only safe frames remain
    assert w.medium_count() == 0
    assert w.low_count() == 0


def test_swc_mixed_frames_known_sequence():
    """Exact counts for a fully specified sequence."""
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.MEDIUM))  # MEDIUM
    w.push(_unsafe(Confidence.LOW))  # LOW
    w.push(_safe())  # safe
    w.push(_unsafe(Confidence.MEDIUM))  # MEDIUM
    w.push(_unsafe(Confidence.HIGH))  # HIGH (not counted)
    assert w.medium_count() == 2
    assert w.low_count() == 1


def test_swc_flush_clears_window():
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.MEDIUM))
    w.push(_unsafe(Confidence.LOW))
    w.flush()
    assert w.medium_count() == 0
    assert w.low_count() == 0


def test_swc_flush_then_push_works():
    w = SlidingWindowCounter(5)
    w.push(_unsafe(Confidence.MEDIUM))
    w.flush()
    w.push(_unsafe(Confidence.LOW))
    assert w.medium_count() == 0
    assert w.low_count() == 1


def test_swc_flush_empty_window_no_error():
    """flush() on an empty window is a no-op — no exception, counts remain 0."""
    w = SlidingWindowCounter(5)
    w.flush()  # must not raise
    assert w.medium_count() == 0
    assert w.low_count() == 0


def test_swc_medium_count_ignores_low():
    w = SlidingWindowCounter(5)
    for _ in range(3):
        w.push(_unsafe(Confidence.LOW))
    assert w.medium_count() == 0


def test_swc_low_count_ignores_medium():
    w = SlidingWindowCounter(5)
    for _ in range(3):
        w.push(_unsafe(Confidence.MEDIUM))
    assert w.low_count() == 0


# ---------------------------------------------------------------------------
# CooldownTimer
# ---------------------------------------------------------------------------


def test_cd_inactive_before_start():
    clock, _ = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    assert not cd.active


def test_cd_active_after_start():
    clock, _ = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    cd.start()
    assert cd.active


def test_cd_inactive_after_expiry():
    clock, t = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    cd.start()
    t[0] = 300.0
    assert not cd.active


def test_cd_inactive_after_cancel():
    clock, _ = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    cd.start()
    cd.cancel()
    assert not cd.active


def test_cd_cancel_before_start_no_error():
    """cancel() before any start() is a no-op — must not raise."""
    clock, _ = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    cd.cancel()
    assert not cd.active


def test_cd_start_idempotent_does_not_extend():
    """Second start() while active must NOT extend the expiry."""
    clock, t = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    cd.start()
    t[0] = 100.0
    cd.start()
    t[0] = 250.0
    assert cd.active
    t[0] = 300.0
    assert not cd.active


def test_cd_start_after_expiry_restarts():
    """start() after the cooldown has expired should start a new cooldown."""
    clock, t = _make_clock()
    cd = CooldownTimer(300.0, clock=clock)
    cd.start()
    t[0] = 400.0
    assert not cd.active
    cd.start()
    assert cd.active
    t[0] = 699.0
    assert cd.active
    t[0] = 700.0
    assert not cd.active


def test_cd_zero_duration_inactive_immediately():
    """Duration of 0: active is False immediately after start (boundary)."""
    clock, _ = _make_clock(0.0)
    cd = CooldownTimer(0.0, clock=clock)
    cd.start()
    assert not cd.active
