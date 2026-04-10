# Design: Wire Pushover Alert URL to Dashboard Gallery

**Date:** 2026-04-10
**Status:** Approved

## Problem

When a Pushover alert fires, Mom receives a notification with no link. She has to manually open the dashboard and navigate to the gallery to see what triggered the alert. The `Alert` model already has a `url` field and `PushoverChannel.send()` already sends it — but `build_alert()` never populates it.

## Goal

Include a deep link in every alert notification that takes Mom directly to the relevant gallery entry: `{dashboard_url}/gallery#{timestamp}`.

## Non-Goals

- This does not set up the Cloudflare Tunnel (separate task).
- Alerts without a configured `dashboard_url` continue to fire normally, just without a link.

## Design

### 1. Config — `WebConfig.dashboard_url`

Add one field to `WebConfig` in `config.py`:

```python
@dataclass(frozen=True)
class WebConfig:
    port: int = 8080
    gallery_max_items: int = 50
    talk_url: str = ""
    dashboard_url: str = ""  # NEW — e.g. "https://grandma.example.com"
```

Default is `""`. When blank, the URL is omitted from the alert payload; Pushover skips the link. No required-secrets validation — blank is valid.

Add to `config.yaml` under the `web:` section:

```yaml
web:
  dashboard_url: ""  # Set to Cloudflare tunnel URL once configured, e.g. https://grandma.example.com
```

### 2. Alert Construction — `build_alert()` in `monitor.py`

Extend the signature to accept `dashboard_url: str` and `timestamp: str`:

```python
def build_alert(
    alert_type: AlertType,
    assessment: AssessmentResult,
    *,
    dashboard_url: str = "",
    timestamp: str = "",
) -> Alert:
```

URL construction: if `dashboard_url` is non-empty, set `url = f"{dashboard_url}/gallery#{timestamp}"`, else `url = ""`.

Applied to all three alert types (`UNSAFE_HIGH`, `UNSAFE_MEDIUM`, `SOFT_LOW_CONFIDENCE`).

### 3. Call Site — `run_cycle()`

`timestamp` is already computed at the top of `run_cycle()`. The call site becomes:

```python
alert_channel.send(
    build_alert(
        alert_type,
        assessment,
        dashboard_url=config.web.dashboard_url,
        timestamp=timestamp,
    )
)
```

No other changes to `run_cycle()`.

## Data Flow

```
config.yaml (web.dashboard_url)
        ↓
    AppConfig.web.dashboard_url
        ↓
    run_cycle() — timestamp already available
        ↓
    build_alert(alert_type, assessment, dashboard_url=..., timestamp=...)
        ↓
    Alert(url="{dashboard_url}/gallery#{timestamp}")
        ↓
    PushoverChannel.send() → Pushover API (url= field)
        ↓
    Mom's phone notification with deep link
```

## Error Handling

- Blank `dashboard_url` → `url=""` → Pushover omits the link. No error.
- Malformed `dashboard_url` (e.g. missing scheme) is the operator's responsibility; the system passes the value through unchanged.

## Testing

### `test_monitor.py` — `build_alert` unit tests

Two new parametrized cases:

1. `dashboard_url="https://grandma.example.com"`, `timestamp="2026-04-10T12:00:00Z"` → `alert.url == "https://grandma.example.com/gallery#2026-04-10T12:00:00Z"`
2. `dashboard_url=""`, `timestamp="2026-04-10T12:00:00Z"` → `alert.url == ""`

Applied across all three alert types.

### `test_monitor.py` — `run_cycle` integration tests

Existing `run_cycle` tests use a web config with blank `dashboard_url` — verify existing behavior unchanged.

Add one new test: web config with `dashboard_url="https://grandma.example.com"` set, assert the alert captured by the spy channel has `url="https://grandma.example.com/gallery#{timestamp}"`.

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `dashboard_url: str = ""` to `WebConfig` |
| `config.yaml` | Add `dashboard_url: ""` with comment under `web:` |
| `monitor.py` | Extend `build_alert()` signature; update call site in `run_cycle()` |
| `tests/test_monitor.py` | New unit tests for `build_alert` with/without URL; new `run_cycle` test with URL |
