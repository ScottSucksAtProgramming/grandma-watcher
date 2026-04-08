"""Typed configuration dataclasses for grandma-watcher.

Loaded once at startup by load_config() and passed as a dependency.
Never re-read mid-run, never accessed via a global.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
