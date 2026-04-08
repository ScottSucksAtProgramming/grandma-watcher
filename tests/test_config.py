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
    SensorNodeConfig,
    SensorsConfig,
    StreamConfig,
    TailscaleConfig,
    WebConfig,
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
    """AppConfig has exactly the expected required and optional fields."""
    required = {"api", "monitor", "alerts"}
    optional = {
        "healthchecks",
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
