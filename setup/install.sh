#!/usr/bin/env bash
# vigil full system setup for Raspberry Pi 5 (Raspberry Pi OS Lite 64-bit)
# Run as root or with sudo from the project root directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_USER="${SUDO_USER:-pi}"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

# --- Config bootstrap -----------------------------------------------------------
if [ ! -f config.yaml ]; then
  cp config.yaml.example config.yaml
  echo "Created config.yaml from config.yaml.example - fill in API keys before running."
fi

# --- Helper: install a systemd service with path/user substitution --------------
install_service() {
  local name="$1"
  local src="$SCRIPT_DIR/systemd/${name}.service"
  local dest="/etc/systemd/system/${name}.service"

  sed \
    -e "s|User=pi|User=${SERVICE_USER}|g" \
    -e "s|Group=pi|Group=${SERVICE_USER}|g" \
    -e "s|/home/pi/eldercare/.venv/bin/python|${VENV_PYTHON}|g" \
    -e "s|/home/pi/eldercare|${PROJECT_DIR}|g" \
    "$src" > "$dest"

  systemctl daemon-reload
  systemctl enable "${name}.service"
  systemctl restart "${name}.service"
  echo "Installed and started ${name}.service"
}

# --- Helper: install a systemd timer (service + timer file) with path substitution ---
install_timer() {
  local name="$1"
  local service_src="$SCRIPT_DIR/systemd/${name}.service"
  local timer_src="$SCRIPT_DIR/systemd/${name}.timer"
  local service_dest="/etc/systemd/system/${name}.service"
  local timer_dest="/etc/systemd/system/${name}.timer"

  sed \
    -e "s|User=pi|User=${SERVICE_USER}|g" \
    -e "s|Group=pi|Group=${SERVICE_USER}|g" \
    -e "s|/home/pi/eldercare/.venv/bin/python|${VENV_PYTHON}|g" \
    -e "s|/home/pi/eldercare|${PROJECT_DIR}|g" \
    "$service_src" > "$service_dest"

  cp "$timer_src" "$timer_dest"

  systemctl daemon-reload
  systemctl enable "${name}.timer"
  systemctl start "${name}.timer"
  echo "Installed and started ${name}.timer"
}

# --- Python venv ----------------------------------------------------------------
if [ ! -f "$VENV_PYTHON" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv "$PROJECT_DIR/.venv"
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi

# --- go2rtc binary --------------------------------------------------------------
if [ ! -x /usr/local/bin/go2rtc ]; then
  echo "Downloading go2rtc ARM64 binary..."
  curl -fsSL -o /usr/local/bin/go2rtc \
    https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_arm64
  chmod +x /usr/local/bin/go2rtc
fi

# --- age encryption tool --------------------------------------------------------
if ! command -v age &>/dev/null; then
  echo "Installing age encryption tool..."
  sudo apt-get install -y age
fi

# --- systemd services -----------------------------------------------------------
install_service go2rtc
install_service web_server
install_service monitor
install_timer archiver
install_timer nas_sync

# --- Healthchecks.io OS-level cron heartbeat ------------------------------------
SYSTEM_PING_URL=$(python3 -c "
import yaml, sys
try:
    c = yaml.safe_load(open('config.yaml'))
    print((c.get('healthchecks') or {}).get('system_ping_url') or '')
except Exception:
    print('')
")

if [ -n "$SYSTEM_PING_URL" ]; then
  PING_SCRIPT="$SCRIPT_DIR/healthcheck_ping.sh"
  CRON_ENTRY="*/5 * * * * HEALTHCHECKS_SYSTEM_URL=${SYSTEM_PING_URL} ${PING_SCRIPT}"
  # Add idempotently: remove any existing entry for healthcheck_ping.sh, then append.
  # Use sudo -u so the entry lands in the service user's crontab, not root's.
  ( sudo -u "$SERVICE_USER" crontab -l 2>/dev/null | grep -v "healthcheck_ping.sh"; echo "$CRON_ENTRY" ) \
    | sudo -u "$SERVICE_USER" crontab -
  echo "Installed cron heartbeat: pings Healthchecks.io every 5 minutes."
else
  echo "healthchecks.system_ping_url not set — skipping cron heartbeat."
fi

echo ""
echo "Setup complete."
echo "Check logs:  journalctl -u grandma-monitor -f"
echo "Dashboard:   http://localhost:8080"
