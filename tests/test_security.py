"""Tests for security.py state objects."""

import datetime

from security import AccessTracker, StreamPauseState


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
