# Access Notifications + Stream Kill Switch — Implementation Plan
**Date:** 2026-04-12
**Issue:** #2
**Spec ref:** PRD §19.3

## Overview

Two security features for the Vigil dashboard:

1. **Access notifications** — send a Pushover alert to the builder the first time
   a given IP hits the dashboard within a rolling detection window. Gives the
   builder early warning of unexpected access.

2. **Stream kill switch** — builder can pause the MJPEG stream via a dashboard
   button. While paused, `/stream` serves a static placeholder image instead of
   live video. The AI monitoring loop is **never** interrupted — only the
   human-viewable stream is affected. Auto-resumes after a configurable timeout
   (default 4 hours) to prevent accidental permanent pausing.

---

## Architecture Decisions

### A. New file: `security.py`
`AccessTracker` and `StreamPauseState` live in a new file `security.py`. Pure
state objects with no Flask imports, following the same pattern as
`CooldownTimer` and `SlidingWindowCounter` in `alert.py`.

### B. `SecurityConfig` as an optional `AppConfig` section
Follows the `HealthchecksConfig` pattern: frozen dataclass with sensible
defaults, optional field on `AppConfig`, key added to `_KNOWN_TOP_LEVEL_KEYS`,
and a `_build_section()` call in `load_config()`.

### C. Builder `PushoverChannel` construction inside `create_app()`
Constructed once if both `alerts.pushover_api_key` and
`alerts.pushover_builder_user_key` are non-empty strings. If either is absent,
the channel is `None` and all builder notifications are silently skipped. This
reuses the existing `PushoverChannel` class from `alert.py` and the existing
builder user key from `AlertsConfig` — no new config keys needed for Pushover
credentials.

### D. Placeholder image: `static/stream_paused.jpg`
Served via `send_from_directory` from `static/`. If the file is missing, Flask
returns a natural 404. For tests, a 1x1 black JPEG stub is sufficient.

### E. `check_and_auto_resume()` call placement
Called at the top of `stream()` **and** inside `GET /stream/status`, so the
auto-resume fires on any interaction that checks pause state, not just stream
requests.

### F. Clock injection
All new classes accept `clock: Callable[[], float] = time.monotonic`, matching
`CooldownTimer` in `alert.py`.

### G. `paused_since` representation
`StreamPauseState` stores a monotonic float internally (for duration math) and
captures a `datetime.datetime` (UTC) at pause time (for display). The status
JSON surfaces the datetime as an ISO 8601 string.

### H. Access notification fires in `index()` only
IP check happens in `index()` — not `/stream` — to avoid double-firing on
MJPEG reconnects (the `<img>` tag reconnects frequently). The PRD says "every
time a new session opens the dashboard", and `index()` is the session entry
point.

### I. IP extraction: `request.remote_addr`
In production, the app is behind Cloudflare Tunnel. `request.remote_addr` will
be the tunnel's loopback IP. This is acceptable for Phase 1 — all Cloudflare
sessions share the same IP, so the notification fires once per window. For
future refinement, check `X-Forwarded-For` or `CF-Connecting-IP`. The whitelist
config exists for when this is improved.

### J. `_build_section` handles `list[str]` correctly
`_build_section` passes through values that are not `int`/`float`, so a YAML
list maps correctly to `access_notification_ip_whitelist: list[str]`. No
special handling needed.

---

## Step-by-Step Implementation

### Step 1 — Add `SecurityConfig` dataclass to `config.py`

```python
@dataclass(frozen=True)
class SecurityConfig:
    stream_pause_auto_resume_hours: float = 4.0
    access_notification_window_minutes: int = 15
    access_notification_ip_whitelist: list[str] = field(default_factory=list)
```

Changes to existing code:

1. Add `SecurityConfig` import/class above `AppConfig`.
2. Add optional field to `AppConfig`:
   ```python
   security: SecurityConfig = field(default_factory=SecurityConfig)
   ```
3. Add `"security"` to `_KNOWN_TOP_LEVEL_KEYS`.
4. Add `_build_section(raw, "security", SecurityConfig)` call in `load_config()`:
   ```python
   security=_build_section(raw, "security", SecurityConfig),
   ```

**Note:** `_build_section` does not handle nested `list` fields via type
coercion — but it passes them through as-is, which is correct since
`yaml.safe_load` already returns a Python list for YAML sequences. The one
edge case is `list[str]` with `field(default_factory=list)` — if the YAML key
is absent, `_build_section` never sets the kwarg and the dataclass default
factory kicks in. This works correctly.

### Step 2 — Write `security.py` with `AccessTracker` and `StreamPauseState`

```python
"""Access tracking and stream pause state for vigil security features.

Pure state objects with no Flask imports. Clock-injectable for testing.
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable


class AccessTracker:
    """Tracks first-seen IPs within a rolling detection window.

    check_and_record(ip) returns True the first time a given IP is seen
    within the configured window, False otherwise. Whitelist entries
    never trigger.
    """

    def __init__(
        self,
        *,
        window_seconds: float,
        whitelist: list[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._whitelist: set[str] = {ip.lower() for ip in (whitelist or [])}
        self._clock = clock
        self._seen: dict[str, float] = {}  # ip -> first_seen_monotonic

    def check_and_record(self, ip: str) -> bool:
        """Return True if this IP should trigger a notification."""
        if ip.lower() in self._whitelist:
            return False
        now = self._clock()
        last_seen = self._seen.get(ip)
        if last_seen is not None and (now - last_seen) < self._window:
            return False
        self._seen[ip] = now
        return True


class StreamPauseState:
    """Tracks whether the MJPEG stream is paused.

    pause()/resume() return True if the state actually changed,
    False if it was already in the requested state (for conditional
    notification firing).
    """

    def __init__(
        self,
        *,
        auto_resume_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._auto_resume_seconds = auto_resume_seconds
        self._clock = clock
        self._paused_at_mono: float | None = None
        self._paused_at_utc: datetime.datetime | None = None

    @property
    def is_paused(self) -> bool:
        return self._paused_at_mono is not None

    @property
    def paused_at(self) -> datetime.datetime | None:
        """UTC datetime when the stream was paused, or None."""
        return self._paused_at_utc

    def pause(self) -> bool:
        """Pause the stream. Returns True if state changed."""
        if self.is_paused:
            return False
        self._paused_at_mono = self._clock()
        self._paused_at_utc = datetime.datetime.now(datetime.UTC)
        return True

    def resume(self) -> bool:
        """Resume the stream. Returns True if state changed."""
        if not self.is_paused:
            return False
        self._paused_at_mono = None
        self._paused_at_utc = None
        return True

    def check_and_auto_resume(self) -> bool:
        """If paused and the auto-resume timeout has elapsed, resume.

        Returns True if an auto-resume occurred.
        """
        if not self.is_paused:
            return False
        elapsed = self._clock() - self._paused_at_mono
        if elapsed >= self._auto_resume_seconds:
            self._paused_at_mono = None
            self._paused_at_utc = None
            return True
        return False
```

**Design notes:**
- `AccessTracker._seen` is a flat dict. On a Pi with at most a handful of
  unique IPs, there is no need for LRU eviction. Old entries just get
  overwritten on their next visit.
- `StreamPauseState` stores both monotonic (for duration math) and UTC datetime
  (for display). `check_and_auto_resume()` clears both fields on auto-resume.

### Step 3 — Update `web_server.py`: instantiate state objects and builder channel

Inside `create_app()`, after the existing `silence` dict:

```python
from alert import PushoverChannel
from models import Alert, AlertType, AlertPriority
from security import AccessTracker, StreamPauseState

# Builder Pushover channel (None if keys not configured)
_builder_channel: PushoverChannel | None = None
if config.alerts.pushover_api_key and config.alerts.pushover_builder_user_key:
    _builder_channel = PushoverChannel(
        api_key=config.alerts.pushover_api_key,
        user_key=config.alerts.pushover_builder_user_key,
    )

# Security state objects
access_tracker = AccessTracker(
    window_seconds=config.security.access_notification_window_minutes * 60,
    whitelist=config.security.access_notification_ip_whitelist,
)
stream_pause = StreamPauseState(
    auto_resume_seconds=config.security.stream_pause_auto_resume_hours * 3600,
)

def _notify_builder(message: str) -> None:
    """Best-effort Pushover notification to the builder. Never raises."""
    if _builder_channel is None:
        return
    try:
        _builder_channel.send(
            Alert(
                alert_type=AlertType.SYSTEM,
                priority=AlertPriority.NORMAL,
                message=message,
            )
        )
    except Exception:
        logger.warning("Failed to send builder notification", exc_info=True)
```

**Gotcha:** The imports of `PushoverChannel`, `Alert`, `AlertType`,
`AlertPriority` must be at the top of `web_server.py`, not inside
`create_app()`. The `_builder_channel`, `access_tracker`, `stream_pause`, and
`_notify_builder` are local to `create_app()` scope — they are closure
variables captured by the route functions, same as the existing `silence` dict.

### Step 4 — Update `index()` route to fire access notification

```python
@app.route("/")
def index() -> str:
    """Serve the caregiver dashboard."""
    ip = request.remote_addr or ""
    if access_tracker.check_and_record(ip):
        _notify_builder(f"Dashboard opened from {ip}")
    return render_template("dashboard.html", talk_url=config.web.talk_url)
```

**Correctness note:** `request.remote_addr` can be `None` in edge cases (e.g.,
Unix socket). We default to `""` and still track it — the whitelist can include
`""` if needed. This matches the existing `_log_checkin()` pattern on line 46.

### Step 5 — Update `stream()` route: auto-resume check and pause-mode placeholder

```python
@app.route("/stream")
def stream() -> Response:
    """Proxy the go2rtc MJPEG stream, or serve placeholder if paused."""
    _log_checkin("stream_opened", config.dataset.checkin_log_file)
    stream_pause.check_and_auto_resume()
    if stream_pause.is_paused:
        return send_from_directory(
            app.static_folder, "stream_paused.jpg",
            mimetype="image/jpeg",
        )
    # ... existing MJPEG proxy code unchanged ...
```

**Important:** `send_from_directory(app.static_folder, ...)` is used instead of
a hardcoded path, since Flask already knows where `static/` is. The
`mimetype="image/jpeg"` is explicit so the browser does not try to interpret it
as an MJPEG multipart response.

**Why not `send_file`?** `send_from_directory` uses `safe_join` internally,
which is the existing project pattern (see `/images/<filename>` route).

### Step 6 — Add `/stream/pause`, `/stream/resume`, `/stream/status` routes

```python
@app.route("/stream/pause", methods=["POST"])
def stream_pause_route() -> Response:
    """Pause the MJPEG stream."""
    changed = stream_pause.pause()
    if changed:
        _notify_builder("Stream paused via dashboard")
    return jsonify({"status": "ok", "changed": changed})


@app.route("/stream/resume", methods=["POST"])
def stream_resume_route() -> Response:
    """Resume the MJPEG stream."""
    changed = stream_pause.resume()
    if changed:
        _notify_builder("Stream resumed via dashboard")
    return jsonify({"status": "ok", "changed": changed})


@app.route("/stream/status")
def stream_status_route() -> Response:
    """Return current stream pause status."""
    stream_pause.check_and_auto_resume()
    paused_at = stream_pause.paused_at
    return jsonify({
        "paused": stream_pause.is_paused,
        "paused_since": paused_at.isoformat() if paused_at else None,
    })
```

**Route naming:** Flask function names must be unique. Use `stream_pause_route`,
`stream_resume_route`, `stream_status_route` to avoid colliding with the
`stream_pause` variable or the existing `stream()` function.

**Auto-resume notification:** `check_and_auto_resume()` is called in both
`stream()` and `stream_status_route()`. If auto-resume fires, there is no
explicit builder notification for it. This is intentional — the builder set a
4-hour timeout and expects it to expire silently. If a notification is desired
later, it can be added by checking the return value.

### Step 7 — Update `templates/dashboard.html`

Add a pause banner above the stream image and a pause button in `#controls`:

```html
<div id="stream-paused-banner" hidden>
  Stream paused
</div>

<img id="stream-img" src="/stream" alt="Live camera feed">

<section id="controls">
  <button id="silence-btn" type="button">Silence 30 min</button>
  <button id="pause-stream-btn" type="button">Pause Stream</button>
  {% if talk_url %}
    ...
  {% endif %}
</section>
```

The banner is `hidden` by default and shown/hidden by JS based on
`/stream/status` polling.

### Step 8 — Update `static/dashboard.js` with `initStreamPause()`

```javascript
// -- Stream Pause ────────────────────────────────────────────

const STREAM_PAUSE_POLL_MS = 30_000;

function updateStreamPauseUI(data) {
  const banner = document.getElementById("stream-paused-banner");
  const btn = document.getElementById("pause-stream-btn");
  const img = document.getElementById("stream-img");
  if (!banner || !btn) return;

  if (data.paused) {
    banner.removeAttribute("hidden");
    btn.textContent = "Resume Stream";
    // Point img at static placeholder to avoid MJPEG error loop.
    // The /stream route also returns the placeholder, but setting
    // img.src directly avoids the error->reconnect cycle in initStream().
    if (!img.src.includes("stream_paused.jpg")) {
      img.src = "/static/stream_paused.jpg";
    }
  } else {
    banner.setAttribute("hidden", "");
    btn.textContent = "Pause Stream";
    // Reload live stream if we were showing the placeholder
    if (img.src.includes("stream_paused.jpg")) {
      reloadStream();
    }
  }
}

function pollStreamStatus() {
  fetch("/stream/status")
    .then((r) => r.json())
    .then(updateStreamPauseUI)
    .catch(() => {});
}

function initStreamPause() {
  pollStreamStatus();
  setInterval(pollStreamStatus, STREAM_PAUSE_POLL_MS);

  const btn = document.getElementById("pause-stream-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    // Determine action from current button text
    const action = btn.textContent.includes("Pause") ? "pause" : "resume";
    fetch(`/stream/${action}`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => pollStreamStatus())
      .catch(() => {})
      .finally(() => {
        setTimeout(() => { btn.disabled = false; }, 1000);
      });
  });
}
```

Add `initStreamPause()` to the `DOMContentLoaded` handler.

**Key design choice:** When paused, `img.src` is set to
`/static/stream_paused.jpg` (the static file URL) rather than `/stream`. This
avoids the MJPEG error-retry loop in `initStream()`. When resumed, the existing
`reloadStream()` function handles reconnection.

### Step 9 — Create `static/stream_paused.jpg`

A 960x540 dark-grey JPEG with centered text "Stream Paused". This is created
manually by the builder. For tests, a minimal 1x1 black JPEG is sufficient as a
stub.

The test stub can be generated in the test fixture:

```python
# Minimal valid JPEG (1x1 pixel, black)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
    b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"
    b"\x22q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16"
    b"\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz"
    b"\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99"
    b"\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7"
    b"\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5"
    b"\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1"
    b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\xae\x8a(\x03\xff\xd9"
)
```

Alternatively, tests that need the file can simply write a few bytes to
`app.static_folder / "stream_paused.jpg"` in a fixture — the route only needs
the file to exist for `send_from_directory` to succeed.

### Step 10 — Write `tests/test_security.py`

```
AccessTracker tests:
  test_new_ip_triggers_notification
  test_same_ip_within_window_does_not_trigger
  test_same_ip_after_window_triggers_again
  test_whitelisted_ip_never_triggers
  test_whitelist_is_case_insensitive
  test_multiple_ips_tracked_independently
  test_empty_ip_string_is_tracked

StreamPauseState tests:
  test_initially_not_paused
  test_pause_returns_true_on_first_call
  test_pause_returns_false_when_already_paused
  test_resume_returns_true_when_paused
  test_resume_returns_false_when_not_paused
  test_paused_at_is_set_on_pause
  test_paused_at_is_cleared_on_resume
  test_auto_resume_before_timeout_returns_false
  test_auto_resume_after_timeout_resumes_and_returns_true
  test_auto_resume_when_not_paused_returns_false
  test_auto_resume_clears_paused_at
```

All tests inject a fake clock (a list iterator or a mutable counter) as
`clock=lambda: fake_time[0]`.

### Step 11 — Extend `tests/test_web_server.py`

#### New fixture: `security_client`

```python
@pytest.fixture
def security_client(sample_config, tmp_path):
    """Client with builder Pushover key set and static placeholder present."""
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset, checkin_log_file=str(checkin_log_file)
    )
    patched_alerts = dataclasses.replace(
        sample_config.alerts,
        pushover_builder_user_key="test-builder-key",
    )
    cfg = dataclasses.replace(
        sample_config,
        dataset=patched_dataset,
        alerts=patched_alerts,
    )
    app = create_app(cfg)
    app.config["TESTING"] = True
    # Write placeholder image so /stream returns it when paused
    import os
    placeholder = os.path.join(app.static_folder, "stream_paused.jpg")
    with open(placeholder, "wb") as f:
        f.write(b"\xff\xd8\xff\xd9")  # minimal JPEG
    with app.test_client() as c:
        yield c
    # Clean up placeholder
    if os.path.exists(placeholder):
        os.remove(placeholder)
```

**Gotcha:** The `static/` folder used by the test client is the real project
`static/` directory (Flask resolves it relative to the app module). Writing a
temporary `stream_paused.jpg` there and cleaning it up avoids test pollution.
Alternatively, the test can use `app.static_folder = str(tmp_path)` to redirect
static file serving to a temp directory, which is cleaner:

```python
app.static_folder = str(tmp_path)
(tmp_path / "stream_paused.jpg").write_bytes(b"\xff\xd8\xff\xd9")
```

This is the preferred approach — it avoids writing to the project tree during
tests.

#### New tests

```
Route tests:
  test_stream_status_returns_not_paused_initially(security_client)
  test_stream_pause_sets_paused_state(security_client)
  test_stream_resume_clears_paused_state(security_client)
  test_stream_pause_idempotent_returns_changed_false(security_client)
  test_stream_resume_idempotent_returns_changed_false(security_client)
  test_stream_status_includes_paused_since_iso(security_client)
  test_stream_serves_placeholder_when_paused(security_client)
  test_stream_proxies_mjpeg_when_not_paused(security_client)
    — reuses the existing mock pattern from test_stream_proxies_mjpeg_when_go2rtc_available

Builder notification tests (mock PushoverChannel.send):
  test_dashboard_access_fires_builder_notification(security_client)
  test_dashboard_access_same_ip_within_window_no_duplicate(security_client)
  test_pause_fires_builder_notification(security_client)
  test_resume_fires_builder_notification(security_client)
  test_no_builder_notification_when_key_absent(client)
    — uses the existing `client` fixture which has empty builder key
```

**Mocking pattern:** Patch `web_server.PushoverChannel.send` (or
`alert.PushoverChannel.send`) using `unittest.mock.patch.object`. The
`PushoverChannel` is instantiated inside `create_app()`, so to mock it, either:

1. Patch `alert.PushoverChannel` before calling `create_app()` so the
   constructor returns a mock, or
2. Patch `web_server.PushoverChannel` (if imported at module level) the same way.

Option 1 is cleanest:

```python
with patch("web_server.PushoverChannel") as MockChannel:
    mock_instance = MockChannel.return_value
    app = create_app(cfg)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.get("/")
        mock_instance.send.assert_called_once()
```

The fixture should be structured to expose the mock for assertion.

### Step 12 — Update `config.yaml`

Add a `security:` section with defaults documented:

```yaml
security:
  stream_pause_auto_resume_hours: 4.0
  access_notification_window_minutes: 15
  access_notification_ip_whitelist: []
```

### Step 13 — Update `CLAUDE.md` Tree

Add these entries:
- `security.py` (top-level, alongside `alert.py`)
- `tests/test_security.py`
- `static/stream_paused.jpg`

### Step 14 — Update `web_server.py` module docstring

Add the three new routes to the docstring at the top of the file:

```
    POST /stream/pause    Pause the MJPEG stream.
    POST /stream/resume   Resume the MJPEG stream.
    GET  /stream/status   Return current stream pause status.
```

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `request.remote_addr` is always `127.0.0.1` behind Cloudflare Tunnel | Acceptable for Phase 1 — notification fires once per window per IP, so builder gets one alert per window. Add `CF-Connecting-IP` header support later. |
| Placeholder JPEG missing in production | `send_from_directory` returns 404 naturally. The dashboard JS shows the `<img>` error state, which is already handled by `initStream()` error retry. Not a crash. |
| Stream pause state is in-memory only — lost on restart | Same pattern as silence state. Acceptable for an eldercare monitor that runs continuously. The 4-hour auto-resume is a safety net, and restart clears the pause. |
| `AccessTracker._seen` dict grows unbounded | Bounded by unique IPs seen. In practice this is 1-3 IPs (Mom's phone, builder's phone, maybe one more). Not a concern. |
| Tests writing to real `static/` directory | Use `app.static_folder = str(tmp_path)` in the fixture to redirect static serving to a temp directory. |
| `_notify_builder` called with Flask `request` context | All calls happen inside route handlers, so app context is always available. No risk. |

---

## Implementation Order Summary

1. `config.py` — SecurityConfig + AppConfig field + _KNOWN_TOP_LEVEL_KEYS
2. `security.py` — AccessTracker + StreamPauseState
3. `tests/test_security.py` — unit tests for both classes
4. `web_server.py` — imports, state objects, builder channel, route updates
5. `templates/dashboard.html` — banner + pause button
6. `static/dashboard.js` — initStreamPause()
7. `tests/test_web_server.py` — security_client fixture + route/notification tests
8. `config.yaml` — security section
9. `CLAUDE.md` — tree update
10. `static/stream_paused.jpg` — placeholder image (manual)

Steps 1-3 can be implemented and tested in isolation before touching the web
layer (steps 4-7).
