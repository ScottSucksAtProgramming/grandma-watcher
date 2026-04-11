# Healthchecks.io Integration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two independent heartbeat channels (app-level ping from `monitor.py`, OS-level cron script) and sustained-outage escalation to Mom via Pushover.

**Design spec:** `docs/superpowers/specs/2026-04-11-healthchecks-integration-design.md`

**Tech Stack:** Python 3.11, requests, pytest, unittest.mock

---

## Chunk 1: `HealthchecksPinger` module

### Task 1: Write failing tests for `healthchecks.py`

**Files:**
- Create: `tests/test_healthchecks.py`
- Modify: none

- [ ] **Step 1: Write the failing tests**

Cover:
- `ping()` calls `requests.get` with the correct URL on success
- `ping()` swallows `requests.RequestException` and does not re-raise
- `ping()` swallows HTTP error status (e.g. 500) and does not re-raise
- `HealthchecksPinger("")` — `ping()` makes no HTTP call (no-op)
- `HealthchecksPinger("  ")` — whitespace-only URL is also a no-op

Use `unittest.mock.patch("healthchecks.requests.get")`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_healthchecks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'healthchecks'`

---

### Task 2: Implement `healthchecks.py`

**Files:**
- Create: `healthchecks.py`
- Test: `tests/test_healthchecks.py`

- [ ] **Step 1: Run the targeted test**

Run: `pytest tests/test_healthchecks.py -v`
Expected: FAIL

- [ ] **Step 2: Implement `HealthchecksPinger`**

Add:
- Module logger
- `_CONNECT_TIMEOUT = 5` and `_READ_TIMEOUT = 10` module-level constants
- `HealthchecksPinger.__init__(self, url: str)` — strip and store URL; set `self._url = url.strip()`
- `HealthchecksPinger.ping(self)` — return immediately if `self._url` is empty; otherwise `requests.get(self._url, timeout=(...))`, log DEBUG on success, log WARNING and return on any exception

- [ ] **Step 3: Run the targeted tests**

Run: `pytest tests/test_healthchecks.py -v`
Expected: PASS

- [ ] **Step 4: Run full suite to check for regressions**

Run: `pytest -q`
Expected: PASS

---

## Chunk 2: Extend `run_forever()` with pinger and escalation

### Task 3: Write failing tests for pinger integration in `run_forever`

**Files:**
- Modify: `tests/test_monitor.py`
- Modify: none (implementation comes next)

- [ ] **Step 1: Write the failing pinger tests**

Cover:
- After a successful `run_cycle`, `pinger.ping()` is called exactly once (use `MagicMock` as pinger)
- After a failed `run_cycle`, `pinger.ping()` is not called

Use the existing sentinel-exception pattern from `test_monitor_integration.py` to stop the loop after N iterations.

- [ ] **Step 2: Run the targeted tests**

Run: `pytest tests/test_monitor.py -k pinger -v`
Expected: FAIL

---

### Task 4: Wire pinger into `run_forever()`

**Files:**
- Modify: `monitor.py`
- Test: `tests/test_monitor.py`

- [ ] **Step 1: Add `pinger` and `mom_channel` parameters to `run_forever()`**

New signature (keyword-only, both default to `None`):
```python
def run_forever(
    config, provider, alert_channel,
    *, builder_channel=None, pinger=None, mom_channel=None
) -> None:
```

- [ ] **Step 2: Call `pinger.ping()` after successful cycle**

After `run_cycle()` succeeds and before `time.sleep()`:
1. Call `pinger.ping()` (guard with `if pinger is not None`)
2. Set `last_successful_ping_at = time.monotonic()`
3. Set `mom_alerted = False`

Initialise `last_successful_ping_at = time.monotonic()` before the `while True`.
Initialise `mom_alerted = False` before the `while True`.

- [ ] **Step 3: Run the pinger tests**

Run: `pytest tests/test_monitor.py -k pinger -v`
Expected: PASS

---

### Task 5: Write failing tests for Mom escalation

**Files:**
- Modify: `tests/test_monitor.py`

- [ ] **Step 1: Write the failing escalation tests**

Cover:
- After enough failed cycles to exceed `sustained_outage_minutes` (patch `time.monotonic` to return a value far enough in the future), Mom's channel receives exactly one alert with `AlertType.SYSTEM`
- Mom's alert fires only once per outage — a second failed cycle after the threshold does not send a second alert (`mom_channel.send` called exactly once)
- After a successful recovery cycle followed by another outage, Mom is alerted again (`mom_alerted` resets on success)

Use a fake `AlertChannel` that collects sent alerts. Patch `time.monotonic` to control elapsed time.

- [ ] **Step 2: Run the targeted tests**

Run: `pytest tests/test_monitor.py -k escalat -v`
Expected: FAIL

---

### Task 6: Implement Mom escalation logic

**Files:**
- Modify: `monitor.py`
- Test: `tests/test_monitor.py`

- [ ] **Step 1: Add escalation check inside the `except` block**

After logging the cycle exception:
1. Compute `outage_seconds = time.monotonic() - last_successful_ping_at`
2. If `outage_seconds >= config.healthchecks.sustained_outage_minutes * 60` and `not mom_alerted` and `mom_channel is not None`:
   - Send `Alert(alert_type=AlertType.SYSTEM, priority=AlertPriority.NORMAL, message="Monitoring system is offline — please check on grandma directly.")` to `mom_channel`
   - Set `mom_alerted = True`

- [ ] **Step 2: Run the escalation tests**

Run: `pytest tests/test_monitor.py -k escalat -v`
Expected: PASS

- [ ] **Step 3: Run the full monitor test file**

Run: `pytest tests/test_monitor.py -v`
Expected: PASS

---

### Task 7: Wire pinger and mom_channel into `main()`

**Files:**
- Modify: `monitor.py`

- [ ] **Step 1: Construct `HealthchecksPinger` in `main()`**

```python
from healthchecks import HealthchecksPinger
pinger = HealthchecksPinger(config.healthchecks.app_ping_url)
```

- [ ] **Step 2: Construct `mom_channel` in `main()`**

```python
mom_channel: AlertChannel | None = None
if config.healthchecks.mom_pushover_user_key:
    mom_channel = PushoverChannel(
        api_key=config.alerts.pushover_api_key,
        user_key=config.healthchecks.mom_pushover_user_key,
        high_priority=config.alerts.high_alert_pushover_priority,
        emergency_retry_seconds=config.alerts.pushover_emergency_retry_seconds,
        emergency_expire_seconds=config.alerts.pushover_emergency_expire_seconds,
    )
```

- [ ] **Step 3: Pass both to `run_forever()`**

```python
run_forever(config, provider, alert_channel,
            builder_channel=builder_channel,
            pinger=pinger,
            mom_channel=mom_channel)
```

- [ ] **Step 4: Run full suite**

Run: `pytest -q`
Expected: PASS

---

## Chunk 3: OS-level cron heartbeat

### Task 8: Create `setup/healthcheck_ping.sh`

**Files:**
- Create: `setup/healthcheck_ping.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -fsS --retry 3 --retry-delay 2 "${HEALTHCHECKS_SYSTEM_URL}" > /dev/null
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x setup/healthcheck_ping.sh`

- [ ] **Step 3: Verify manually (if system_ping_url is configured)**

Run: `HEALTHCHECKS_SYSTEM_URL=<your-test-url> bash setup/healthcheck_ping.sh`
Expected: exits 0, ping appears in Healthchecks.io dashboard

---

### Task 9: Add cron entry to `setup/install.sh`

**Files:**
- Modify: `setup/install.sh`

- [ ] **Step 1: Read `system_ping_url` from `config.yaml` in the install script**

Add a block to install.sh that:
1. Reads `system_ping_url` from `config.yaml` via Python one-liner:
   ```bash
   SYSTEM_PING_URL=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('healthchecks',{}).get('system_ping_url',''))")
   ```
2. If non-empty, appends the crontab entry idempotently:
   ```bash
   CRON_ENTRY="*/5 * * * * HEALTHCHECKS_SYSTEM_URL=${SYSTEM_PING_URL} $(pwd)/setup/healthcheck_ping.sh"
   ( crontab -l 2>/dev/null | grep -v "healthcheck_ping.sh"; echo "${CRON_ENTRY}" ) | crontab -
   ```
3. If empty, prints a skip notice: `echo "healthchecks.system_ping_url not set — skipping cron heartbeat"`

---

## Chunk 4: Final verification

### Task 10: Full project verification

- [ ] **Step 1: Run full test suite**

Run: `pytest -q`
Expected: all PASS

- [ ] **Step 2: Run lint**

Run: `ruff check .`
Expected: no errors

- [ ] **Step 3: Run formatter check**

Run: `black --check .`
Expected: no changes needed

- [ ] **Step 4: Update CLAUDE.md tree and todo.taskpaper**

- Add `healthchecks.py` to the Tree in `CLAUDE.md`
- Add `setup/healthcheck_ping.sh` to the Tree in `CLAUDE.md`
- Add `tests/test_healthchecks.py` to the Tree in `CLAUDE.md`
- Mark the Healthchecks.io tasks as `@done` in `todo.taskpaper`
