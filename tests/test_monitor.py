import dataclasses
import json
import logging
from collections import deque
from unittest.mock import MagicMock, patch

import pytest
import requests

from alert import CooldownTimer, PatientLocationStateMachine, SlidingWindowCounter
from config import AppConfig, DatasetConfig
from models import (
    Alert,
    AlertType,
    AssessmentResult,
    Confidence,
    PatientLocation,
)
from security import CallState


class _ProviderFake:
    def __init__(self, results):
        self._results = deque(results)
        self.calls = []

    def assess(self, frame: bytes, prompt: str) -> AssessmentResult:
        self.calls.append((frame, prompt))
        return self._results.popleft()


class _AlertChannelFake:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.alerts.append(alert)


def _app_config(sample_config: AppConfig, tmp_path) -> AppConfig:
    base_dir = tmp_path / "dataset"
    dataset = DatasetConfig(
        base_dir=str(base_dir),
        images_dir=str(base_dir / "images"),
        log_file=str(base_dir / "log.jsonl"),
        checkin_log_file=str(base_dir / "checkins.jsonl"),
    )
    return dataclasses.replace(sample_config, dataset=dataset)


def _state(config):
    return dict(
        window_counter=SlidingWindowCounter(config.alerts.window_size),
        medium_cooldown=CooldownTimer(config.alerts.cooldown_minutes * 60),
        low_cooldown=CooldownTimer(config.alerts.low_confidence_cooldown_minutes * 60),
        location_state=PatientLocationStateMachine(
            out_of_bed_frames_to_silence=config.alerts.out_of_bed_frames_to_silence,
            in_bed_frames_to_resume=config.alerts.in_bed_frames_to_resume,
        ),
    )


def _assessment(
    *,
    safe: bool,
    confidence: Confidence,
    reason: str,
    patient_location: PatientLocation,
) -> AssessmentResult:
    return AssessmentResult(
        safe=safe,
        confidence=confidence,
        reason=reason,
        patient_location=patient_location,
    )


def test_fetch_snapshot_uses_configured_snapshot_url(sample_config):
    from monitor import fetch_snapshot

    class _Response:
        content = b"jpeg-bytes"

        def raise_for_status(self) -> None:
            return None

    calls = {}

    def fake_get(url, *, timeout):
        calls["url"] = url
        calls["timeout"] = timeout
        return _Response()

    original_get = requests.get
    requests.get = fake_get
    try:
        result = fetch_snapshot(sample_config)
    finally:
        requests.get = original_get

    assert result == b"jpeg-bytes"
    assert calls["url"] == sample_config.stream.snapshot_url
    assert calls["timeout"] == (
        sample_config.api.timeout_connect_seconds,
        sample_config.api.timeout_read_seconds,
    )


def test_run_cycle_safe_cycle_writes_dataset_and_sends_no_alert(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=True,
                confidence=Confidence.HIGH,
                reason="Patient resting in bed.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)

    run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _config: fixture_frame_bytes,
        **state,
    )

    assert channel.alerts == []
    payload = json.loads((tmp_path / "dataset" / "log.jsonl").read_text(encoding="utf-8"))
    assert payload["alert_fired"] is False
    assert payload["provider"] == config.api.provider
    assert payload["model"] == config.api.model
    assert payload["prompt_version"] == config.monitor.prompt_version


def test_run_cycle_high_unsafe_sends_immediate_alert_and_writes_dataset(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=False,
                confidence=Confidence.HIGH,
                reason="Patient appears stuck against the rail.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)

    run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _config: fixture_frame_bytes,
        **state,
    )

    assert len(channel.alerts) == 1
    assert channel.alerts[0].alert_type == AlertType.UNSAFE_HIGH
    assert channel.alerts[0].message == "Patient appears stuck against the rail."

    payload = json.loads((tmp_path / "dataset" / "log.jsonl").read_text(encoding="utf-8"))
    assert payload["alert_fired"] is True


def test_run_cycle_suppresses_alert_send_when_call_active(
    sample_config, tmp_path, fixture_frame_bytes, caplog
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=False,
                confidence=Confidence.HIGH,
                reason="Patient appears stuck against the rail.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)
    call_state = CallState(auto_expire_seconds=60)
    call_state.start()

    with caplog.at_level(logging.INFO):
        run_cycle(
            config,
            provider,
            channel,
            fetch_frame=lambda _config: fixture_frame_bytes,
            call_state=call_state,
            **state,
        )

    assert channel.alerts == []
    assert any("alert suppressed: call active" in record.message for record in caplog.records)


def test_run_cycle_sends_alert_after_call_state_ends(sample_config, tmp_path, fixture_frame_bytes):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=False,
                confidence=Confidence.HIGH,
                reason="Patient appears stuck against the rail.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)
    call_state = CallState(auto_expire_seconds=60)
    call_state.start()
    call_state.end()

    run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _config: fixture_frame_bytes,
        call_state=call_state,
        **state,
    )

    assert len(channel.alerts) == 1
    assert channel.alerts[0].alert_type == AlertType.UNSAFE_HIGH


def test_run_cycle_medium_threshold_fires_on_second_cycle(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Patient near bed edge.",
                patient_location=PatientLocation.IN_BED,
            ),
            _assessment(
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Patient near bed edge.",
                patient_location=PatientLocation.IN_BED,
            ),
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)

    run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _config: fixture_frame_bytes,
        **state,
    )
    run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _config: fixture_frame_bytes,
        **state,
    )

    assert len(channel.alerts) == 1
    assert channel.alerts[0].alert_type == AlertType.UNSAFE_MEDIUM


def test_run_cycle_auto_silence_flushes_window_and_suppresses_medium_alert(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=True,
                confidence=Confidence.HIGH,
                reason="Bed empty.",
                patient_location=PatientLocation.OUT_OF_BED,
            ),
            _assessment(
                safe=True,
                confidence=Confidence.HIGH,
                reason="Bed empty.",
                patient_location=PatientLocation.OUT_OF_BED,
            ),
            _assessment(
                safe=True,
                confidence=Confidence.HIGH,
                reason="Bed empty.",
                patient_location=PatientLocation.OUT_OF_BED,
            ),
            _assessment(
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Patient near bed edge.",
                patient_location=PatientLocation.OUT_OF_BED,
            ),
            _assessment(
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Patient near bed edge.",
                patient_location=PatientLocation.OUT_OF_BED,
            ),
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)

    for _ in range(5):
        run_cycle(
            config,
            provider,
            channel,
            fetch_frame=lambda _config: fixture_frame_bytes,
            **state,
        )

    assert channel.alerts == []
    assert state["location_state"].auto_silenced is True


def test_run_forever_uses_config_out_of_bed_silence_thresholds(sample_config):
    """run_forever must read silence thresholds from config."""
    import monitor
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    machine_kwargs = {}
    original_machine = monitor.PatientLocationStateMachine

    def capturing_machine(**kwargs):
        machine_kwargs.update(kwargs)
        raise StopLoop()

    monitor.PatientLocationStateMachine = capturing_machine
    try:
        with pytest.raises(StopLoop):
            run_forever(sample_config, provider=object(), alert_channel=object())
    finally:
        monitor.PatientLocationStateMachine = original_machine

    assert (
        machine_kwargs["out_of_bed_frames_to_silence"]
        == sample_config.alerts.out_of_bed_frames_to_silence
    )
    assert machine_kwargs["in_bed_frames_to_resume"] == sample_config.alerts.in_bed_frames_to_resume


def test_run_forever_resets_failure_counter_after_successful_cycle(sample_config, caplog):
    """Success resets the failure counter before the next failure wave."""
    import monitor
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    threshold = sample_config.api.consecutive_failure_threshold
    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < threshold:
            raise RuntimeError("first wave, below threshold")
        if calls["n"] == threshold:
            return  # success — resets counter
        if calls["n"] < threshold * 2:
            raise RuntimeError("second wave, below threshold again")
        raise StopLoop()

    builder_channel = _AlertChannelFake()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with caplog.at_level(logging.ERROR, logger="monitor"):
            with pytest.raises(StopLoop):
                run_forever(
                    sample_config,
                    provider=object(),
                    alert_channel=object(),
                    builder_channel=builder_channel,
                )
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    # Neither wave reached threshold alone, so no builder alert should fire
    assert len(builder_channel.alerts) == 0


def test_run_forever_sends_builder_alert_when_consecutive_failure_threshold_reached(
    sample_config, caplog
):
    """A SYSTEM alert is sent to builder_channel when consecutive_failure_threshold is reached."""
    import monitor
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    threshold = sample_config.api.consecutive_failure_threshold
    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= threshold:
            raise RuntimeError("api error")
        raise StopLoop()

    builder_channel = _AlertChannelFake()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with caplog.at_level(logging.ERROR, logger="monitor"):
            with pytest.raises(StopLoop):
                run_forever(
                    sample_config,
                    provider=object(),
                    alert_channel=object(),
                    builder_channel=builder_channel,
                )
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert len(builder_channel.alerts) == 1
    assert builder_channel.alerts[0].alert_type == AlertType.SYSTEM


def test_run_forever_does_not_repeat_builder_alert_on_subsequent_failures(sample_config, caplog):
    """Builder alert fires exactly once at the threshold, not on every subsequent failure."""
    import monitor
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    threshold = sample_config.api.consecutive_failure_threshold
    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= threshold + 3:
            raise RuntimeError("api error")
        raise StopLoop()

    builder_channel = _AlertChannelFake()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with caplog.at_level(logging.ERROR, logger="monitor"):
            with pytest.raises(StopLoop):
                run_forever(
                    sample_config,
                    provider=object(),
                    alert_channel=object(),
                    builder_channel=builder_channel,
                )
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert len(builder_channel.alerts) == 1


def test_run_forever_catches_cycle_exception_and_continues(sample_config, caplog):
    from monitor import run_forever

    config = sample_config

    class StopLoop(BaseException):
        pass

    calls = {"run_cycle": 0, "sleep": []}

    def fake_run_cycle(*args, **kwargs):
        calls["run_cycle"] += 1
        if calls["run_cycle"] == 1:
            raise RuntimeError("boom")
        raise StopLoop()

    import monitor

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda seconds: calls["sleep"].append(seconds)
    try:
        with caplog.at_level(logging.ERROR, logger="monitor"):
            with pytest.raises(StopLoop):
                run_forever(config, provider=object(), alert_channel=object())
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert calls["run_cycle"] == 2
    assert calls["sleep"] == [config.monitor.interval_seconds]
    assert any("Monitoring cycle failed" in record.message for record in caplog.records)


def test_run_forever_calls_pinger_ping_after_successful_cycle(sample_config, caplog):
    """pinger.ping() is called once per successful cycle."""
    import monitor
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # success
        raise StopLoop()

    pinger = MagicMock()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with pytest.raises(StopLoop):
            run_forever(sample_config, provider=object(), alert_channel=object(), pinger=pinger)
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert pinger.ping.call_count == 1


def test_run_forever_does_not_call_pinger_after_failed_cycle(sample_config, caplog):
    """pinger.ping() is NOT called when run_cycle raises."""
    import monitor
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("cycle failed")
        raise StopLoop()

    pinger = MagicMock()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with pytest.raises(StopLoop):
            run_forever(sample_config, provider=object(), alert_channel=object(), pinger=pinger)
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert pinger.ping.call_count == 0


def test_run_forever_sends_mom_alert_after_sustained_outage(sample_config, caplog):
    """Mom channel receives exactly one alert after sustained_outage_minutes of failures."""
    import dataclasses

    import monitor
    from config import HealthchecksConfig
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    # sustained_outage_minutes=0 means any outage duration triggers escalation immediately
    config = dataclasses.replace(
        sample_config,
        healthchecks=HealthchecksConfig(sustained_outage_minutes=0),
    )

    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("sustained failure")
        raise StopLoop()

    mom_channel = _AlertChannelFake()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with pytest.raises(StopLoop):
            run_forever(
                config,
                provider=object(),
                alert_channel=object(),
                mom_channel=mom_channel,
            )
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert len(mom_channel.alerts) == 1
    assert mom_channel.alerts[0].alert_type == AlertType.SYSTEM
    assert "offline" in mom_channel.alerts[0].message.lower()


def test_run_forever_mom_alert_fires_only_once_per_outage(sample_config, caplog):
    """Mom is not spammed — alert fires exactly once even for many subsequent failures."""
    import dataclasses

    import monitor
    from config import HealthchecksConfig
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    config = dataclasses.replace(
        sample_config,
        healthchecks=HealthchecksConfig(sustained_outage_minutes=0),
    )

    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 4:
            raise RuntimeError("sustained failure")
        raise StopLoop()

    mom_channel = _AlertChannelFake()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with pytest.raises(StopLoop):
            run_forever(
                config,
                provider=object(),
                alert_channel=object(),
                mom_channel=mom_channel,
            )
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert len(mom_channel.alerts) == 1


def test_run_forever_mom_alerted_resets_after_recovery(sample_config, caplog):
    """After a successful cycle, mom_alerted resets so a future outage re-alerts."""
    import dataclasses

    import monitor
    from config import HealthchecksConfig
    from monitor import run_forever

    class StopLoop(BaseException):
        pass

    config = dataclasses.replace(
        sample_config,
        healthchecks=HealthchecksConfig(sustained_outage_minutes=0),
    )

    calls = {"n": 0}

    def fake_run_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first outage")
        if calls["n"] == 2:
            return  # recovery — resets mom_alerted
        if calls["n"] == 3:
            raise RuntimeError("second outage")
        raise StopLoop()

    mom_channel = _AlertChannelFake()

    original_run_cycle = monitor.run_cycle
    original_sleep = monitor.time.sleep
    monitor.run_cycle = fake_run_cycle
    monitor.time.sleep = lambda _: None
    try:
        with pytest.raises(StopLoop):
            run_forever(
                config,
                provider=object(),
                alert_channel=object(),
                mom_channel=mom_channel,
            )
    finally:
        monitor.run_cycle = original_run_cycle
        monitor.time.sleep = original_sleep

    assert len(mom_channel.alerts) == 2


def test_main_selects_lmstudio_provider_when_configured(tmp_path):
    """main() must instantiate LMStudioProvider when config.api.provider == 'lmstudio'."""
    import monitor
    from config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
api:
  provider: lmstudio
  model: "Qwen3 VL 235B A22B Instruct"
  lmstudio_base_url: "http://localhost:1234"
  lmstudio_model: "qwen3-vlm-7b"
monitor:
  interval_seconds: 30
  image_width: 960
  image_height: 540
  silence_duration_minutes: 30
alerts:
  pushover_api_key: "test-key-app"
  pushover_user_key: "test-key-user"
""",
        encoding="utf-8",
    )

    class StopLoop(BaseException):
        pass

    provider_types = []

    original_run_forever = monitor.run_forever
    original_load_config = monitor.load_config

    def fake_load_config(*args, **kwargs):
        return load_config(str(cfg_path))

    def fake_run_forever(config, provider, alert_channel, **kwargs):
        provider_types.append(type(provider).__name__)
        raise StopLoop()

    monitor.load_config = fake_load_config
    monitor.run_forever = fake_run_forever
    try:
        with patch("lmstudio_provider.LMStudioProvider.load_model"):
            with pytest.raises(StopLoop):
                monitor.main()
    finally:
        monitor.load_config = original_load_config
        monitor.run_forever = original_run_forever

    assert provider_types == ["LMStudioProvider"]


@pytest.mark.parametrize(
    "alert_type",
    [AlertType.UNSAFE_HIGH, AlertType.UNSAFE_MEDIUM, AlertType.SOFT_LOW_CONFIDENCE],
)
def test_build_alert_with_dashboard_url_includes_gallery_link(alert_type):
    from monitor import build_alert

    assessment = _assessment(
        safe=False,
        confidence=Confidence.HIGH,
        reason="Patient at risk.",
        patient_location=PatientLocation.IN_BED,
    )
    alert = build_alert(
        alert_type,
        assessment,
        dashboard_url="https://grandma.example.com",
        timestamp="2026-04-10T12:00:00Z",
    )
    assert alert.url == "https://grandma.example.com/gallery#2026-04-10T12:00:00Z"


@pytest.mark.parametrize(
    "alert_type",
    [AlertType.UNSAFE_HIGH, AlertType.UNSAFE_MEDIUM, AlertType.SOFT_LOW_CONFIDENCE],
)
def test_build_alert_without_dashboard_url_has_empty_url(alert_type):
    from monitor import build_alert

    assessment = _assessment(
        safe=False,
        confidence=Confidence.HIGH,
        reason="Patient at risk.",
        patient_location=PatientLocation.IN_BED,
    )
    alert = build_alert(
        alert_type,
        assessment,
        dashboard_url="",
        timestamp="2026-04-10T12:00:00Z",
    )
    assert alert.url == ""


def test_run_cycle_high_unsafe_alert_includes_gallery_url_when_dashboard_url_set(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    config = dataclasses.replace(
        config,
        web=dataclasses.replace(config.web, dashboard_url="https://grandma.example.com"),
    )
    provider = _ProviderFake(
        [
            _assessment(
                safe=False,
                confidence=Confidence.HIGH,
                reason="Patient needs help.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)

    run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _config: fixture_frame_bytes,
        **state,
    )

    assert len(channel.alerts) == 1
    alert = channel.alerts[0]
    assert alert.url.startswith("https://grandma.example.com/gallery#")
    # Timestamp portion is non-empty (ISO 8601 format)
    assert len(alert.url) > len("https://grandma.example.com/gallery#")


def test_run_cycle_returns_true_when_save_image_true(sample_config, tmp_path, fixture_frame_bytes):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=True,
                confidence=Confidence.HIGH,
                reason="Safe.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    state = _state(config)

    result = run_cycle(
        config,
        provider,
        _AlertChannelFake(),
        fetch_frame=lambda _: fixture_frame_bytes,
        save_image=True,
        **state,
    )

    assert result is True
    assert (tmp_path / "dataset" / "images").exists()


def test_run_cycle_returns_false_when_save_image_false_and_no_alert(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=True,
                confidence=Confidence.HIGH,
                reason="Safe.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    state = _state(config)

    result = run_cycle(
        config,
        provider,
        _AlertChannelFake(),
        fetch_frame=lambda _: fixture_frame_bytes,
        save_image=False,
        **state,
    )

    assert result is False
    assert not (tmp_path / "dataset" / "images").exists()


def test_run_cycle_saves_image_when_alert_fires_even_if_save_image_false(
    sample_config, tmp_path, fixture_frame_bytes
):
    from monitor import run_cycle

    config = _app_config(sample_config, tmp_path)
    provider = _ProviderFake(
        [
            _assessment(
                safe=False,
                confidence=Confidence.HIGH,
                reason="Patient at risk.",
                patient_location=PatientLocation.IN_BED,
            )
        ]
    )
    channel = _AlertChannelFake()
    state = _state(config)

    result = run_cycle(
        config,
        provider,
        channel,
        fetch_frame=lambda _: fixture_frame_bytes,
        save_image=False,
        **state,
    )

    assert result is True
    assert len(channel.alerts) == 1
    assert (tmp_path / "dataset" / "images").exists()
