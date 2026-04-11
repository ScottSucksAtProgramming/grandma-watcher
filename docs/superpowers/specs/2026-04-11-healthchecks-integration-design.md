# Design Spec: Healthchecks.io Integration

**Date:** 2026-04-11
**Project:** grandma-watcher
**Status:** Approved
**Scope:** Add two independent heartbeat channels — an app-level ping from `monitor.py` and an OS-level cron ping — plus sustained-outage escalation to Mom via Pushover.
**GitHub Issue:** https://github.com/ScottSucksAtProgramming/grandma-watcher/issues/1

---

## 1. Overview

grandma-watcher currently has no mechanism to detect silent failures. If `monitor.py` crashes, hangs, or loses API connectivity for an extended period, neither the builder nor Mom is notified. This feature adds two independent dead-man's-switch heartbeats using Healthchecks.io, plus internal outage tracking that escalates to Mom after 30 minutes of missed pings.

**Two failure modes, two heartbeats:**

| Heartbeat | Source | Detects |
|---|---|---|
| App-level ping | `monitor.py` after each successful cycle | App crash, hang, API failure |
| OS-level ping | cron every 5 minutes | Pi power loss, kernel panic, OS freeze |

Healthchecks.io is configured by the builder to alert them via Pushover on missed pings for either check. `monitor.py` additionally tracks outage duration internally and Pushovers Mom directly after `sustained_outage_minutes`.

**Dependency direction:** `healthchecks.py` → `requests` only. `monitor.py` → `healthchecks.py`.

---

## 2. New Module: `healthchecks.py`

### Shape

```python
class HealthchecksPinger:
    def __init__(self, url: str) -> None: ...
    def ping(self) -> None: ...
```

### Behaviour

- `__init__(url)`: stores the URL. If `url` is empty or whitespace, all subsequent `ping()` calls are silent no-ops (no HTTP call, no log message).
- `ping()`: sends a `GET` request to the stored URL with a short timeout (5s connect, 10s read). On success, logs at `DEBUG`. On any exception (`requests.RequestException`, timeout, connection error), logs a `WARNING` with the error detail and returns — never re-raises. Fire-and-forget semantics.
- No retry logic. Healthchecks.io is designed to tolerate occasional missed pings; the OS cron provides redundancy.
- Timeout constants are module-level (`_CONNECT_TIMEOUT = 5`, `_READ_TIMEOUT = 10`) for easy adjustment without touching the constructor signature.

---

## 3. Changes to `monitor.py`

### `run_forever()` signature

Add two optional parameters:

```python
def run_forever(
    config: AppConfig,
    provider: VLMProvider,
    alert_channel: AlertChannel,
    *,
    builder_channel: AlertChannel | None = None,
    pinger: HealthchecksPinger | None = None,
    mom_channel: AlertChannel | None = None,
) -> None:
```

Both are `None` by default to maintain backwards compatibility with existing tests that do not supply them.

### App-level ping

After a successful `run_cycle()` call:

1. Call `pinger.ping()` (if pinger is not `None`).
2. Record `last_successful_ping_at = time.monotonic()`.
3. Reset `mom_alerted = False` (in case of recovery after an outage).

### Sustained-outage escalation to Mom

New in-loop state variables (initialized before `while True`):

- `last_successful_ping_at: float = time.monotonic()` — initialised to now so the first failure cycle doesn't immediately start the outage clock.
- `mom_alerted: bool = False`

On each failed cycle (inside the `except` block), after logging:

1. Compute `outage_seconds = time.monotonic() - last_successful_ping_at`.
2. If `outage_seconds >= config.healthchecks.sustained_outage_minutes * 60` and `not mom_alerted` and `mom_channel is not None`:
   - Send an `Alert` to `mom_channel`:
     - `alert_type=AlertType.SYSTEM`
     - `priority=AlertPriority.NORMAL`
     - `message="Monitoring system is offline — please check on grandma directly."`
   - Set `mom_alerted = True`.

### Builder alert (existing behaviour, unchanged)

The existing `builder_channel` alert (fires after `consecutive_failure_threshold`) is unchanged. The Mom escalation is independent of the builder alert and uses a different condition (wall-clock duration vs. consecutive count).

### `main()` additions

```python
pinger = HealthchecksPinger(config.healthchecks.app_ping_url)

mom_channel: AlertChannel | None = None
if config.healthchecks.mom_pushover_user_key:
    mom_channel = PushoverChannel(
        api_key=config.alerts.pushover_api_key,
        user_key=config.healthchecks.mom_pushover_user_key,
        ...
    )

run_forever(config, provider, alert_channel,
            builder_channel=builder_channel,
            pinger=pinger,
            mom_channel=mom_channel)
```

`mom_channel` uses `config.alerts.pushover_api_key` (the same app key used for all Pushover traffic) but `config.healthchecks.mom_pushover_user_key` as the recipient.

---

## 4. New File: `setup/healthcheck_ping.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -fsS --retry 3 --retry-delay 2 "${HEALTHCHECKS_SYSTEM_URL}" > /dev/null
```

- The URL is injected via environment variable so the script is generic and can be tested manually with any URL.
- `curl -fsS`: fail silently on server errors, suppress progress meter, show errors on stderr.
- `--retry 3 --retry-delay 2`: three attempts with 2-second gaps before giving up.
- The script exits non-zero if all retries fail. Cron captures this; it does not send email by default unless MAILTO is set.
- Committed to the repo, made executable (`chmod +x`).

---

## 5. Changes to `setup/install.sh`

During install, if `healthchecks.system_ping_url` is non-empty in `config.yaml`:

1. Read the URL from `config.yaml` via Python one-liner.
2. Write a crontab entry:
   ```
   */5 * * * * HEALTHCHECKS_SYSTEM_URL=<url> /home/pi/grandma-watcher/setup/healthcheck_ping.sh
   ```
3. If the URL is empty, skip silently (no cron entry added).

Cron is added using `crontab -l | { cat; echo "<entry>"; } | crontab -` to append without overwriting existing entries. The install script is idempotent — it checks for the entry before adding.

---

## 6. Config

`HealthchecksConfig` already has all required fields in `config.py`. No schema changes.

```yaml
healthchecks:
  app_ping_url: ""        # monitor.py pings this after each successful cycle
  system_ping_url: ""     # cron script pings this every 5 min
  sustained_outage_minutes: 30
  mom_pushover_user_key: ""
```

All fields default to empty/zero — section can be omitted entirely in development without any behaviour change.

---

## 7. Testing Strategy

**What makes a good test:** Assert on externally observable side-effects (HTTP call made to URL, alert sent to channel, flag state after recovery). Do not assert on internal variable names, sleep durations, or retry counts inside `HealthchecksPinger`.

### `tests/test_healthchecks.py` (new file)

1. `ping()` with a successful HTTP response calls `requests.get` with the correct URL.
2. `ping()` with a `requests.RequestException` does not raise and returns `None`.
3. `ping()` with an HTTP error status (e.g. 500) does not raise.
4. `HealthchecksPinger("")` — `ping()` makes no HTTP call at all.
5. `HealthchecksPinger("  ")` (whitespace-only) — same no-op behaviour.

Mock HTTP using `unittest.mock.patch("healthchecks.requests.get")`.

### `tests/test_monitor.py` (extend existing)

6. After a successful `run_cycle`, `pinger.ping()` is called exactly once.
7. After a failed `run_cycle`, `pinger.ping()` is not called.
8. After enough failed cycles to exceed `sustained_outage_minutes`, Mom's channel receives exactly one alert.
9. Mom's alert fires only once per outage — a second failed cycle after threshold does not send a second alert.
10. After a successful recovery cycle, `mom_alerted` resets — a subsequent outage re-alerts Mom.

Use a `MagicMock` as the pinger (assert `pinger.ping.call_count`). Use a fake `AlertChannel` collecting sent alerts. Use `time.monotonic` patching to control elapsed time without real waits.

Prior art: `tests/test_monitor_integration.py` for `run_forever` with mocked provider and channel, including the sentinel-exception pattern to stop the loop.

---

## 8. What Not to Include

- Healthchecks.io account setup or check configuration (builder does this manually in the Healthchecks.io dashboard).
- Routing Healthchecks.io missed-ping alerts to Pushover (configured in Healthchecks.io settings, not this codebase).
- Dataset encryption or retention pruning (separate milestone tasks).
- Security hardening items (separate milestone tasks).
- Alert escalation based on Mom not responding to a safety alert (separate open question, PRD §6.4).
