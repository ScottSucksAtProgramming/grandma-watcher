---
title: "grandma-watcher Lessons Learned"
summary: "Running log of corrections, preferences, and discoveries for the eldercare monitor project"
created: 2026-04-07
updated: 2026-04-07
---

# grandma-watcher Lessons Learned

<!-- Append dated one-liners below. When 3+ related lessons accumulate on a topic, extract into a dedicated context file. -->

2026-04-07: go2rtc on Pi 5 requires `rpicam-vid` (not `libcamera-vid`) with `--libav-format h264` — without this flag rpicam-vid cannot write to stdout.
2026-04-07: Together AI does not offer Qwen2.5-VL-72B on serverless endpoints; switched to OpenRouter + Qwen3-VL-32B-Instruct (~$13.50/month at 30s intervals, 960×540).
2026-04-07: WebRTC media (UDP) cannot traverse Cloudflare Tunnel (HTTP-only); two-way audio routed via Tailscale instead — Mom needs Tailscale app for audio only.
2026-04-07: Pushover does not support multi-button action callbacks — labeling moved to dashboard gallery with supplemental URL link in notification.
2026-04-07: VLMs cannot distinguish Parkinson's tremors from entrapment in a single still frame — removed that distinction from the prompt; let N-of-5 sliding window handle noise instead.
2026-04-07: patient_location sliding window should flush on silence activation — hours may pass between silence and return, stale pre-silence frames should not influence post-return alerts.
2026-04-08: Prep task ordering matters — pyproject.toml (pythonpath config) must exist before any test can be written, even to fail correctly; bootstrap it before models.py, not after.
2026-04-08: AlertType.INFO is needed alongside SYSTEM for informational Mom notifications (e.g. silence-resume) — overloading SYSTEM conflates builder system-health alerts with patient-state notifications.
2026-04-08: Codex workflow: design spec → Opus spec review → implementation plan → Opus plan review → Codex brief → verify output. Two Opus review passes caught 6 spec issues and 1 plan issue before implementation.
2026-04-08: TDD plan import sequencing — test files that import not-yet-implemented symbols must add imports incrementally per task, or the red phase fails for the wrong reason (ImportError vs missing implementation).
2026-04-09: Dev environment doc belongs in context/ before Milestone 1 — clarifies Mac/Pi split, mocking strategy, and rsync deploy before any integration tests are written.
2026-04-09: E501 in string literals (verbatim prompt constants) should be suppressed via per-file-ignores in pyproject.toml — never wrap prompt text to satisfy a linter; wrap the ignore instead.
2026-04-09: Use `type(x) is bool` (not `isinstance`) to validate VLM boolean fields — bool subclasses int in Python, so isinstance(True, int) is True; only `type(x) is bool` rejects integers while accepting booleans.
2026-04-09: In except clauses raising a different exception type, always use `from None` to suppress the exception chain — the new exception already carries all context, and chaining adds traceback noise in logs.
2026-04-09: Patch requests.Session.post (not requests.post) when the provider stores a session at __init__ time — instance method lookup falls through to the class, so patching the class method intercepts calls on already-constructed instances.
2026-04-09: exc_info=True on logger calls outside an except block is a silent no-op — sys.exc_info() returns (None, None, None) when no exception is being handled; only use exc_info=True inside except blocks.
