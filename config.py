"""Typed configuration dataclasses for grandma-watcher.

Loaded once at startup by load_config() and passed as a dependency.
Never re-read mid-run, never accessed via a global.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, get_type_hints

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionConfig:
    alert_frames: str = "forever"
    uncertain_frames_days: int = 30
    safe_sample_frames_days: int = 30
    safe_unsample_frames_days: int = 7


@dataclass(frozen=True)
class DatasetConfig:
    base_dir: str = "/home/pi/eldercare/dataset"
    images_dir: str = ""  # derived from base_dir by _build_dataset if empty
    log_file: str = ""  # derived from base_dir by _build_dataset if empty
    checkin_log_file: str = ""  # derived from base_dir by _build_dataset if empty
    max_disk_gb: int = 50
    retention: RetentionConfig = field(default_factory=RetentionConfig)


@dataclass(frozen=True)
class SensorNodeConfig:
    enabled: bool = False
    node_url: str = ""
    poll_interval_seconds: int = 5


@dataclass(frozen=True)
class SensorsConfig:
    load_cells: SensorNodeConfig = field(default_factory=SensorNodeConfig)
    vitals: SensorNodeConfig = field(default_factory=SensorNodeConfig)


@dataclass(frozen=True)
class ApiConfig:
    provider: str = "openrouter"
    model: str = "qwen/qwen3-vl-32b-instruct"
    openrouter_api_key: str = ""
    hyperbolic_api_key: str = ""
    anthropic_api_key: str = ""
    timeout_connect_seconds: int = 10
    timeout_read_seconds: int = 30
    fallback_provider: str = "hyperbolic"
    fallback_model: str = "qwen/qwen2.5-vl-72b-instruct"
    consecutive_failure_threshold: int = 5


@dataclass(frozen=True)
class MonitorConfig:
    interval_seconds: int = 30
    image_width: int = 960
    image_height: int = 540
    silence_duration_minutes: int = 30
    prompt_version: str = "1.0"


@dataclass(frozen=True)
class HealthchecksConfig:
    app_ping_url: str = ""
    system_ping_url: str = ""
    sustained_outage_minutes: int = 30
    mom_pushover_user_key: str = ""


@dataclass(frozen=True)
class AlertsConfig:
    pushover_api_key: str = ""
    pushover_user_key: str = ""
    pushover_builder_user_key: str = ""
    cooldown_minutes: int = 5
    window_size: int = 5
    medium_unsafe_window_threshold: int = 2
    low_unsafe_window_threshold: int = 3
    low_confidence_cooldown_minutes: int = 60
    high_alert_pushover_priority: int = 1
    pushover_emergency_retry_seconds: int = 60
    pushover_emergency_expire_seconds: int = 3600


@dataclass(frozen=True)
class StreamConfig:
    go2rtc_api_port: int = 1984
    snapshot_url: str = "http://localhost:1984/api/frame.jpeg?src=grandma"
    stream_name: str = "grandma"


@dataclass(frozen=True)
class WebConfig:
    port: int = 8080
    gallery_max_items: int = 50


@dataclass(frozen=True)
class CloudflareConfig:
    tunnel_token: str = ""


@dataclass(frozen=True)
class TailscaleConfig:
    enabled: bool = True


@dataclass(frozen=True)
class AudioConfig:
    chime_before_talk: bool = True
    chime_file: str = "static/chime.mp3"  # relative to project WorkingDirectory


@dataclass(frozen=True)
class AppConfig:
    # Required sections - must be present in config.yaml
    api: ApiConfig
    monitor: MonitorConfig
    alerts: AlertsConfig
    # Optional sections - sensible defaults if omitted
    healthchecks: HealthchecksConfig = field(default_factory=HealthchecksConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    web: WebConfig = field(default_factory=WebConfig)
    cloudflare: CloudflareConfig = field(default_factory=CloudflareConfig)
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)


_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "api",
        "monitor",
        "alerts",
        "healthchecks",
        "dataset",
        "stream",
        "web",
        "cloudflare",
        "tailscale",
        "sensors",
        "audio",
    }
)


def _build_section(raw: dict[str, Any], section_key: str, cls: type) -> Any:
    """Construct a frozen dataclass from a YAML section dict."""
    section_raw = raw.get(section_key, {}) or {}
    hints = get_type_hints(cls)
    field_names = {f.name for f in dataclasses.fields(cls)}
    kwargs: dict[str, Any] = {}

    for key, val in section_raw.items():
        if key not in field_names:
            continue
        hint = hints.get(key)
        if hint in (int, float):
            try:
                kwargs[key] = hint(val)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Config key {section_key}.{key} must be {hint.__name__}, got: {val!r}"
                ) from exc
        else:
            kwargs[key] = val

    return cls(**kwargs)


def _build_dataset(raw: dict[str, Any]) -> DatasetConfig:
    """Build DatasetConfig, deriving sub-paths from base_dir when not specified."""
    section = raw.get("dataset", {}) or {}
    base_dir = str(section.get("base_dir") or "/home/pi/eldercare/dataset")
    images_dir = str(section.get("images_dir") or f"{base_dir}/images")
    log_file = str(section.get("log_file") or f"{base_dir}/log.jsonl")
    checkin_log_file = str(section.get("checkin_log_file") or f"{base_dir}/checkins.jsonl")
    max_disk_gb = int(section.get("max_disk_gb", 50))
    retention_raw = section.get("retention", {}) or {}
    retention = _build_section({"retention": retention_raw}, "retention", RetentionConfig)
    return DatasetConfig(
        base_dir=base_dir,
        images_dir=images_dir,
        log_file=log_file,
        checkin_log_file=checkin_log_file,
        max_disk_gb=max_disk_gb,
        retention=retention,
    )


def _build_sensors(raw: dict[str, Any]) -> SensorsConfig:
    """Build SensorsConfig with nested SensorNodeConfig instances."""
    section = raw.get("sensors", {}) or {}
    load_cells_raw = section.get("load_cells", {}) or {}
    vitals_raw = section.get("vitals", {}) or {}
    return SensorsConfig(
        load_cells=_build_section({"load_cells": load_cells_raw}, "load_cells", SensorNodeConfig),
        vitals=_build_section({"vitals": vitals_raw}, "vitals", SensorNodeConfig),
    )


_REQUIRED_SECTIONS = ("api", "monitor", "alerts")

_REQUIRED_SECRETS: list[tuple[str, Any]] = [
    ("api.openrouter_api_key", lambda c: c.api.openrouter_api_key),
    ("alerts.pushover_api_key", lambda c: c.alerts.pushover_api_key),
    ("alerts.pushover_user_key", lambda c: c.alerts.pushover_user_key),
]


def load_config(path: str = "config.yaml") -> AppConfig:
    """Load and validate configuration from a YAML file."""
    with open(path) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    for key in raw:
        if key not in _KNOWN_TOP_LEVEL_KEYS:
            logger.warning("Unknown config key: %s", key)

    for section in _REQUIRED_SECTIONS:
        if section not in raw:
            raise ValueError(f"Missing required config section: {section}")

    config = AppConfig(
        api=_build_section(raw, "api", ApiConfig),
        monitor=_build_section(raw, "monitor", MonitorConfig),
        alerts=_build_section(raw, "alerts", AlertsConfig),
        healthchecks=_build_section(raw, "healthchecks", HealthchecksConfig),
        dataset=_build_dataset(raw),
        stream=_build_section(raw, "stream", StreamConfig),
        web=_build_section(raw, "web", WebConfig),
        cloudflare=_build_section(raw, "cloudflare", CloudflareConfig),
        tailscale=_build_section(raw, "tailscale", TailscaleConfig),
        sensors=_build_sensors(raw),
        audio=_build_section(raw, "audio", AudioConfig),
    )

    missing = [name for name, getter in _REQUIRED_SECRETS if not getter(config)]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")

    return config
