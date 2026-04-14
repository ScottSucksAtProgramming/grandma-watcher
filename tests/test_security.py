"""Tests for security.py state objects."""

import datetime
import subprocess
import threading
from pathlib import Path

import pytest

from security import AccessTracker, CallState, ChimeError, ChimePlayer, StreamPauseState


def test_new_ip_triggers_notification():
    fake_time = [100.0]
    tracker = AccessTracker(window_seconds=60, clock=lambda: fake_time[0])

    assert tracker.check_and_record("1.2.3.4") is True


def test_same_ip_within_window_does_not_trigger():
    fake_time = [100.0]
    tracker = AccessTracker(window_seconds=60, clock=lambda: fake_time[0])

    assert tracker.check_and_record("1.2.3.4") is True
    fake_time[0] = 159.0

    assert tracker.check_and_record("1.2.3.4") is False


def test_same_ip_after_window_triggers_again():
    fake_time = [100.0]
    tracker = AccessTracker(window_seconds=60, clock=lambda: fake_time[0])

    assert tracker.check_and_record("1.2.3.4") is True
    fake_time[0] = 160.0

    assert tracker.check_and_record("1.2.3.4") is True


def test_whitelisted_ip_never_triggers():
    fake_time = [100.0]
    tracker = AccessTracker(
        window_seconds=60,
        whitelist=["1.2.3.4"],
        clock=lambda: fake_time[0],
    )

    assert tracker.check_and_record("1.2.3.4") is False


def test_whitelist_is_case_insensitive():
    fake_time = [100.0]
    tracker = AccessTracker(
        window_seconds=60,
        whitelist=["ABCD::1"],
        clock=lambda: fake_time[0],
    )

    assert tracker.check_and_record("abcd::1") is False


def test_multiple_ips_tracked_independently():
    fake_time = [100.0]
    tracker = AccessTracker(window_seconds=60, clock=lambda: fake_time[0])

    assert tracker.check_and_record("1.2.3.4") is True
    fake_time[0] = 110.0
    assert tracker.check_and_record("5.6.7.8") is True
    fake_time[0] = 120.0

    assert tracker.check_and_record("1.2.3.4") is False


def test_empty_ip_string_is_tracked():
    fake_time = [100.0]
    tracker = AccessTracker(window_seconds=60, clock=lambda: fake_time[0])

    assert tracker.check_and_record("") is True
    fake_time[0] = 110.0
    assert tracker.check_and_record("") is False


def test_initially_not_paused():
    state = StreamPauseState(auto_resume_seconds=60)

    assert state.is_paused is False
    assert state.paused_at is None


def test_pause_returns_true_on_first_call():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])

    assert state.pause() is True


def test_pause_returns_false_when_already_paused():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])
    state.pause()

    assert state.pause() is False


def test_resume_returns_true_when_paused():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])
    state.pause()

    assert state.resume() is True


def test_resume_returns_false_when_not_paused():
    state = StreamPauseState(auto_resume_seconds=60)

    assert state.resume() is False


def test_paused_at_is_set_on_pause():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])

    state.pause()

    assert isinstance(state.paused_at, datetime.datetime)
    assert state.paused_at.tzinfo == datetime.UTC


def test_paused_at_is_cleared_on_resume():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])
    state.pause()

    state.resume()

    assert state.paused_at is None


def test_auto_resume_before_timeout_returns_false():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])
    state.pause()
    fake_time[0] = 159.0

    assert state.check_and_auto_resume() is False
    assert state.is_paused is True


def test_auto_resume_after_timeout_resumes_and_returns_true():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])
    state.pause()
    fake_time[0] = 160.0

    assert state.check_and_auto_resume() is True
    assert state.is_paused is False


def test_auto_resume_when_not_paused_returns_false():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])

    assert state.check_and_auto_resume() is False


def test_auto_resume_clears_paused_at():
    fake_time = [100.0]
    state = StreamPauseState(auto_resume_seconds=60, clock=lambda: fake_time[0])
    state.pause()
    fake_time[0] = 160.0

    state.check_and_auto_resume()

    assert state.paused_at is None


def test_call_state_is_inactive_before_start():
    state = CallState(auto_expire_seconds=60)

    assert state.is_active() is False


def test_call_state_is_active_after_start():
    fake_time = [100.0]
    state = CallState(auto_expire_seconds=60, clock=lambda: fake_time[0])

    state.start()

    assert state.is_active() is True


def test_call_state_is_inactive_after_end():
    fake_time = [100.0]
    state = CallState(auto_expire_seconds=60, clock=lambda: fake_time[0])
    state.start()

    state.end()

    assert state.is_active() is False


def test_call_state_auto_expires_after_timeout():
    fake_time = [100.0]
    state = CallState(auto_expire_seconds=60, clock=lambda: fake_time[0])
    state.start()
    fake_time[0] = 160.0

    assert state.is_active() is False


def test_call_state_remains_thread_safe_under_concurrent_start_end():
    fake_time = [100.0]
    state = CallState(auto_expire_seconds=60, clock=lambda: fake_time[0])
    barrier = threading.Barrier(9)
    errors: list[Exception] = []

    def worker(action: str) -> None:
        try:
            barrier.wait()
            for _ in range(200):
                if action == "start":
                    state.start()
                else:
                    state.end()
                state.is_active()
        except Exception as exc:  # pragma: no cover - failure path assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=("start",)) for _ in range(4)] + [
        threading.Thread(target=worker, args=("end",)) for _ in range(4)
    ]

    for thread in threads:
        thread.start()

    barrier.wait()

    for thread in threads:
        thread.join()

    assert errors == []
    assert isinstance(state.is_active(), bool)


def test_chime_player_raises_when_file_is_missing(tmp_path):
    missing_file = tmp_path / "missing.wav"

    with pytest.raises(ChimeError, match="missing"):
        ChimePlayer(missing_file)


def test_chime_player_calls_aplay_with_expected_args(tmp_path):
    chime_file = tmp_path / "chime.wav"
    chime_file.write_bytes(b"RIFFtest")
    calls: list[tuple[list[str], int]] = []

    def fake_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append((command, timeout))
        return subprocess.CompletedProcess(command, 0)

    player = ChimePlayer(chime_file, run_command=fake_run)

    player.play()

    assert calls == [(["aplay", str(chime_file)], 10)]


def test_chime_player_raises_when_aplay_fails(tmp_path):
    chime_file = tmp_path / "chime.wav"
    chime_file.write_bytes(b"RIFFtest")

    def fake_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1)

    player = ChimePlayer(chime_file, run_command=fake_run)

    with pytest.raises(ChimeError, match="aplay"):
        player.play()


def test_static_chime_wav_exists():
    chime_path = Path(__file__).parent.parent / "static" / "chime.wav"

    assert chime_path.exists()
