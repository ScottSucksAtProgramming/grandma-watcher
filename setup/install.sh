#!/usr/bin/env bash
# grandma-watcher full system setup for Raspberry Pi 5 (Raspberry Pi OS Lite 64-bit)
# Run as root or with sudo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# --- Config bootstrap -----------------------------------------------------------
# Copy config template if config.yaml does not exist.
# Fill in API keys in config.yaml before starting any service.
if [ ! -f config.yaml ]; then
  cp config.yaml.example config.yaml
  echo "Created config.yaml from config.yaml.example - fill in API keys before running."
fi

# --- TODO: remaining setup steps (systemd, go2rtc, apcupsd, etc.) ---------------
echo "Setup complete."
