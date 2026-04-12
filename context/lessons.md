---
title: "vigil Lessons Learned"
summary: "Running log of corrections, preferences, and discoveries for the eldercare monitor project"
created: 2026-04-07
updated: 2026-04-07
---

# vigil Lessons Learned

<!-- Append dated one-liners below. When 3+ related lessons accumulate on a topic, extract into a dedicated context file. -->

2026-04-12: If a Flask route builds a notification channel inside `create_app()`, patch the imported constructor on the web module before calling `create_app()`; patching the instance method afterward misses the closure-scoped dependency.

2026-04-10: When adding side-effectful logging to existing Flask routes, all test fixtures that hit those routes must patch the new file path — not just fixtures created for the new feature. Update the shared `client` fixture and any inline test configs at the same time.

2026-04-10: Flask route tests that rely on the default `client` fixture break as soon as the route writes to disk — any route doing real I/O needs a tmp_path fixture so file paths resolve in tests.

2026-04-10: JSONL in-place label update — read all lines, match by `timestamp` field, update `label`, rewrite entire file; JSONL has no partial-line update primitive.

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
2026-04-09: Alert decision functions should raise ValueError on unknown enum values rather than silently returning None — silent fallthrough is the worst failure mode for safety-critical code; a crash is far preferable.
2026-04-09: CooldownTimer.start() must not extend an active cooldown — extending lets repeated unsafe frames push expiry forward indefinitely; idempotent no-op is the safe behavior.
2026-04-09: Pushover HTTP API requires form-encoded POST (`data=` not `json=`); priority 2 (emergency) requires `retry` and `expire` params — omit them entirely for lower priorities or the API rejects the request.
2026-04-09: `dataclasses.asdict()` preserves Enum objects inside nested dataclasses — dataset JSONL serialization needs an explicit recursive `.value` conversion before `json.dumps()`.
2026-04-09: A one-cycle orchestrator should accept injectable boundary helpers like `fetch_frame` — that keeps monitor-loop tests narrow and deterministic without patching global network calls.
2026-04-09: Full-cycle monitor integration tests should reuse the real `run_cycle(...)` and fake only the outer boundaries (frame source, provider, alert channel) — patching deeper adapters duplicates unit coverage and adds brittleness.
2026-04-10: Flask app silence state must be scoped to the `create_app` closure, not a module-level global — module-level state leaks across test instances sharing the same import; closure-scoped state resets with each `create_app()` call.
2026-04-10: When testing a route that reads a config-derived file path, use `dataclasses.replace` on the nested config dataclass to override the path to `tmp_path` — frozen dataclasses support `replace` so no monkey-patching needed.
2026-04-10: `git stash --include-untracked` stashes untracked files into a separate stash commit, but `git stash pop` fails if those untracked files already exist (e.g. after a merge created them) — drop the stash after confirming the important tracked-file changes were restored.
2026-04-10: When a worktree branches from a commit that predates untracked files in the main working tree, those files won't appear in the worktree; the merge back to main will fail unless they're removed first (after verifying the feature branch version is a superset).
2026-04-10: CSS `#modal-close` overriding `min-height: auto` from a base button rule breaks the 48px tap target — close buttons need explicit `min-height: var(--tap-height)` even when styled differently from other buttons.
2026-04-10: `flashButton()` re-enables the button internally after the delay — a `finally` block that also re-enables is dead code (idempotent but misleading); only use `finally` for re-enable when there is no `flashButton` call in both branches.
2026-04-10: `build_alert()` keyword-only args (`*`) keep the call site readable and prevent accidental positional mismatches when adding optional plumbing like `dashboard_url` and `timestamp` — frozen dataclass fields picked up automatically by `_build_section` when added with a default.
2026-04-10: Cloudflare Tunnel setup — store the tunnel token in EnvironmentFile=/etc/vigil/cloudflare.env (mode 600) so it stays out of the service unit (which is checked into git); systemd reads EnvironmentFile as root before dropping to the service user, so root-owned 600 works fine.
2026-04-10: Service unit templates hardcode User=pi but the Pi username is eyespy — setup scripts must substitute $SUDO_USER for "pi" via sed when copying .service files to /etc/systemd/system/; go2rtc.service and web_server.service will need the same treatment in install.sh.
2026-04-11: `crontab -u <user>` in install.sh requires root and writes to a named user's crontab — but when the install runs as root via sudo, use `sudo -u "$SERVICE_USER" crontab` instead, so the entry lands in the correct user's crontab rather than root's.
2026-04-11: When mocking `time.monotonic` in `run_forever` tests with a finite iterator, the iterator runs out because multiple monotonic calls occur per iteration (init + `now` + outage check + `last_successful_ping_at` on success) — use `sustained_outage_minutes=0` in the test config instead, which removes the need to mock time entirely.
2026-04-11: NanoGPT API is OpenAI-compatible at https://nano-gpt.com/api/v1; adding a new cloud provider is just a new *_provider.py with a configurable base URL + api key field in ApiConfig + entry in _PROVIDER_REQUIRED_SECRETS + elif branch in monitor.main(). DeepSeek-R1 ("thinking") has no vision — use Qwen3.5-122B-A10B (model ID on NanoGPT TBD) or qwen/qwen3.5-122b-a10b on OpenRouter.
2026-04-11: MJPEG streams can stall silently without firing an error event — add both exponential-backoff error retry (3s base, 60s max) and a periodic forced reconnect (setInterval every 5 min) as a stall safety net. WebRTC video would fix this properly but won't traverse Cloudflare Tunnel (UDP); defer until Mom is on Tailscale for both audio and video.
2026-04-12: Flask route functions must not share names with closure-scoped state objects — name route functions with a `_route` suffix (e.g. `stream_pause_route`) to avoid shadowing `StreamPauseState` variables like `stream_pause`.
2026-04-12: When testing Flask routes that serve static files, override `app.static_folder = str(tmp_path)` in the fixture so tests write placeholder files to a temp directory and never touch the real `static/` folder.
2026-04-12: Patch `web_server.PushoverChannel` (the constructor) before calling `create_app()` so the mock is captured in the closure; patching the instance method afterward misses the dependency already bound at factory time.
2026-04-12: Injecting a `clock` callable into AccessTracker and StreamPauseState (defaulting to `time.monotonic`) keeps time-dependent tests deterministic without monkeypatching builtins — use a mutable list `fake_time = [0.0]` and `clock=lambda: fake_time[0]` for controllable advancement.
