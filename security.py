"""Access tracking and stream pause state for vigil security features."""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable


class AccessTracker:
    """Track first-seen IPs within a fixed detection window."""

    def __init__(
        self,
        *,
        window_seconds: float,
        whitelist: list[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._whitelist = {ip.lower() for ip in (whitelist or [])}
        self._clock = clock
        self._seen: dict[str, float] = {}

    def check_and_record(self, ip: str) -> bool:
        """Return True when this IP should trigger a notification."""
        if ip.lower() in self._whitelist:
            return False
        now = self._clock()
        key = ip.lower()
        first_seen = self._seen.get(key)
        if first_seen is not None and (now - first_seen) < self._window:
            return False
        self._seen[key] = now
        return True


class StreamPauseState:
    """Track whether the MJPEG stream is paused."""

    def __init__(
        self,
        *,
        auto_resume_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._auto_resume_seconds = auto_resume_seconds
        self._clock = clock
        self._paused_at_mono: float | None = None
        self._paused_at_utc: datetime.datetime | None = None

    @property
    def is_paused(self) -> bool:
        return self._paused_at_mono is not None

    @property
    def paused_at(self) -> datetime.datetime | None:
        return self._paused_at_utc

    def pause(self) -> bool:
        """Pause the stream. Return True only if state changed."""
        if self.is_paused:
            return False
        self._paused_at_mono = self._clock()
        self._paused_at_utc = datetime.datetime.now(datetime.UTC)
        return True

    def resume(self) -> bool:
        """Resume the stream. Return True only if state changed."""
        if not self.is_paused:
            return False
        self._paused_at_mono = None
        self._paused_at_utc = None
        return True

    def check_and_auto_resume(self) -> bool:
        """Resume automatically when the configured timeout elapses."""
        paused_at = self._paused_at_mono
        if paused_at is None:
            return False
        if (self._clock() - paused_at) < self._auto_resume_seconds:
            return False
        self._paused_at_mono = None
        self._paused_at_utc = None
        return True
