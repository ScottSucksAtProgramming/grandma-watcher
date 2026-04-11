# Alert URL Wiring Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a Pushover alert deep-link URL to each alert so Mom can tap the notification and land directly on the relevant gallery entry.

**Architecture:** Add `dashboard_url` to `WebConfig`, extend `build_alert()` in `monitor.py` to accept `dashboard_url` and `timestamp` and build the gallery URL, then update the call site in `run_cycle()` to pass both values from config and the already-computed timestamp.

**Tech Stack:** Python dataclasses, pytest, existing `Alert.url` field and `PushoverChannel.send()` plumbing (already supports URL delivery — no changes needed there).

**Spec:** `docs/superpowers/specs/2026-04-10-alert-url-wiring-design.md`

---

## Chunk 1: Config field + build_alert URL + run_cycle call site

### Task 1: Write failing tests for `build_alert` URL behaviour

**Files:**
- Modify: `tests/test_monitor.py`

- [ ] **Step 1: Add parametrized tests for `build_alert` with a `dashboard_url` set**

  Append these tests to `tests/test_monitor.py`:

  ```python
  @pytest.mark.parametrize(
      "alert_type",
      [AlertType.UNSAFE_HIGH, AlertType.UNSAFE_MEDIUM, AlertType.SOFT_LOW_CONFIDENCE],
  )
  def test_build_alert_with_dashboard_url_includes_gallery_link(alert_type):
      from monitor import build_alert

      assessment = _assessment(
          safe=False,
          confidence=Confidence.HIGH,
          reason="Patient at risk.",
          patient_location=PatientLocation.IN_BED,
      )
      alert = build_alert(
          alert_type,
          assessment,
          dashboard_url="https://grandma.example.com",
          timestamp="2026-04-10T12:00:00Z",
      )
      assert alert.url == "https://grandma.example.com/gallery#2026-04-10T12:00:00Z"


  @pytest.mark.parametrize(
      "alert_type",
      [AlertType.UNSAFE_HIGH, AlertType.UNSAFE_MEDIUM, AlertType.SOFT_LOW_CONFIDENCE],
  )
  def test_build_alert_without_dashboard_url_has_empty_url(alert_type):
      from monitor import build_alert

      assessment = _assessment(
          safe=False,
          confidence=Confidence.HIGH,
          reason="Patient at risk.",
          patient_location=PatientLocation.IN_BED,
      )
      alert = build_alert(
          alert_type,
          assessment,
          dashboard_url="",
          timestamp="2026-04-10T12:00:00Z",
      )
      assert alert.url == ""
  ```

- [ ] **Step 2: Add a `run_cycle` test asserting the gallery URL is included when `dashboard_url` is configured**

  Also append to `tests/test_monitor.py`:

  ```python
  def test_run_cycle_high_unsafe_alert_includes_gallery_url_when_dashboard_url_set(
      sample_config, tmp_path, fixture_frame_bytes
  ):
      from monitor import run_cycle

      config = _app_config(sample_config, tmp_path)
      config = dataclasses.replace(
          config,
          web=dataclasses.replace(config.web, dashboard_url="https://grandma.example.com"),
      )
      provider = _ProviderFake(
          [
              _assessment(
                  safe=False,
                  confidence=Confidence.HIGH,
                  reason="Patient needs help.",
                  patient_location=PatientLocation.IN_BED,
              )
          ]
      )
      channel = _AlertChannelFake()
      state = _state(config)

      run_cycle(
          config,
          provider,
          channel,
          fetch_frame=lambda _config: fixture_frame_bytes,
          **state,
      )

      assert len(channel.alerts) == 1
      alert = channel.alerts[0]
      assert alert.url.startswith("https://grandma.example.com/gallery#")
      # Timestamp portion is non-empty (ISO 8601 format)
      assert len(alert.url) > len("https://grandma.example.com/gallery#")
  ```

- [ ] **Step 3: Run the new tests to confirm they fail**

  ```bash
  pytest tests/test_monitor.py::test_build_alert_with_dashboard_url_includes_gallery_link \
         tests/test_monitor.py::test_build_alert_without_dashboard_url_has_empty_url \
         tests/test_monitor.py::test_run_cycle_high_unsafe_alert_includes_gallery_url_when_dashboard_url_set \
         -v
  ```

  Expected: FAIL — `build_alert()` does not yet accept `dashboard_url` or `timestamp`.

---

### Task 2: Add `dashboard_url` to `WebConfig`

**Files:**
- Modify: `config.py` — `WebConfig` dataclass

- [ ] **Step 1: Add `dashboard_url` field to `WebConfig`**

  In `config.py`, change `WebConfig` from:

  ```python
  @dataclass(frozen=True)
  class WebConfig:
      port: int = 8080
      gallery_max_items: int = 50
      talk_url: str = ""
  ```

  to:

  ```python
  @dataclass(frozen=True)
  class WebConfig:
      port: int = 8080
      gallery_max_items: int = 50
      talk_url: str = ""
      dashboard_url: str = ""
  ```

  No other changes to `config.py` — `_build_section` picks up the new field automatically via `get_type_hints`.

---

### Task 3: Extend `build_alert()` and update the call site in `run_cycle()`

**Files:**
- Modify: `monitor.py` — `build_alert()` signature and body; `run_cycle()` call site

- [ ] **Step 1: Extend `build_alert()` to accept and use `dashboard_url` and `timestamp`**

  In `monitor.py`, change `build_alert()` from:

  ```python
  def build_alert(alert_type: AlertType, assessment: AssessmentResult) -> Alert:
      """Create an Alert payload for the given alert type."""
      if alert_type == AlertType.UNSAFE_HIGH:
          return Alert(
              alert_type=alert_type,
              priority=AlertPriority.HIGH,
              message=assessment.reason,
          )
      if alert_type == AlertType.UNSAFE_MEDIUM:
          return Alert(
              alert_type=alert_type,
              priority=AlertPriority.NORMAL,
              message=assessment.reason,
          )
      if alert_type == AlertType.SOFT_LOW_CONFIDENCE:
          return Alert(
              alert_type=alert_type,
              priority=AlertPriority.NORMAL,
              message="System uncertain — please check on grandma and label the frames.",
          )
      raise ValueError(f"Unsupported alert type for monitor loop: {alert_type!r}")
  ```

  to:

  ```python
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
  ```

- [ ] **Step 2: Update the call site in `run_cycle()`**

  In `monitor.py`, change the alert dispatch inside `run_cycle()` from:

  ```python
  alert_channel.send(build_alert(alert_type, assessment))
  ```

  to:

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

  The variable `timestamp` is already assigned at the top of `run_cycle()` as `timestamp = _utc_now_iso()`. No other changes needed.

- [ ] **Step 3: Run the full test suite to confirm all tests pass**

  ```bash
  pytest tests/ -v
  ```

  Expected: all tests PASS, including the three new ones.

- [ ] **Step 4: Commit**

  ```bash
  git add config.py monitor.py tests/test_monitor.py
  git commit -m "feat: include gallery deep-link URL in Pushover alert notifications"
  ```

---

### Task 4: Update `todo.taskpaper`

**Files:**
- Modify: `todo.taskpaper`

- [ ] **Step 1: Mark the task done**

  Change:

  ```
  - Wire Pushover alert URL to dashboard frame (alert notification links to /gallery#<id>) @na
  ```

  to:

  ```
  - Wire Pushover alert URL to dashboard frame (alert notification links to /gallery#<id>) @done
  ```
