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
  config.yaml
  monitor.py
  web_server.py
  alert.py
  sensors.py
  prompt_builder.py
  dataset.py
  smoke_test.py
  go2rtc.yaml
  requirements.txt
  todo.taskpaper
  tests/
    fixtures/
    test_models.py
    test_protocols.py
  setup/
    install.sh
    tailscale_setup.sh
    cloudflare_setup.sh
    apcupsd.conf
    systemd/
      monitor.service
      web_server.service
      go2rtc.service
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
      plans/
        2026-04-08-models-protocols.md
  context/
    conventions.md
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
2026-04-08: Prep task ordering matters — pyproject.toml (pythonpath config) must exist before any test can be written, even to fail correctly.
2026-04-08: AlertType.INFO is needed alongside SYSTEM for informational Mom notifications (silence-resume) — overloading SYSTEM conflates builder and patient-state alerts.
2026-04-08: Codex workflow: design spec → Opus spec review → implementation plan → Opus plan review → Codex brief → verify output. Two Opus passes caught 6 spec issues and 1 plan issue before implementation.
