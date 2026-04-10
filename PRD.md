# grandma-watcher — Product Requirements Document

**Version:** 2.6
**Last Updated:** April 10, 2026
**Status:** Ready for Development  

---

## 1. Background & Problem Statement

A 97-year-old woman with Parkinson's disease is bed-bound and largely non-verbal. She cannot press call buttons, cannot advocate for herself, and frequently attempts to get out of bed — becoming stuck against bed rails or in dangerous positions she cannot escape from.

Her daughter (referred to as "Mom") is the full-time live-in caregiver. This situation creates severe caregiver burnout from constant vigilance. The builder (a paramedic and developer) lives remotely and cannot be physically present.

**The core problem:** Grandma needs help, cannot ask for it, and Mom cannot watch 24/7 without being destroyed by it.

**The goal:** A passive, AI-powered monitoring system that alerts Mom when Grandma needs attention, lets Mom check in remotely at any time, and reduces the cognitive and physical burden of constant vigilance.

---

## 2. Users

| User | Technical Level | Primary Need |
|---|---|---|
| Mom (caregiver, on-site) | Moderate | Receive alerts, view live feed on phone, talk to grandma |
| Builder (developer, remote) | High | Build, deploy, maintain, iterate |
| Grandma (patient) | None — passive subject | Not disturbed, not embarrassed, not harmed |

---

## 3. Core Requirements

### 3.1 Functional Requirements

- Passively monitor grandma in bed 24/7 via camera
- AI safety assessment every 30 seconds
- Instant push notification to Mom's phone when grandma is in an unsafe position, with a link to the dashboard frame (no image embedded in notification — images do not leave the home network)
- Gentle soft alert to Mom when the AI reports low-confidence unsafe readings in a sliding window (model is uncertain — Mom should check and label)
- Alert silencing: Mom can suppress notifications for a set duration (30 min default) without stopping monitoring — frames are still captured, analyzed, and logged during silence
- Live video feed Mom can access from her phone browser at any time, no app install required
- Two-way audio: Mom can speak to grandma through a speaker; grandma's room audio is heard by Mom
- Audio chime plays before Mom's voice comes through so grandma is not startled
- Selective dataset logging: alert frames + uncertain frames saved permanently; normal frames pruned after 7 days
- Mom can label AI assessments from the dashboard gallery (tap frame → "Real Issue" / "False Alarm") and report missed alerts via dashboard button
- System logs every time Mom checks the live stream or gallery (caregiver engagement log)
- Remote SSH access for the builder to manage and update the system

### 3.2 Non-Functional Requirements

- Must run 24/7 without intervention
- Must survive power outages without data corruption
- False positive rate target: fewer than 3 alerts per day that are clearly wrong
- Nighttime IR imaging required — grandma must not be disturbed by visible light
- No app install required for Mom to use
- All camera footage stays within the family's home network — no cloud video storage, no images embedded in push notifications
- Must be operable by Mom at a basic level (receive alerts, watch feed, make a call)

---

## 4. What This Is NOT

- Not a fall detection product (grandma is bed-bound; the risk is stuck positions, not falls)
- Not a medical device
- Not a replacement for caregiver judgment
- Not designed for grandma to interact with

---

## 5. System Architecture

### 5.1 Overview

```
[Grandma's Room]
  Raspberry Pi 5 8GB
  + Arducam Wide NoIR Camera V3 (CSI)
  + IR Illuminator 850nm (night)
  + USB Audio Adapter
  + USB Speaker
  + Lavalier Mic
  + CyberPower UPS
       |
       |── Camera frames every 30s (via go2rtc HTTP snapshot)
       |      └── Base64 encode
       |      └── Build prompt (image + sensor readings)
       |      └── Call OpenRouter API (Qwen3-VL-32B-Instruct)
       |      └── Parse + validate JSON response
       |      └── Save image + response to dataset (selective retention)
       |      └── If UNSAFE → Pushover alert + dashboard link (no image; silence check)
       |      └── Ping Healthchecks.io (silent heartbeat)
       |
       |── Live stream (go2rtc, always on)
       |      └── WebRTC output for browser
       |
       └── Flask web dashboard
              └── /stream → live video
              └── /gallery → recent frames + AI annotations + labeling buttons
              └── /talk → two-way audio
              └── /silence → silence alerts for N minutes (monitoring never stops; Mom can cancel early)
              └── /label/<id> → label a specific frame (real/false/missed)
              └── /report-missed → flag a missed alert for review

[Internet]
  Cloudflare Tunnel → Mom's browser (no app install)
  Tailscale VPN → Builder SSH access

[Mom's Phone]
  Pushover app receives alerts with image
  Browser bookmark opens dashboard
```

### 5.2 Architecture Decisions

**VLM approach over pose detection:** A Vision Language Model that reasons about the full scene provides better context-aware safety assessment than skeletal keypoint extraction, especially for a bed-bound patient partially covered by blankets.

**go2rtc owns the camera:** go2rtc is the sole owner of the CSI camera. `monitor.py` pulls snapshots via go2rtc's HTTP snapshot endpoint (`GET http://localhost:1984/api/frame.jpeg?src=grandma`) rather than using picamera2 directly. This avoids camera sharing conflicts and cleanly separates streaming from monitoring. If `monitor.py` crashes, the live stream stays up. go2rtc uses `rpicam-vid` (not `libcamera-vid` — deprecated) with `--libav-format h264`, which is required on Pi 5. See `go2rtc.yaml` for the full source configuration.

**API inference over local inference:** Phase 1 uses OpenRouter hosting Qwen3-VL-32B (~$11/month at 30-second intervals, 960×540 resolution). Together AI does not offer Qwen2.5-VL-72B on serverless endpoints. OpenRouter provides a single API key with easy model switching via config. Fallback model: Qwen2.5-VL-72B via Hyperbolic (~$45/month) if accuracy is insufficient.

**Hub and Spoke sensor architecture (Phase 2):** The Pi 5 acts as the central hub. Pi Zero 2W sensor nodes connect via WiFi HTTP endpoints. Each sensor node runs a tiny Flask HTTP server; the Pi polls them every few seconds and folds sensor readings into the VLM prompt.

**Selective dataset retention:** Not every frame has fine-tuning value. Alert-triggering frames and medium/low-confidence frames are retained long-term. Routine safe/high-confidence frames are pruned after 7 days. A random 1-in-20 sample of safe frames is kept for 30 days as negative training examples. The JSONL log is kept forever regardless. This reduces disk pressure while preserving the frames that matter.

**Mom-driven labeling via dashboard gallery:** Pushover alert notifications include a supplementary URL linking to the alert frame on the dashboard. Mom taps the link, sees the image and live video, then taps "Real Issue" or "False Alarm" — written to the log entry via `/label/<id>`. False negatives are reported via a "Report missed alert" button. This gives Mom full visual context before labeling, which is more accurate than labeling from a thumbnail in the notification.

**Split access model — Cloudflare for visual, Tailscale for audio:** Cloudflare Tunnel proxies HTTP only — WebRTC media (UDP) cannot traverse it. Two-way audio via go2rtc WebRTC requires a real UDP path, which Tailscale provides. Access is split accordingly:
- **Cloudflare Tunnel:** Dashboard, gallery, stream viewing, labeling, silencing — no app install, any browser
- **Tailscale:** Two-way audio ("Talk to Grandma") — requires Tailscale app on Mom's phone (one-time setup)

Mom needs one app install (Tailscale) for audio. All other features work from a browser bookmark. This is an acceptable tradeoff — audio is intentional and infrequent, browser access is the primary daily use.

**Cloudflare Access + Google OAuth for dashboard auth:** Mom authenticates via her Google account through Cloudflare Access. No password to manage; sessions persist for weeks on her phone. Builder can revoke access remotely from the Cloudflare dashboard.

**Healthchecks.io for silent system health monitoring:** The Pi pings a Healthchecks.io URL every monitoring cycle. If check-ins are missed, Healthchecks.io sends a Pushover alert to the builder first. For sustained outages (configurable threshold, default 30 minutes), a secondary alert is sent to Mom so she can physically check on grandma when the builder cannot intervene remotely. No noise when the system is healthy — only alerts on failure. Free tier is sufficient.

**Known limitation — internet dependency:** All AI inference runs on cloud APIs (OpenRouter). All remote access (dashboard, alerts, builder SSH) requires internet connectivity. A home internet outage means: no AI assessments, no Pushover alerts, no dashboard access, no remote builder access. The Healthchecks.io missed check-in alert will fire to the builder and Mom if outage is sustained, but they cannot use the system until connectivity is restored. This limitation will be resolved in Phase 4 when on-device inference is deployed. Until then, Mom remains the local safety net during outages.

**Pushover notifications — link only, no embedded images:** Pushover alerts include a dashboard URL link, not an embedded image. This keeps all visual footage within the home network and avoids accumulating images of a vulnerable person on third-party servers. Future notification channels (Signal bot, Matrix, native iOS app) are under consideration for Phase 3+.

**Storage — SD card for Phase 1, USB SSD option for Phase 2+:** Phase 1 uses the 128GB SD card for all data storage. SD cards have finite write endurance; continuous 24/7 writes will degrade the card over months. A USB SSD migration path is planned for Phase 2 — move `dataset/` to an external SSD, keep OS on SD. SD card health will be monitored via periodic checks during Phase 1 to determine when migration is needed.

**UPS graceful shutdown via apcupsd:** `apcupsd` monitors the CyberPower UPS via USB. On power loss it sends a Pushover alert to the builder immediately. At 30% remaining battery (~5 minutes of runtime), it initiates a clean system shutdown, preventing the hard power-off SD card corruption that is the leading cause of Pi data loss. This is configured in `setup/install.sh`.

**External Pi process heartbeat:** In addition to Healthchecks.io pings from `monitor.py` (which detect API/monitoring failure), the Pi runs a lightweight system-level heartbeat cron job that pings a separate Healthchecks.io check every 5 minutes regardless of application state. If the Pi itself crashes, hangs, or loses power without a clean shutdown, this external check misses its ping and alerts the builder. Two independent heartbeats: one from the application, one from the OS. Both route to the builder's Pushover.

---

## 6. AI / VLM Design

### 6.1 Model

**Provider:** OpenRouter  
**Model:** `qwen/qwen3-vl-32b-instruct` (~$11/month at 30s intervals, 960×540)  
**Fallback:** `qwen/qwen2.5-vl-72b-instruct` via Hyperbolic (~$45/month) if accuracy is insufficient  
**Note:** Together AI does not offer Qwen2.5-VL-72B on serverless — dedicated endpoints only (custom pricing).

**Cost estimate:** ~700 image tokens + ~350 prompt text tokens = ~1,050 input tokens per call. At 2,880 calls/day: ~3M input tokens/day + ~290K output tokens/day. Monthly: ~93M input ($9.70 at $0.104/M) + ~9M output ($3.74 at $0.416/M) = **~$13.50/month**. Actual cost varies with image tokenization — validate against the OpenRouter usage dashboard after first real test session.

**Local Testing (development only):**
During hardware bringup and camera integration testing, the builder can run a
local LM Studio instance (MacBook Pro) and point the Pi at it to avoid OpenRouter
API costs. Set `api.provider: lmstudio` in `config.yaml`. The Pi reaches LM Studio
over LAN or Tailscale; LM Studio must be configured to listen on `0.0.0.0`.
Switch back to `api.provider: openrouter` for production. See
`docs/superpowers/specs/2026-04-09-lmstudio-provider-design.md` for full details.

### 6.2 Prompt Template

```
You are a safety monitor for an elderly bed-bound patient with Parkinson's disease.
The patient is 97 years old, mostly non-verbal, and cannot call for help.

IMPORTANT CONTEXT:
- Tremors and unusual resting positions are NORMAL for this patient due to Parkinson's
- The patient is bed-bound and is always in or near the bed during normal care
- The bed has safety rails on the sides
- The patient is frequently covered by blankets — a patient-shaped lump under blankets means she is there and is SAFE
- A caregiver may be partially or fully out of frame during repositioning, hygiene, or bedding changes

ANALYZE this image and determine if the patient is SAFE, UNSAFE, or UNCERTAIN.

UNSAFE — use high or medium confidence when you can clearly see:
- A limb or the body visibly caught against or trapped in a bed rail
- A limb at an angle that looks painful or mechanically constrained (not just an unusual resting position)
- The patient's body significantly hanging over the edge of the mattress
- The patient visibly falling, being dropped, or suspended without support

SAFE — respond safe:true when:
- Patient is resting in or on the bed in any position, including on their side or curled
- A patient-shaped lump is visible under blankets in the bed (assume patient is there)
- Unusual resting positions that are not dangerous (Parkinson's patients often rest in asymmetric postures)
- A caregiver or family member is visibly present and the patient is not in acute physical danger (not falling, not unsupported mid-air, not being dropped)
- Signs of active care are present (rails lowered, medical supplies visible) — assume a caregiver is nearby even if out of frame

UNCERTAIN — use low confidence when:
- The bed appears completely empty with no patient-shaped lump (patient may have been moved by a caregiver)
- Image quality is too poor to assess (extreme darkness, lens obstruction, severe glare)
- Patient's exact position relative to the rails is genuinely ambiguous

Respond ONLY with valid JSON in this exact format:
{
  "safe": true or false,
  "confidence": "high", "medium", or "low",
  "reason": "one sentence explanation",
  "patient_location": "in_bed", "being_assisted_out", "out_of_bed", or "unknown"
}

patient_location rules:
- "in_bed": patient is visible in or on the bed, or a patient-shaped lump is under blankets
- "being_assisted_out": a caregiver is VISIBLY present AND the patient is actively being moved out of the bed — do NOT use this if no caregiver is visible
- "out_of_bed": bed appears empty, no patient-shaped lump present
- "unknown": image quality is too poor to determine, or situation is genuinely ambiguous

IMPORTANT: if the patient appears to be moving toward the bed edge WITHOUT a visible caregiver, set patient_location to "in_bed" and safe to false. Unsupported movement is an unsafe exit attempt, not an assisted transfer.
```

Note: `prompt_builder.py` adds a SENSOR READINGS section and `sensor_notes` response field only when at least one sensor is enabled in config. The Phase 1 prompt omits both.

### 6.3 Alert Logic

| Condition | Action |
|---|---|
| `safe: false`, confidence `high` | **Immediate Pushover alert — no cooldown check, always fires** |
| `safe: false`, confidence `medium`, 2-of-5 frames | Pushover alert (respects cooldown) |
| `safe: false`, confidence `low` | Log, increment low-confidence window counter |
| `safe: false`, confidence `low`, 3-of-5 frames | Soft Pushover alert to Mom: "System uncertain — please check on grandma and label the frames" (60-min cooldown) |
| `safe: true` | Log (does not reset sliding window counters) |
| API error / invalid JSON | Log error, retry once with same provider, then increment failure counter |
| 5 consecutive API failures | Auto-switch to fallback provider (Hyperbolic), alert builder via Pushover |
| Valid JSON but missing/wrong fields | Log schema error, treat as API failure |

**High confidence always fires:** `safe: false, confidence: high` bypasses all cooldown logic. A real emergency should never be silenced by a prior false positive.

**Sliding window counters:** Medium and low confidence unsafe assessments are tracked in a rolling 5-frame window. A `safe: true` response does not reset the window — it simply adds a "safe" frame to the window. This prevents model noise (safe/unsafe/safe/unsafe oscillation) from indefinitely suppressing soft alerts. Counters are in-memory only and reset on process restart or silence activation. Accepted tradeoff for Phase 1.

**Auto-failover:** After 5 consecutive API failures (~2.5 minutes of blindness), `monitor.py` automatically switches to the fallback provider defined in config and sends a Pushover alert to the builder. On recovery, it does not auto-switch back — the builder manually restores the primary provider when confident it is stable.

**patient_location state machine:** `monitor.py` tracks a `patient_location` state derived from the rolling VLM responses. This drives automatic alert silencing without requiring Mom to do anything.

| patient_location state | Consecutive frames | System action |
|---|---|---|
| `in_bed` | Any | Normal monitoring |
| `being_assisted_out` | 1+ | Mark safe, begin watching for `out_of_bed` |
| `out_of_bed` | 3 (≈90 seconds) | Auto-silence alerts, log `silence_activated` |
| `in_bed` after auto-silence | 2 | Auto-resume alerts, Pushover to Mom: *"Grandma appears to be back in bed — monitoring resumed. If she's NOT in bed, tap to re-silence."* (supplemental URL → /silence) |
| `unknown` | Any | Treat as `in_bed`, stay alert |

**patient_location validation:** If the field is missing or has an unexpected value, default to `unknown`. Never crash on a missing field. The `safe` field is always the primary alert trigger — `patient_location` only drives silence state, never suppresses a `safe: false, high` alert.

**Window flush on silence:** When silence activates (auto or manual), the N-of-5 sliding window for medium and low confidence assessments is flushed. The counter starts fresh when monitoring resumes. Silence events are often separated from the preceding monitoring session by hours — stale pre-silence frames should not influence post-return alerts.

**Response validation rules:** `safe` must be a boolean; `confidence` must be one of `"high"`, `"medium"`, `"low"`; `reason` must be a non-empty string. Any other values are treated as schema errors.

### 6.4 Alert Cooldown

- **High confidence:** No cooldown. Always fires immediately.
- **Medium confidence:** 5-minute global cooldown. 
- **Low confidence (soft alert):** 60-minute cooldown.

Cooldown is global, not per trigger type — free-text reason matching is unreliable and not implemented.

**⚠ Open question — alert escalation:** If Mom receives an alert and does not check the dashboard or live stream within a defined window, should the system re-alert, alert the builder, or do nothing? This behavior needs to be decided in conversation with Mom before deployment. See task: *"Discuss alert escalation preferences with Mom."*

### 6.5 Provider Failover

| Failure count | Action |
|---|---|
| 1–4 consecutive failures | Log, retry next cycle |
| 5 consecutive failures | Switch to fallback provider, alert builder |
| Recovery | Stay on fallback until builder manually restores primary |

Config key `api.fallback_provider` and `api.fallback_model` specify the failover target. Failure count resets on any successful API response.

---

## 7. Hardware Bill of Materials

### 7.1 Phase 1 — Order Now (Development + Deployment)

| Item | Link / Source | Est. Price | Notes |
|---|---|---|---|
| CanaKit Raspberry Pi 5 Essentials Starter Kit (8GB) | Amazon | $189.97 | Includes case, 45W PSU, 32GB SD, USB reader |
| SanDisk Extreme 128GB microSD A2 | Amazon — SDSQXAA-128G | ~$16 | Replace 32GB before first boot |
| Arducam IMX708 120° Wide Angle NoIR Camera V3 | Amazon — B0... | $42.99 | 120° FOV, PDAF autofocus, Pi 5 CSI |

**Phase 1 "order today" total: ~$249**

The following Phase 1 items should be purchased before deployment but are not needed for development:

| Item | Est. Price | Notes |
|---|---|---|
| Univivi IR Illuminator 850nm (includes 12V adapter) | ~$16 | amazon.com/dp/B01G6K407Q — skip during daylight dev |
| UGREEN USB Audio Adapter | ~$11 | amazon.com/dp/B087T5H3MQ |
| Logitech S150 USB Speaker | ~$20 | amazon.com/dp/B000ZH98LU |
| Movo LV1 Clip-On Lavalier Mic (3.5mm) | ~$15 | Clips to headboard |
| CyberPower CP425SLG Mini UPS | ~$40 | Prevents SD card corruption on outage |
| 3M Command Large Strips | ~$10 | For mounting camera and device |
| White cable raceway kit | ~$15 | Tidy cable runs |

**Full Phase 1 total (all items): ~$370**

### 7.2 Phase 2 — Sensor Nodes (Ship Later)

Phase 2 introduces Pi Zero 2W sensor nodes that communicate with the Pi 5 hub over WiFi HTTP. Buy from PiShop.us (authorized reseller, $15 MSRP, not affected by Pi 5 memory shortage).

**Node 1 — Load Cells (under bed legs, tracks weight distribution)**

| Item | Est. Price |
|---|---|
| Pi Zero 2W with pre-soldered headers (pishop.us) | ~$17 |
| 4x 50kg bar load cells | ~$15 |
| 4x HX711 load cell amplifier boards | ~$12 |
| Micro SD 32GB | ~$8 |
| 5W USB power adapter | ~$6 |

**Node 2 — Vitals + Environment**

| Item | Est. Price |
|---|---|
| Pi Zero 2W with pre-soldered headers (pishop.us) | ~$17 |
| Seeed MR60BHA1 mmWave sensor (breathing + HR) | ~$38 |
| DHT22 temperature + humidity sensor | ~$6 |
| Micro SD 32GB | ~$8 |
| 5W USB power adapter | ~$6 |

**Phase 2 total: ~$133**

### 7.3 Future Consideration — Camera Extension

If camera placement requires more than ~50cm of cable between the Pi and the camera mount point, add:

| Item | Est. Price | Notes |
|---|---|---|
| Arducam CSI-to-HDMI Extension Kit | ~$22 | amazon.com/dp/B06XDNBM63 — extends camera up to 3–5m via HDMI cable |

Measure the room before purchasing. Skip entirely during development.

### 7.4 Hardware Decisions Log

**Pi 5 8GB over Pi 5 4GB:** Memory headroom for concurrent processes — go2rtc streaming, Flask server, camera capture, API calls, and eventually local sensor processing all running simultaneously.

**Pi 5 over Intel N100 mini PC:** Pi 5 has native GPIO for Phase 2 sensor nodes, native CSI camera connector, and while currently inflated in price (~$120–168 on Amazon from third-party sellers vs ~$95 original MSRP), the CanaKit bundle at $189.97 includes PSU, case, and SD card, making the true price comparison reasonable. N100 mini PCs were confirmed at $379+ on Amazon — far exceeding estimates.

**Pi 5 over Jetson Orin Nano Super ($249):** The Jetson's AI hardware is wasted when using API inference (Phase 1–3). The Pi 5 CanaKit bundle at $189.97 is $60 cheaper and includes accessories. The Jetson has a fan (not ideal for a bedroom). The Pi ecosystem is better documented for this exact use case.

**Arducam Wide NoIR (120°) over standard NoIR (75°):** The 120° field of view is better suited for overhead or high-wall mounting to capture a full bed in frame. Autofocus handles variable camera placement distances.

**128GB SD over 32GB:** At ~1.3GB/day of dataset images (1 frame/20 sec @ 300KB avg JPEG), the 32GB would fill in 2–3 weeks. The 128GB provides ~3–4 months of headroom before file transfer or pruning is needed.

---

## 8. Software Stack

| Component | Technology | Notes |
|---|---|---|
| OS | Raspberry Pi OS Lite (64-bit) | Headless |
| Camera | go2rtc + rpicam-vid | go2rtc owns CSI camera; monitor.py pulls HTTP snapshots |
| Live streaming | go2rtc | WebRTC, RTSP, HLS output; two-way audio |
| Web dashboard | Flask + WebSocket | Mom's browser interface |
| AI inference | OpenRouter API | Qwen3-VL-32B-Instruct (~$13.50/month) |
| Alerts | Pushover | $5 one-time iOS/Android app |
| Remote access (Mom) | Cloudflare Tunnel | No app install, browser only |
| Remote access (Builder) | Tailscale | SSH admin access |
| Dataset storage | Local filesystem + JSONL | Images in `/dataset/images/`, log in `/dataset/log.jsonl` |
| Sensor nodes | Flask HTTP on Pi Zero 2W | Polled by hub every 5 seconds |
| UPS management | apcupsd | Power loss alerts + graceful shutdown at 30% battery |
| System heartbeat | cron + Healthchecks.io | OS-level ping every 5 min, independent of application |
| Config | `config.yaml` | All settings, feature flags |

---

## 9. File Structure

```
eldercare/
  config.yaml              ← API keys, thresholds, sensor enable/disable flags
  monitor.py               ← Main loop: capture → prompt → API → alert → log
  web_server.py            ← Flask: /stream, /gallery, /talk, /status
  alert.py                 ← Pushover wrapper + cooldown logic
  sensors.py               ← HTTP polling of Pi Zero sensor nodes
  prompt_builder.py        ← Builds VLM prompt from config + current sensor readings
  dataset.py               ← Logging, image saving, label utilities, pruning
  smoke_test.py            ← End-to-end system verification (camera, API, Pushover, tunnel, disk, UPS)
  go2rtc.yaml              ← go2rtc camera + streaming config
  setup/
    install.sh             ← Full system setup script (installs all services, apcupsd, cron heartbeat)
    tailscale_setup.sh
    cloudflare_setup.sh
    apcupsd.conf           ← UPS config: power loss alert + shutdown at 30% battery
    systemd/
      monitor.service
      web_server.service
      go2rtc.service
  templates/
    dashboard.html         ← Mom's interface
  static/
    dashboard.js           ← WebSocket for real-time alerts
    dashboard.css
  dataset/
    images/                ← Saved frames (JPEG)
    log.jsonl              ← One JSON line per inference
  docs/
    MOM_GUIDE.md           ← How to use the dashboard and alerts
    INSTALL_GUIDE.md       ← Setup from scratch
    SENSOR_SETUP.md        ← Phase 2 sensor node setup
```

---

## 10. config.yaml Specification

```yaml
# API Configuration
api:
  provider: "openrouter"  # openrouter | hyperbolic | anthropic | lmstudio
  model: "qwen/qwen3-vl-32b-instruct"
  openrouter_api_key: ""
  hyperbolic_api_key: ""
  anthropic_api_key: ""
  timeout_connect_seconds: 10
  timeout_read_seconds: 30
  fallback_provider: "hyperbolic"
  fallback_model: "qwen/qwen2.5-vl-72b-instruct"
  consecutive_failure_threshold: 5  # failures before auto-switching to fallback
  lmstudio_base_url: "http://localhost:1234"  # LM Studio server URL (LAN/Tailscale for Pi→Mac)
  lmstudio_model: "qwen3-vlm-7b"             # Model name as shown in LM Studio UI (case-sensitive)

# Monitoring
monitor:
  interval_seconds: 30
  image_width: 960
  image_height: 540
  silence_duration_minutes: 30  # default alert silence duration (monitoring continues)

# Healthchecks.io
healthchecks:
  app_ping_url: ""      # monitor.py pings this — detects application-level failure
  system_ping_url: ""   # cron pings this every 5 min — detects OS/Pi-level failure
  # Both are separate Healthchecks.io checks configured to alert the builder on miss.
  # After sustained_outage_minutes of missed app pings, monitor.py also alerts Mom directly.
  sustained_outage_minutes: 30
  mom_pushover_user_key: ""  # Mom's Pushover key for outage escalation

# UPS (managed by apcupsd, not this config — see setup/apcupsd.conf)
# apcupsd sends Pushover to builder on power loss and shuts down Pi at 30% battery.
# apcupsd config is in setup/apcupsd.conf and installed by setup/install.sh.

# Alert Thresholds
alerts:
  pushover_api_key: ""
  pushover_user_key: ""
  pushover_builder_user_key: ""   # builder's Pushover user key (for system health alerts)
  cooldown_minutes: 5
  window_size: 5                           # sliding window size for medium/low counters
  medium_unsafe_window_threshold: 2        # N-of-5 medium-unsafe frames triggers alert
  low_unsafe_window_threshold: 3           # N-of-5 low-unsafe frames triggers soft alert
  low_confidence_cooldown_minutes: 60
  # escalation:  # ⚠ Undecided — discuss with Mom before implementing
  #   enabled: false
  #   no_response_minutes: 15     # time before escalation if no dashboard check-in after alert
  #   escalate_to_builder: true

# Dataset
dataset:
  base_dir: "/home/pi/eldercare/dataset"  # absolute path required
  images_dir: "/home/pi/eldercare/dataset/images"
  log_file: "/home/pi/eldercare/dataset/log.jsonl"
  checkin_log_file: "/home/pi/eldercare/dataset/checkins.jsonl"
  max_disk_gb: 50  # warn when dataset exceeds this
  # Retention policy
  retention:
    alert_frames: "forever"
    uncertain_frames_days: 30      # medium/low confidence
    safe_sample_frames_days: 30    # 1-in-20 random safe frames (negative training examples)
    safe_unsample_frames_days: 7   # all other safe frames

# Streaming (go2rtc)
# Camera source and stream config lives in go2rtc.yaml (not here).
# Pi 5 CSI camera uses rpicam-vid via exec: source — NOT /dev/video0.
stream:
  go2rtc_api_port: 1984
  snapshot_url: "http://localhost:1984/api/frame.jpeg?src=grandma"
  stream_name: "grandma"

# Web Dashboard
web:
  port: 8080
  gallery_max_items: 50

# Cloudflare Tunnel
cloudflare:
  tunnel_token: ""
  # Auth handled by Cloudflare Access + Google OAuth (configured in Cloudflare dashboard)

# Tailscale
tailscale:
  enabled: true

# Sensors (Phase 2 — all disabled by default)
sensors:
  load_cells:
    enabled: false
    node_url: "http://loadcells.local:5000/sensors"
    poll_interval_seconds: 5
  vitals:
    enabled: false
    node_url: "http://vitals.local:5000/sensors"
    poll_interval_seconds: 5

# Audio
audio:
  chime_before_talk: true
  chime_file: "static/chime.mp3"
```

---

## 11. Dataset Schema

### 11.1 Log Entry (`log.jsonl`)

One JSON object per line:

```json
{
  "timestamp": "2026-04-07T03:22:11Z",
  "image_path": "/home/pi/eldercare/dataset/images/2026-04-07_03-22-11.jpg",
  "image_pruned": false,
  "provider": "openrouter",
  "model": "qwen/qwen3-vl-32b-instruct",
  "prompt_version": "1.0",
  "sensor_snapshot": {
    "load_cells_enabled": false,
    "vitals_enabled": false
  },
  "response_raw": "{\"safe\": true, \"confidence\": \"high\", ...}",
  "safe": true,
  "confidence": "high",
  "reason": "Patient is resting flat in bed, centered on mattress, within bed frame.",
  "patient_location": "in_bed",
  "alert_fired": false,
  "silence_active": false,
  "api_latency_ms": 2140,
  "label": null
}
```

The `label` field is `null` until reviewed. Values: `"correct"`, `"false_positive"`, `"false_negative"`. Labels are written by:
- Mom tapping "Real Issue" or "False Alarm" on the dashboard label page (linked from Pushover alert notification URL)
- Builder reviewing logs via SSH
The `image_pruned` field is set to `true` when a frame is deleted per the retention policy — the log entry is preserved but the image file is gone. This becomes the fine-tuning dataset.

### 11.2 Retention Policy per Frame

| Condition | Retention |
|---|---|
| `alert_fired: true` | Forever |
| `confidence: "medium"` or `"low"` | 30 days |
| Safe + high confidence + 1-in-20 random sample | 30 days |
| All other safe + high confidence frames | 7 days |
| JSONL log entries | Forever |

### 11.3 Caregiver Check-in Log (`checkins.jsonl`)

One entry per event:

```json
{
  "timestamp": "2026-04-07T03:22:11Z",
  "event": "stream_opened",  // stream_opened | gallery_opened | silence_activated | silence_cancelled | silence_expired | missed_alert_reported
  "source_ip": "192.168.1.x"
}
```

Used to track Mom's engagement and identify false positive fatigue remotely.

---

## 12. Phased Roadmap

### Phase 1 — Core Monitoring (Months 1–2, ~$370 total)

**Goal:** A working system deployed in grandma's room that Mom trusts.

**Components:**
- Pi 5 with camera, IR illuminator, audio
- VLM API monitoring on fixed 30-second interval
- Pushover alerts with image on unsafe detection
- go2rtc live stream
- Flask dashboard (stream, gallery, talk button)
- Cloudflare Tunnel for Mom, Tailscale for builder
- Full dataset logging

**Success gate:** Fewer than 3 false positives per day. System runs 2+ weeks without manual intervention. Mom checks in voluntarily.

### Phase 2 — Sensor Nodes (Months 3–4, ~$133 additional)

**Goal:** Add breathing/vitals monitoring and weight distribution sensing.

**Components:**
- Pi Zero 2W load cell node (under bed legs)
- Pi Zero 2W vitals node (mmWave + temp)
- Sensor readings folded into VLM prompt
- Dashboard sensor status panel (green/yellow/red indicators)

**Deployment:** Nodes are pre-configured before shipping to grandma's location. Mom plugs them in; system discovers them via mDNS. Builder enables them via `config.yaml` flip.

**Success gate:** Breathing detection working reliably. False positive rate unchanged or improved.

### Phase 3 — Intelligence (Months 5–6, software only)

**Goal:** Smarter alerting, dataset ready for fine-tuning.

**Components:**
- Replace fixed-interval polling with sensor-triggered VLM calls
- Dashboard labeling tool (tap frame → mark correct/incorrect)
- 2,000+ labeled images in dataset
- Nightly rsync to builder's machine

### Phase 4 — Local Inference (Month 6+)

**Goal:** Move inference off the cloud for privacy and cost.

**Options:**
- Mac Mini M4 24GB ($799): Runs Qwen2.5-VL-7B via Ollama, silent, 40W
- Mac Mini M4 Pro 48GB ($1,999): Runs larger models, more future-proof

**Note:** A Jetson Orin Nano Super ($249) runs Qwen2.5-VL-3B locally but with noticeably lower accuracy than 7B. The Mac Mini is the better choice when local inference is the goal.

---

## 13. Networking Setup

### Mom's Access — Dashboard (Cloudflare Tunnel)
- Pi runs `cloudflared` as a systemd service
- Dashboard accessible at a fixed URL (e.g., `https://grandma.yourdomain.com`)
- No app install required; works in any mobile browser
- Authenticated via Cloudflare Access + Google OAuth
- Cloudflare Access session duration should be configured to 30 days to minimize re-auth friction for Mom
- Covers: stream viewing, gallery, labeling, silencing, report-missed

### Mom's Access — Two-Way Audio (Tailscale)
- Mom installs Tailscale on her phone (one-time setup, handled by builder before shipping)
- go2rtc WebRTC negotiates directly over Tailscale's VPN (UDP traversal works natively)
- go2rtc dashboard UI accessed via Pi's Tailscale IP: `http://<pi-tailscale-ip>:1984/stream.html?src=grandma`
- Audio works from anywhere Mom has Tailscale connected
- **Why not Cloudflare:** Cloudflare tunnels are HTTP-only; WebRTC media uses UDP and cannot traverse them

### Builder's Access (Tailscale)
- Pi and builder's machine are on the same Tailscale network
- SSH access via Pi's Tailscale IP
- Used for system updates, log review, config changes, dataset management

### Static IP
- Pi assigned static local IP via router DHCP reservation
- Sensor nodes assigned static IPs or resolved via mDNS (`loadcells.local`, `vitals.local`)

---

## 14. Two-Way Audio Design

**Hardware:**
- UGREEN USB Audio Adapter → provides 3.5mm mic input + headphone output to Pi
- Logitech S150 USB Speaker → plugged into USB for audio output
- Movo LV1 lavalier mic → clips to headboard, plugs into UGREEN adapter's mic input

**Call flow:**
1. Mom taps "Talk to Grandma" on dashboard
2. Pi plays audio chime through speaker (grandma hears someone is connecting)
3. WebRTC two-way audio session opens via go2rtc
4. Mom's phone mic → go2rtc → Pi speaker → grandma hears Mom
5. Room mic → go2rtc → Mom's phone speaker → Mom hears grandma
6. Mom taps "End" to close session

**go2rtc handles WebRTC audio/video natively.** No custom audio streaming code needed. Audio requires Mom's phone to be on Tailscale (see §13). Two-way audio does not work through Cloudflare Tunnel.

---

## 15. Alert Silencing Behavior

**Silencing ≠ stopping monitoring.** Whether triggered automatically or manually, silencing only suppresses alert delivery. The system continues capturing frames, calling the API, and logging every result. The dataset is never interrupted.

### Automatic Silencing (via patient_location)

The system silences and resumes alerts automatically based on the VLM's `patient_location` field. No action required from Mom for routine care transfers.

| Trigger | Behavior |
|---|---|
| `out_of_bed` for 3 consecutive frames | Auto-silence, log `silence_activated` |
| `in_bed` for 2 consecutive frames after auto-silence | Auto-resume, Pushover to Mom: *"Grandma appears to be back in bed — monitoring resumed. If she's NOT in bed, tap to re-silence."* (supplemental URL → /silence) |
| `being_assisted_out` detected | Safe, no silence yet — watches for `out_of_bed` to confirm transfer complete |

### Manual Silencing (via dashboard)

Mom can silence manually at any time for scenarios the model may not catch cleanly.

| Behavior | Detail |
|---|---|
| Default duration | 30 minutes (configurable) |
| Mom can cancel early | Yes — "End Silence" button on dashboard |
| Silence can be extended | No — must cancel and re-activate |
| Resume notification | Pushover to Mom: *"Alert monitoring resumed"* |
| Silence logged | `checkins.jsonl`: `silence_activated`, `silence_cancelled`, `silence_expired` |
| Builder visibility | Silence state and source (auto/manual) shown on dashboard |
| Stacking silences | Not allowed — must cancel current before starting new |

### High-Confidence Events During Silence

`safe: false, confidence: high` **always fires, even during silence.** If the model is certain grandma is in danger, Mom is notified regardless of silence state. This is the one hard override.

### Phase 2 Enhancement

When load cell sensor nodes are deployed, weight dropping to zero under the bed legs provides an instant, unambiguous "grandma left the bed" signal. Combined with `patient_location`, reliability of auto-silencing improves significantly.

## 16. Developer Tooling

### 16.1 Model Probe (`probe.py`)

A standalone CLI tool for interactively testing the VLM without running the full monitor pipeline. Used to evaluate what the model can and cannot detect, iterate on prompt ideas, and validate model behavior against live or saved frames.

**Problem it solves:** The production monitor enforces a strict JSON response schema (via `vlm_parser.py`) tuned for eldercare assessment. Testing any other prompt — object detection, scene description, capability probing — fails schema validation. `probe.py` bypasses the schema entirely, returns raw model responses, and supports continuous stream watching so the developer can observe model behavior over time with minimal friction.

**Usage:**
```bash
# Stream mode (default) — loops at configured interval, reads probe_prompt.md
python probe.py

# Single frame from live go2rtc snapshot
python probe.py --single

# Single frame from saved JPEG (implies --single)
python probe.py --image /path/to/frame.jpg

# Inline prompt override
python probe.py --prompt "Is there a cat visible?"

# Different prompt file
python probe.py --prompt-file my_experiment.md

# Override provider or model without editing config.yaml
python probe.py --provider openrouter --model qwen/qwen3-vl-32b-instruct
```

**Behavior:**
- **Stream mode (default):** fetches a live frame from go2rtc, sends to model, prints raw response, sleeps `monitor.interval_seconds`, repeats until Ctrl+C. Prints a timestamp header before each response. On Ctrl+C, prints a clean summary ("Stopped after N cycles") instead of a traceback.
- **Single mode (`--single` or `--image`):** fetches one frame, prints response, exits.
- **Prompt resolution order:** `--prompt` (inline) → `--prompt-file <path>` → `probe_prompt.md` in project root. If the resolved file is missing or empty, exits with a clear error message.
- **Provider/model:** defaults to `config.yaml` values; `--provider` and `--model` override without touching the file.
- **go2rtc errors:** prints a human-readable message ("Could not connect to go2rtc at {url} — is it running?") rather than a raw traceback.
- Makes direct HTTP calls to the provider endpoint — does not go through `vlm_parser.py` or the provider classes. Raw response string only.
- Requires a valid `config.yaml` in the project root (same as all other scripts). Pushover keys must be present even though alerts are never sent — this is a known limitation of `load_config()` validation.
- Not intended for production use; developer tool only.

**Files:**
- `probe.py` (new, ~100 lines)
- `probe_prompt.md` (new, starter prompt — committed to repo)

No changes to existing modules.

---

## 17. Risk Register

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| High false positive rate alarms Mom repeatedly | Medium | High | Confidence threshold logic, cooldown, iterative prompt tuning |
| SD card corruption on power outage | Medium | High | UPS + apcupsd graceful shutdown at 30% battery; Pushover alert to builder on power loss; journaling filesystem |
| OpenRouter API outage | Low | High | Fallback to Hyperbolic (Qwen2.5-VL-72B) via config provider switch; alert builder if 3+ consecutive API failures |
| Camera angle misses dangerous position | Medium | Medium | Test placement carefully; overhead preferred over side |
| Mom ignores alerts due to false positive fatigue | Medium | High | Tune aggressively in first two weeks; get false positives under 3/day |
| Pi overheats running 24/7 | Low | Medium | Active cooler included in CanaKit PRO kit; monitor CPU temp |
| Grandma disturbed by IR illuminator | Low | Low | 850nm is nearly invisible; use 940nm if any issue |
| Privacy concern — bedroom camera | Low | Medium | All footage local; no cloud video; no images in notifications; Cloudflare tunnel is authenticated |
| Home internet outage | Medium | High | **Known limitation (Phase 1).** System cannot monitor or alert without internet. Healthchecks.io alerts builder + Mom after 30 min outage. Mom is local safety net. Resolved in Phase 4 with on-device inference. |
| SD card wear / failure | Medium | High | Monitor card health during Phase 1. USB SSD migration planned for Phase 2. UPS provides graceful shutdown time (but no shutdown script yet — to be added). |

---

## 18. Open Questions

1. **Camera mount position** — Overhead (ceiling) vs. high wall at 45° angle. Needs physical room assessment before final install. Overhead is preferred.

2. **File transfer cadence** — Nightly rsync to builder's machine vs. manual periodic pull. Automated nightly rsync via cron is simpler but requires builder's machine to be accessible. Deferred to Phase 3.

3. **Dashboard authentication** — ~~Resolved: Cloudflare Access + Google OAuth.~~ Mom authenticates via Google account.

4. **Audio chime selection** — Soft enough not to startle grandma, distinct enough for her to register. Needs real-world testing.

5. **Nighttime IR image quality** — VLM accuracy on 850nm IR-lit frames is untested. Must be validated before shipping to Florida. If accuracy is poor, may need to switch to 940nm illuminator or adjust camera exposure settings.

6. **Model accuracy at 960×540** — Starting resolution is a cost/quality tradeoff. Needs validation against representative frames (various positions, lighting conditions, daytime vs. IR night) before committing to production.

7. **Out-of-bed mode (Phase 2)** — When grandma is taken out of bed for care or an outing, the current system has no way to distinguish this from a genuine absence. Silence is the workaround for Phase 1. A dedicated "Out of Bed" mode — where an empty bed is expected and the system alerts if she doesn't return within N minutes — is a Phase 2 feature.

8. ~~**Deployment verification protocol**~~ — Resolved: see §17 First Boot Sequence and `smoke_test.py`.

---

## 19. Florida Deployment — First Boot Sequence

The Pi ships pre-configured. Mom's only physical actions are: plug in power, plug in Ethernet (or confirm it connects via WiFi). Everything else is automatic or builder-managed remotely.

### Pre-Ship Checklist (Builder Completes Before Shipping)

- [ ] Flash 128GB SD with Raspberry Pi OS Lite 64-bit
- [ ] Pre-configure WiFi: Mom's SSID and password written to `wpa_supplicant.conf` on boot partition
- [ ] Set hostname to `eldercare`
- [ ] Enable SSH
- [ ] Clone repo, run `setup/install.sh` — installs all services, go2rtc, apcupsd, Tailscale, cloudflared
- [ ] Authenticate Tailscale on the Pi (builder logs in via their Tailscale account)
- [ ] Add Cloudflare tunnel token to `config.yaml`
- [ ] Add all API keys to `config.yaml`
- [ ] Pre-configure Mom's Google account in Cloudflare Access
- [ ] Install Tailscale on Mom's phone and join the Tailscale network
- [ ] Test end-to-end on builder's own network: camera → API → Pushover alert received
- [ ] Ship with: Pi + power supply + SD card + Ethernet cable (WiFi backup) + camera cable

### First Boot (Mom Plugs In)

1. Mom connects Ethernet cable to router (WiFi also attempted automatically)
2. Pi boots, connects to internet, authenticates Tailscale
3. All systemd services start: go2rtc, monitor, web_server, cloudflared
4. On successful first boot, Pi sends Pushover to builder: *"eldercare online. Camera: ✓ API: ✓ Stream: ✓ Tunnel: ✓"* (or reports which component failed)
5. Builder confirms via Tailscale SSH that everything is running: `systemctl status monitor web_server go2rtc cloudflared`
6. Builder opens dashboard via Cloudflare URL to visually confirm camera angle
7. Builder calls Mom to walk through: opening the dashboard bookmark, what an alert looks like, how to silence, how to use the talk feature
8. If WiFi-only and connection fails: Mom plugs in Ethernet cable, builder debugs WiFi credentials remotely via Tailscale

### Smoke Test (Run After First Boot or Any Major Change)

```bash
python smoke_test.py
```

Checks and reports:
- go2rtc running and returning a valid snapshot
- OpenRouter API responding with valid JSON
- Pushover delivering to both Mom and builder
- Cloudflare tunnel reachable from the internet
- Tailscale connected
- Disk space above threshold
- UPS connected and on mains power

Exits 0 on all pass, 1 on any failure. Builder can run this remotely via Tailscale SSH at any time.

## 20. Developer Setup Notes

### Getting Started (Claude Code)

```bash
git clone <your-repo>
cd eldercare
cp config.yaml.example config.yaml
# Fill in API keys in config.yaml
pip install -r requirements.txt
python monitor.py --dry-run  # Test camera + API without alerts
python web_server.py          # Test dashboard in browser
```

### Pi First Boot

```bash
# Flash Raspberry Pi OS Lite 64-bit to 128GB SD card using Pi Imager
# Enable SSH, set hostname to 'eldercare', configure WiFi
ssh pi@eldercare.local
cd ~/
git clone <your-repo> eldercare
cd eldercare && ./setup/install.sh
```

### Key Dependencies

```
requests         # API calls + go2rtc snapshot fetch
flask            # Dashboard
flask-socketio   # Real-time alerts
python-pushover  # Push notifications
pyyaml           # Config
pillow           # Image encoding/processing
```

Note: `picamera2` is NOT a dependency. Camera access is handled entirely by go2rtc.

---

*This PRD reflects all decisions made through April 10, 2026. Hardware confirmed via Amazon screenshots. Architecture finalized through builder-led design sessions.*
