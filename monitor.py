"""Core monitoring loop for grandma-watcher."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import requests

from alert import (
    CooldownTimer,
    PatientLocationStateMachine,
    PushoverChannel,
    SilenceEvent,
    SlidingWindowCounter,
    decide_alert_type,
)
from config import AppConfig, load_config
from dataset import record_dataset_entry
from lmstudio_provider import LMStudioProvider
from nanogpt_provider import NanoGPTProvider
from models import (
    Alert,
    AlertPriority,
    AlertType,
    AssessmentResult,
    DatasetEntry,
    SensorSnapshot,
)
from openrouter_provider import OpenRouterProvider
from prompt_builder import build_prompt
from protocols import AlertChannel, VLMProvider

logger = logging.getLogger(__name__)


def fetch_snapshot(config: AppConfig) -> bytes:
    """Fetch one JPEG snapshot from go2rtc."""
    response = requests.get(
        config.stream.snapshot_url,
        timeout=(
            config.api.timeout_connect_seconds,
            config.api.timeout_read_seconds,
        ),
    )
    response.raise_for_status()
    return response.content


def build_sensor_snapshot(config: AppConfig) -> SensorSnapshot:
    """Build the Phase 1 sensor snapshot from config flags."""
    return SensorSnapshot(
        load_cells_enabled=config.sensors.load_cells.enabled,
        vitals_enabled=config.sensors.vitals.enabled,
    )


def build_alert(
    alert_type: AlertType,
    assessment: AssessmentResult,
    *,
    dashboard_url: str = "",
    timestamp: str = "",
) -> Alert:
    """Create an Alert payload for the given alert type."""
    url = f"{dashboard_url}/gallery#{timestamp}" if dashboard_url else ""
    if alert_type == AlertType.UNSAFE_HIGH:
        return Alert(
            alert_type=alert_type,
            priority=AlertPriority.HIGH,
            message=assessment.reason,
            url=url,
        )
    if alert_type == AlertType.UNSAFE_MEDIUM:
        return Alert(
            alert_type=alert_type,
            priority=AlertPriority.NORMAL,
            message=assessment.reason,
            url=url,
        )
    if alert_type == AlertType.SOFT_LOW_CONFIDENCE:
        return Alert(
            alert_type=alert_type,
            priority=AlertPriority.NORMAL,
            message="System uncertain — please check on grandma and label the frames.",
            url=url,
        )
    raise ValueError(f"Unsupported alert type for monitor loop: {alert_type!r}")


def run_cycle(
    config: AppConfig,
    provider: VLMProvider,
    alert_channel: AlertChannel,
    *,
    window_counter: SlidingWindowCounter,
    medium_cooldown: CooldownTimer,
    low_cooldown: CooldownTimer,
    location_state: PatientLocationStateMachine,
    fetch_frame: Callable[[AppConfig], bytes] = fetch_snapshot,
    save_image: bool = True,
) -> bool:
    """Run one monitoring cycle. Returns True if a frame image was saved."""
    timestamp = _utc_now_iso()
    frame = fetch_frame(config)
    sensor_snapshot = build_sensor_snapshot(config)
    prompt = build_prompt(sensor_snapshot)
    assessment = provider.assess(frame, prompt)

    window_counter.push(assessment)
    silence_event = location_state.push(assessment)
    if silence_event == SilenceEvent.ACTIVATE:
        window_counter.flush()
        medium_cooldown.cancel()
        low_cooldown.cancel()

    silence_active = location_state.auto_silenced
    alert_type = decide_alert_type(
        assessment,
        medium_unsafe_in_window=window_counter.medium_count(),
        low_unsafe_in_window=window_counter.low_count(),
        silence_active=silence_active,
        medium_cooldown_active=medium_cooldown.active,
        low_cooldown_active=low_cooldown.active,
        config=config.alerts,
    )

    logger.info(
        "Assessment: safe=%s confidence=%s location=%s alert=%s | %s",
        assessment.safe,
        assessment.confidence.value,
        assessment.patient_location.value,
        alert_type.value if alert_type else "none",
        assessment.reason,
    )

    alert_fired = alert_type is not None
    if alert_type is not None:
        alert_channel.send(
            build_alert(
                alert_type,
                assessment,
                dashboard_url=config.web.dashboard_url,
                timestamp=timestamp,
            )
        )
        if alert_type == AlertType.UNSAFE_MEDIUM:
            medium_cooldown.start()
        elif alert_type == AlertType.SOFT_LOW_CONFIDENCE:
            low_cooldown.start()

    entry = DatasetEntry(
        timestamp=timestamp,
        image_path="",
        provider=config.api.provider,
        model=config.api.model,
        prompt_version=config.monitor.prompt_version,
        sensor_snapshot=sensor_snapshot,
        response_raw=_assessment_to_raw(assessment),
        assessment=assessment,
        alert_fired=alert_fired,
        api_latency_ms=0.0,
        silence_active=silence_active,
    )
    actually_save = save_image or alert_fired
    record_dataset_entry(
        config=config,
        timestamp=timestamp,
        frame_bytes=frame,
        entry=entry,
        save_image=actually_save,
    )
    return actually_save


def run_forever(
    config: AppConfig,
    provider: VLMProvider,
    alert_channel: AlertChannel,
    *,
    builder_channel: AlertChannel | None = None,
) -> None:
    """Run the monitor loop indefinitely, keeping per-loop state in memory."""
    window_counter = SlidingWindowCounter(config.alerts.window_size)
    medium_cooldown = CooldownTimer(config.alerts.cooldown_minutes * 60)
    low_cooldown = CooldownTimer(config.alerts.low_confidence_cooldown_minutes * 60)
    location_state = PatientLocationStateMachine(
        out_of_bed_frames_to_silence=config.alerts.out_of_bed_frames_to_silence,
        in_bed_frames_to_resume=config.alerts.in_bed_frames_to_resume,
    )

    consecutive_failures = 0
    builder_alerted = False
    last_image_saved_at: float = 0.0  # monotonic seconds; 0 = never saved
    image_interval_seconds = config.dataset.image_interval_minutes * 60

    while True:
        try:
            now = time.monotonic()
            save_image = (now - last_image_saved_at) >= image_interval_seconds
            image_saved = run_cycle(
                config,
                provider,
                alert_channel,
                window_counter=window_counter,
                medium_cooldown=medium_cooldown,
                low_cooldown=low_cooldown,
                location_state=location_state,
                save_image=save_image,
            )
            if image_saved:
                last_image_saved_at = time.monotonic()
            consecutive_failures = 0
            builder_alerted = False
        except Exception:
            logger.exception("Monitoring cycle failed")
            consecutive_failures += 1
            if (
                consecutive_failures >= config.api.consecutive_failure_threshold
                and not builder_alerted
                and builder_channel is not None
            ):
                builder_channel.send(
                    Alert(
                        alert_type=AlertType.SYSTEM,
                        priority=AlertPriority.NORMAL,
                        message=(
                            f"Monitor has failed {consecutive_failures} consecutive cycles. "
                            "Check API connectivity and logs."
                        ),
                    )
                )
                builder_alerted = True
        time.sleep(config.monitor.interval_seconds)


def main() -> int:
    """Load config and start the monitor loop."""
    config = load_config()
    if config.api.provider == "lmstudio":
        provider: VLMProvider = LMStudioProvider(config.api)
        provider.load_model()
    elif config.api.provider == "nanogpt":
        provider = NanoGPTProvider(config.api)
    else:
        provider = OpenRouterProvider(config.api)
    alert_channel = PushoverChannel(
        api_key=config.alerts.pushover_api_key,
        user_key=config.alerts.pushover_user_key,
        high_priority=config.alerts.high_alert_pushover_priority,
        emergency_retry_seconds=config.alerts.pushover_emergency_retry_seconds,
        emergency_expire_seconds=config.alerts.pushover_emergency_expire_seconds,
    )
    builder_channel: AlertChannel | None = None
    if config.alerts.pushover_builder_user_key:
        builder_channel = PushoverChannel(
            api_key=config.alerts.pushover_api_key,
            user_key=config.alerts.pushover_builder_user_key,
            high_priority=config.alerts.high_alert_pushover_priority,
            emergency_retry_seconds=config.alerts.pushover_emergency_retry_seconds,
            emergency_expire_seconds=config.alerts.pushover_emergency_expire_seconds,
        )
    run_forever(config, provider, alert_channel, builder_channel=builder_channel)
    return 0


def _assessment_to_raw(assessment: AssessmentResult) -> str:
    """Serialize a validated assessment into canonical JSON for dataset logging."""
    payload = {
        "safe": assessment.safe,
        "confidence": assessment.confidence.value,
        "reason": assessment.reason,
        "patient_location": assessment.patient_location.value,
    }
    if assessment.sensor_notes:
        payload["sensor_notes"] = assessment.sensor_notes
    return json.dumps(payload)


def _utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601 format with trailing Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    raise SystemExit(main())
