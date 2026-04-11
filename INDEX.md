# grandma-watcher Index

Quick-reference for finding content in this directory. For conventions, see `context/conventions.md`. For full architecture and hardware decisions, see `PRD.md`.

## Core Application Files

| File | Purpose | When to Use |
|------|---------|-------------|
| `monitor.py` | Main loop: capture → prompt → API → alert → log | Entry point for monitoring logic |
| `healthchecks.py` | Healthchecks.io dead-man's-switch pinger (app-level heartbeat) | When modifying system health monitoring |
| `web_server.py` | Flask dashboard: /stream, /gallery, /talk, /status | Entry point for the web UI |
| `alert.py` | Pushover wrapper + cooldown logic | When modifying alert behavior |
| `sensors.py` | HTTP polling of Pi Zero sensor nodes (Phase 2) | When working on sensor integration |
| `prompt_builder.py` | Builds VLM prompt from config + sensor readings | When tuning the AI prompt |
| `dataset.py` | Logging, image saving, label utilities | When touching dataset or logging |
| `config.yaml` | All settings, API keys, feature flags | Source of truth for configuration |
| `go2rtc.yaml` | go2rtc camera + streaming config | When configuring live stream |
| `requirements.txt` | Python dependencies | When setting up or adding deps |

## Setup & Deployment

| File/Folder | Purpose | When to Use |
|-------------|---------|-------------|
| `setup/install.sh` | Full system setup script for Pi | Pi first-boot setup |
| `setup/healthcheck_ping.sh` | OS-level cron heartbeat script (pings system_ping_url every 5 min) | Verifying or reinstalling cron heartbeat |
| `setup/tailscale_setup.sh` | Tailscale VPN install/config | Builder remote access setup |
| `setup/cloudflare_setup.sh` | Cloudflare Tunnel install/config | Mom's browser access setup |
| `setup/systemd/` | systemd service files for monitor, web, go2rtc | When configuring auto-start on Pi |

## Web Dashboard

| File | Purpose | When to Use |
|------|---------|-------------|
| `templates/dashboard.html` | Mom's browser interface | When working on UI layout |
| `static/dashboard.js` | WebSocket for real-time alerts | When working on frontend logic |
| `static/dashboard.css` | Dashboard styles | When working on UI styles |

## Dataset

| Path | Purpose | When to Use |
|------|---------|-------------|
| `dataset/images/` | Saved JPEG frames from monitoring | Dataset review, fine-tuning prep |
| `dataset/log.jsonl` | One JSON line per inference (see PRD §11) | Log analysis, labeling |

## Docs

| File | Purpose | When to Use |
|------|---------|-------------|
| `docs/MOM_GUIDE.md` | How Mom uses dashboard and alerts | Updating end-user instructions |
| `docs/INSTALL_GUIDE.md` | Full setup from scratch | New deployment |
| `docs/SENSOR_SETUP.md` | Phase 2 sensor node setup | When deploying sensor nodes |
| `PRD.md` | Full product requirements, architecture, BOM, roadmap | Architecture decisions, phase planning |

## Task List

| File | Purpose | When to Use |
|------|---------|-------------|
| `todo.taskpaper` | Active task list in TaskPaper format (`@na` = next action, `@done` = complete) | Check at session start; mark tasks `@done` as work is completed |

## context/

| File | Purpose |
|------|---------|
| `conventions.md` | File naming, dataset schema, config patterns, coding conventions |
| `dev-environment.md` | Local dev strategy — Mac/Pi split, mocking, deploy, smoke test |
| `lessons.md` | Running log of lessons learned |
