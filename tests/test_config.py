"""Tests for config.py - loader and dataclasses."""

import dataclasses
import logging
from pathlib import Path

import pytest
import yaml

from config import (
    AlertsConfig,
    ApiConfig,
    AppConfig,
    AudioConfig,
    CloudflareConfig,
    DatasetConfig,
    HealthchecksConfig,
    MonitorConfig,
    RetentionConfig,
    SecurityConfig,
    SensorNodeConfig,
    SensorsConfig,
    StreamConfig,
    TailscaleConfig,
    WebConfig,
    _build_dataset,
    _build_section,
    _build_sensors,
    load_config,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
VALID_FIXTURE = FIXTURES_DIR / "config_valid.yaml"
EXAMPLE_FILE = Path(__file__).parent.parent / "config.yaml.example"

# Minimal valid config dict used as a base for edge-case tests.
# Modify specific keys in tests rather than duplicating the whole dict.
_MINIMAL_RAW: dict = {
    "api": {
        "provider": "openrouter",
        "model": "qwen/qwen3-vl-32b-instruct",
        "openrouter_api_key": "test-key-openrouter",
        "fallback_provider": "hyperbolic",
        "fallback_model": "qwen/qwen2.5-vl-72b-instruct",
        "consecutive_failure_threshold": 5,
    },
    "monitor": {"interval_seconds": 30},
    "alerts": {
        "pushover_api_key": "test-key-pushover-app",
        "pushover_user_key": "test-key-pushover-mom",
    },
}


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a dict as YAML to a temp config.yaml and return the path."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def test_appconfig_dataclass_fields():
    """AppConfig has exactly the expected fields and config types are dataclasses."""
    config_types = (
        RetentionConfig,
        DatasetConfig,
        SensorNodeConfig,
        SensorsConfig,
        ApiConfig,
        MonitorConfig,
        HealthchecksConfig,
        AlertsConfig,
        SecurityConfig,
        StreamConfig,
        WebConfig,
        CloudflareConfig,
        TailscaleConfig,
        AudioConfig,
        AppConfig,
    )
    assert all(dataclasses.is_dataclass(cls) for cls in config_types)

    required = {"api", "monitor", "alerts"}
    optional = {
        "healthchecks",
        "security",
        "dataset",
        "stream",
        "web",
        "cloudflare",
        "tailscale",
        "sensors",
        "audio",
    }
    field_names = {f.name for f in dataclasses.fields(AppConfig)}
    assert field_names == required | optional


def test_example_file_structurally_valid():
    """config.yaml.example must construct each section without raising."""
    with open(EXAMPLE_FILE) as f:
        raw = yaml.safe_load(f)
    _build_section(raw, "api", ApiConfig)
    _build_section(raw, "monitor", MonitorConfig)
    _build_section(raw, "alerts", AlertsConfig)
    _build_section(raw, "security", SecurityConfig)
    _build_dataset(raw)
    _build_sensors(raw)


def test_quoted_numeric_coercion():
    """A quoted integer in YAML (e.g. "45") is cast to int correctly."""
    raw = {"monitor": {"interval_seconds": "45"}}
    result = _build_section(raw, "monitor", MonitorConfig)
    assert result.interval_seconds == 45
    assert isinstance(result.interval_seconds, int)


def test_int_cast_failure_raises():
    """A non-numeric value for an int field raises ValueError naming the field."""
    raw = {"monitor": {"interval_seconds": "not_a_number"}}
    with pytest.raises(ValueError, match="monitor.interval_seconds"):
        _build_section(raw, "monitor", MonitorConfig)


def test_sensor_defaults_from_builder():
    """Calling _build_sensors with no sensors key produces disabled-by-default nodes."""
    result = _build_sensors({})
    assert result.load_cells.enabled is False
    assert result.vitals.enabled is False


def test_load_valid_config():
    config = load_config(str(VALID_FIXTURE))
    assert isinstance(config, AppConfig)
    assert config.api.provider == "nanogpt"
    assert config.monitor.interval_seconds == 30
    assert config.alerts.pushover_api_key == "test-key-pushover-app"


def test_alerts_config_has_high_alert_pushover_priority():
    config = load_config(str(VALID_FIXTURE))
    assert config.alerts.high_alert_pushover_priority == 1


def test_alerts_config_has_emergency_retry_and_expire():
    config = load_config(str(VALID_FIXTURE))
    assert config.alerts.pushover_emergency_retry_seconds == 60
    assert config.alerts.pushover_emergency_expire_seconds == 3600


def test_missing_required_secret_raises(tmp_path):
    data = {**_MINIMAL_RAW, "api": {**_MINIMAL_RAW["api"], "openrouter_api_key": ""}}
    p = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="api.openrouter_api_key"):
        load_config(str(p))


def test_missing_multiple_secrets_reports_all(tmp_path):
    data = {
        **_MINIMAL_RAW,
        "api": {**_MINIMAL_RAW["api"], "openrouter_api_key": ""},
        "alerts": {"pushover_api_key": "", "pushover_user_key": ""},
    }
    p = _write_config(tmp_path, data)
    with pytest.raises(ValueError) as exc_info:
        load_config(str(p))
    msg = str(exc_info.value)
    assert "api.openrouter_api_key" in msg
    assert "alerts.pushover_api_key" in msg
    assert "alerts.pushover_user_key" in msg


def test_file_not_found_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")


def test_invalid_yaml_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("key: [\nbroken yaml")
    with pytest.raises(yaml.YAMLError):
        load_config(str(p))


def test_unknown_keys_warn(tmp_path, caplog):
    data = {**_MINIMAL_RAW, "unknown_section": {"foo": "bar"}}
    p = _write_config(tmp_path, data)
    with caplog.at_level(logging.WARNING, logger="config"):
        load_config(str(p))
    assert any("unknown_section" in record.message for record in caplog.records)


def test_missing_required_section_raises(tmp_path):
    data = {k: v for k, v in _MINIMAL_RAW.items() if k != "alerts"}
    p = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="alerts"):
        load_config(str(p))


def test_load_config_accepts_lmstudio_provider_without_openrouter_key(tmp_path):
    """config.yaml with provider: lmstudio must not require openrouter_api_key."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
api:
  provider: lmstudio
  model: "qwen/qwen3-vl-32b-instruct"
  openrouter_api_key: ""
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
    config = load_config(str(cfg_path))
    assert config.api.provider == "lmstudio"
    assert config.api.lmstudio_base_url == "http://localhost:1234"
    assert config.api.lmstudio_model == "qwen3-vlm-7b"


def test_load_config_openrouter_still_requires_api_key(tmp_path):
    """config.yaml with provider: openrouter must still require openrouter_api_key."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
api:
  provider: openrouter
  model: "qwen/qwen3-vl-32b-instruct"
  openrouter_api_key: ""
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
    with pytest.raises(ValueError, match="api.openrouter_api_key"):
        load_config(str(cfg_path))


def test_security_config_archival_fields_have_correct_defaults():
    cfg = SecurityConfig()

    assert cfg.archive_after_hours == 24.0
    assert cfg.age_public_key == ""
    assert cfg.nas_sync_enabled is False
    assert cfg.nas_rsync_target == ""


def test_dataset_config_archive_dir_derived_from_base_dir(tmp_path):
    raw = {"dataset": {"base_dir": str(tmp_path / "ds")}}

    cfg = _build_dataset(raw)

    assert cfg.archive_dir == str(tmp_path / "ds" / "archive")


def test_dataset_config_archive_dir_explicit_overrides_default(tmp_path):
    raw = {"dataset": {"base_dir": str(tmp_path), "archive_dir": "/custom/archive"}}

    cfg = _build_dataset(raw)

    assert cfg.archive_dir == "/custom/archive"


def test_image_interval_minutes_yaml_override_is_respected(tmp_path):
    raw = {"dataset": {"base_dir": str(tmp_path), "image_interval_minutes": 10}}

    cfg = _build_dataset(raw)

    assert cfg.image_interval_minutes == 10


def test_load_config_rejects_nas_sync_enabled_without_target(tmp_path):
    cfg_dict = {
        "api": {"provider": "nanogpt", "nanogpt_api_key": "x"},
        "monitor": {"interval_seconds": 30},
        "alerts": {"pushover_api_key": "x", "pushover_user_key": "x"},
        "security": {"nas_sync_enabled": True, "nas_rsync_target": ""},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg_dict))

    with pytest.raises(ValueError, match="nas_rsync_target"):
        load_config(str(path))


def test_load_config_accepts_nas_sync_enabled_with_target(tmp_path):
    cfg_dict = {
        "api": {"provider": "nanogpt", "nanogpt_api_key": "x"},
        "monitor": {"interval_seconds": 30},
        "alerts": {"pushover_api_key": "x", "pushover_user_key": "x"},
        "security": {
            "nas_sync_enabled": True,
            "nas_rsync_target": "vigil-sync@100.1.2.3:/mnt/pool",
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg_dict))

    config = load_config(str(path))

    assert config.security.nas_sync_enabled is True
