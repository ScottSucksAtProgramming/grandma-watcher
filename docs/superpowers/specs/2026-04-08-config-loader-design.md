# Config Schema and Loader Design

**Date:** 2026-04-08
**Status:** Approved
**Task:** Write full config.yaml schema with defaults and comments

---

## Overview

This spec covers the creation of `config.yaml.example` (the committed schema template), `config.py` (the typed config loader), and `tests/test_config.py` (the loader test suite). It also covers the `.gitignore` entry for the real `config.yaml` and the `setup/install.sh` copy step.

---

## Files Touched

### New files
- `config.yaml.example` — full schema from PRD §10 with inline comments; blank API keys
- `config.py` — nested frozen dataclasses + `load_config()` public function
- `tests/test_config.py` — 11 test cases for the loader
- `tests/fixtures/config_valid.yaml` — minimal valid YAML fixture with fake (non-empty) secrets
- `.gitignore` — new file; entries for `config.yaml`, `__pycache__/`, `.DS_Store`, `dataset/`

### Modified files
- `setup/install.sh` — add `cp config.yaml.example config.yaml` near top, before any step that reads config
- `CLAUDE.md` tree — add `config.py`, `tests/fixtures/`, `.gitignore`

---

## Secrets Strategy

`config.yaml.example` is committed with blank API key values. The real `config.yaml` is gitignored. On the Pi, `setup/install.sh` runs `cp config.yaml.example config.yaml` once, then the operator fills in real keys.

Rationale: keys in git history are hard to erase; the example file serves as both template and schema documentation; the copy step is a one-time action at deploy time, not ongoing friction.

---

## `config.py` — Dataclass Structure

All dataclasses use `@dataclass(frozen=True)`. Leaf nodes first, `AppConfig` last.

### Leaf dataclasses

```python
@dataclass(frozen=True)
class RetentionConfig:
    alert_frames: str = "forever"
    uncertain_frames_days: int = 30
    safe_sample_frames_days: int = 30
    safe_unsample_frames_days: int = 7

@dataclass(frozen=True)
class DatasetConfig:
    base_dir: str = "/home/pi/eldercare/dataset"
    images_dir: str = ""          # derived from base_dir in builder if empty
    log_file: str = ""            # derived from base_dir in builder if empty
    checkin_log_file: str = ""    # derived from base_dir in builder if empty
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
```

### Top-level `AppConfig`

`api`, `monitor`, and `alerts` have **no defaults** — they must be present in the YAML. All other sections have `field(default_factory=...)` so they can be omitted from a minimal config.

```python
@dataclass(frozen=True)
class AppConfig:
    # Required sections — must be present in config.yaml
    api: ApiConfig
    monitor: MonitorConfig
    alerts: AlertsConfig
    # Optional sections — sensible defaults if omitted
    healthchecks: HealthchecksConfig = field(default_factory=HealthchecksConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    web: WebConfig = field(default_factory=WebConfig)
    cloudflare: CloudflareConfig = field(default_factory=CloudflareConfig)
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
```

---

## `config.py` — Loader Design

### Public interface

```python
def load_config(path: str = "config.yaml") -> AppConfig: ...
```

Default path is `"config.yaml"` (relative to the project `WorkingDirectory`). Callers can pass an explicit path for testing or alternate deployments.

### Implementation steps

1. Open and parse the YAML file. Let `FileNotFoundError` and `yaml.YAMLError` propagate — callers get clear errors.
2. Warn (don't error) on unrecognized top-level keys: `logger.warning("Unknown config key: %s", key)`. Forward compatibility — new fields in future config versions don't break old deployments.
3. Assert required sections exist (`api`, `monitor`, `alerts`). Raise `ValueError("Missing required config section: <name>")` if absent.
4. Build each section via `_build_section(raw, key, cls)` for flat sections, and custom builders for sections with nesting (`DatasetConfig`).
5. Validate required secrets are non-empty strings; raise `ValueError("Missing required config keys: <names>")` listing all missing.
6. Return `AppConfig(...)`.

### Generic builder

```python
def _build_section(raw: dict, key: str, cls: type) -> object:
    """Construct a frozen dataclass from a YAML section dict.

    Introspects the dataclass fields to cast int/float values.
    Passes through str and bool fields unchanged.
    """
```

- Introspects `dataclasses.fields(cls)` for type annotations
- Casts numeric fields with `int()` / `float()` — guards against quoted YAML values like `"30"`
- Raises `ValueError("Config key <section>.<field> must be <type>, got: <value>")` on bad casts
- Unrecognized keys within a section are silently ignored (forward compat)

### DatasetConfig builder

Custom builder derives `images_dir`, `log_file`, and `checkin_log_file` from `base_dir` if those fields are empty in the YAML. This prevents three paths from drifting independently.

### Validation

Required secrets — exactly these three, validated after construction:
- `api.openrouter_api_key` — OpenRouter API access; system cannot assess frames without it
- `alerts.pushover_api_key` — Pushover application key; system cannot send alerts without it
- `alerts.pushover_user_key` — Mom's Pushover user key; system cannot reach Mom without it

`alerts.pushover_builder_user_key` and `healthchecks.mom_pushover_user_key` are NOT validated — they are optional operational fields that degrade gracefully when absent.

All missing required secrets are reported in a single `ValueError` rather than failing one-at-a-time.

---

## `tests/test_config.py` — Test Suite (11 tests)

| # | Test name | What it asserts |
|---|-----------|-----------------|
| 1 | `test_load_valid_config` | Fixture loads, returns `AppConfig`, spot-checks values |
| 2 | `test_example_file_structurally_valid` | Calls `_build_*` helpers directly on `config.yaml.example`; asserts construction succeeds (secrets validation skipped — example has blank keys by design) |
| 3 | `test_missing_required_secret_raises` | Blank `openrouter_api_key` → `ValueError` naming the key |
| 4 | `test_missing_multiple_secrets_reports_all` | All three required secrets blank → `ValueError` containing all three names |
| 5 | `test_file_not_found_raises` | Nonexistent path → `FileNotFoundError` |
| 6 | `test_invalid_yaml_raises` | Garbage content → `yaml.YAMLError` |
| 7 | `test_unknown_keys_warn` | Extra top-level key → `logging.WARNING` via `caplog` |
| 8 | `test_quoted_numeric_coercion` | `interval_seconds: "45"` (quoted) → `config.monitor.interval_seconds == 45` as `int` |
| 9 | `test_sensor_defaults` | No `sensors` section in fixture → `config.sensors.load_cells.enabled is False` |
| 10 | `test_missing_required_section_raises` | YAML with no `alerts` section → `ValueError` naming the section |
| 11 | `test_int_cast_failure_raises` | `interval_seconds: "not_a_number"` → `ValueError` with clear field name |

### Fixture design

`tests/fixtures/config_valid.yaml` contains:
- All required sections (`api`, `monitor`, `alerts`)
- Required secrets set to non-empty fake values (e.g., `"test-key-openrouter"`)
- Optional sections omitted — tests defaults via test 9

### Test variants

Use `dataclasses.replace()` for config variants in tests. Example:
```python
modified = dataclasses.replace(config.monitor, interval_seconds=60)
```

---

## `config.yaml.example` notes

- Matches PRD §10 exactly
- Every key has an inline comment explaining its purpose and valid values
- API keys are blank (`""`) with a comment indicating where to obtain the key
- Escalation section remains commented out with a note referencing the open decision in PRD §6.4
- `audio.chime_file` has a comment: `# relative to project WorkingDirectory (set in systemd service)`
- `dataset` paths document that `images_dir`, `log_file`, and `checkin_log_file` are auto-derived from `base_dir` if left blank

---

## Design decisions log

| Decision | Rationale |
|----------|-----------|
| Frozen dataclasses over pydantic | Consistent with `models.py` pattern; no new dependencies; config loads once |
| Generic `_build_section()` helper | Avoids 11 near-identical per-section builders; type casting via field introspection |
| `healthchecks` optional | Sensible zero-value defaults; system runs without it; keeps minimal config minimal |
| Derive dataset paths from `base_dir` | Prevents three paths from drifting independently in config |
| Warn (not error) on unknown keys | Forward compatibility when new fields are added |
| Don't validate URLs/paths at load time | They fail naturally at first use with better error context |
| No `validate_secrets` param on `load_config()` | Test 2 calls builders directly instead — avoids test-only parameters in prod code |
