# grandma-watcher — AI-Powered Eldercare Monitor

## Purpose

Passive, AI-powered 24/7 monitoring system for a 97-year-old bed-bound patient with Parkinson's disease. Runs on a Raspberry Pi 5 with a NoIR camera, uses OpenRouter (Qwen3-VL-32B-Instruct) to assess safety every 30 seconds, and sends Pushover alerts to the caregiver when the patient is in an unsafe position. Includes a live video stream via go2rtc, two-way audio, and a Flask dashboard accessible from any phone browser. Full architecture and phased roadmap are in `PRD.md`.

## Tree

```
grandma-watcher/
  .gitignore
  CLAUDE.md
  INDEX.md
  PRD.md
  config.py
  models.py
  protocols.py
  pyproject.toml
  Makefile
  config.yaml
  monitor.py
  web_server.py
  alert.py
  sensors.py
  prompt_builder.py
  vlm_parser.py
  openrouter_provider.py
  lmstudio_provider.py
  dataset.py
  smoke_test.py
  probe.py
  probe_prompt.md
  go2rtc.yaml
  requirements.txt
  todo.taskpaper
  tests/
    conftest.py
    fixtures/
      config_valid.yaml
      frame.jpeg
    test_dataset.py
    test_monitor.py
    test_monitor_integration.py
    test_models.py
    test_protocols.py
    test_prompt_builder.py
    test_vlm_parser.py
    test_web_server.py
    test_openrouter_provider.py
    test_lmstudio_provider.py
    test_probe.py
    test_web_server.py
  setup/
    install.sh
    tailscale_setup.sh
    cloudflare_setup.sh
    apcupsd.conf
    systemd/
      monitor.service
      web_server.service
      go2rtc.service
      cloudflared.service
  templates/
    dashboard.html
  static/
    dashboard.js
    dashboard.css
  dataset/
    images/
    log.jsonl
  docs/
    MOM_GUIDE.md
    INSTALL_GUIDE.md
    SENSOR_SETUP.md
    superpowers/
      specs/
        2026-04-08-models-protocols-design.md
        2026-04-09-dataset-logging-design.md
        2026-04-09-monitor-core-loop-design.md
        2026-04-09-monitor-integration-test-design.md
      plans/
        2026-04-08-models-protocols.md
        2026-04-09-dataset-logging.md
        2026-04-09-monitor-core-loop.md
        2026-04-09-monitor-integration-test.md
  context/
    conventions.md
    dev-environment.md
    lessons.md
```

## Rules

1. On session start within `grandma-watcher/`, read this file, then `INDEX.md`, then `PRD.md` for full architecture context. Check `todo.taskpaper` for current next actions.
2. Primary development target is Raspberry Pi 5 (ARM64, Raspberry Pi OS Lite 64-bit). Code must run headless.
3. go2rtc owns the CSI camera exclusively. `monitor.py` fetches frames via `GET http://localhost:1984/api/frame.jpeg?src=grandma`. Never import or use `picamera2` in application code.
4. Two-way audio uses WebRTC via go2rtc over Tailscale (UDP). It does NOT work through Cloudflare Tunnel (HTTP-only). Dashboard features use Cloudflare; audio uses Tailscale. Mom needs Tailscale installed for audio only.
5. All video footage stays local — never add code that uploads raw frames to any external service (dataset images go to `dataset/images/` only). Pushover notifications send links only — never embed images.
6. Alert fatigue is a critical failure mode. Be conservative when modifying alert threshold logic; see `PRD.md` §6.3 for the alert decision matrix.
7. `config.yaml` is the single source of truth for all settings, API keys, and feature flags. Do not hardcode values that belong in config.
8. Phase 2 sensor nodes (load cells, vitals) are disabled by default. All sensor code must gate on `config.sensors.*.enabled`.
9. When creating, renaming, or deleting files, update the Tree section above.
10. Follow the Note-Taking protocol: log lessons to `context/lessons.md` after completing tasks.
11. `todo.taskpaper` is the project task list. At session start, read it to understand current next actions. When a task is complete, mark it `@done`. Do not invent or work on tasks not listed there without checking with Scott first.

## Note-Taking

After completing a task, log any corrections, preferences, patterns, or discoveries.

**Protocol:**

1. Write a dated one-liner to the appropriate location:
   - General vault lessons → `context/lessons.md`
   - Topic-specific lessons → the relevant context file's Lessons Learned section
2. If 3+ related lessons accumulate in `context/lessons.md`, extract them into a new context file in `context/`, add a Lessons Learned section to that file, and update both `INDEX.md` and the Tree above.
3. Do not ask permission to log lessons. Just log them.

### Recent Lessons (last 5)

<!-- Claude maintains this as a quick-reference mirror of the most recent entries from context/lessons.md. -->
2026-04-10: CSS `#modal-close` overriding `min-height: auto` from a base button rule breaks the 48px tap target — close buttons need explicit `min-height: var(--tap-height)` even when styled differently from other buttons.
2026-04-10: `flashButton()` re-enables the button internally after the delay — a `finally` block that also re-enables is dead code (idempotent but misleading); only use `finally` for re-enable when there is no `flashButton` call in both branches.
2026-04-10: `build_alert()` keyword-only args (`*`) keep the call site readable and prevent accidental positional mismatches when adding optional plumbing like `dashboard_url` and `timestamp` — frozen dataclass fields are picked up automatically by `_build_section` when added with a default.
2026-04-10: Cloudflare Tunnel setup — store the tunnel token in EnvironmentFile=/etc/grandma-watcher/cloudflare.env (mode 600) so it stays out of the service unit (which is checked into git); systemd reads EnvironmentFile as root before dropping to the service user, so root-owned 600 works fine.
