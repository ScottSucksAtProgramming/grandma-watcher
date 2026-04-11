#!/usr/bin/env bash
# Install cloudflared and configure the Cloudflare Tunnel from config.yaml.
# Run as root (or with sudo) from the project root directory.
# The tunnel token must already be set in config.yaml before running this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="/etc/grandma-watcher/cloudflare.env"
SERVICE_SRC="$SCRIPT_DIR/systemd/cloudflared.service"
SERVICE_DEST="/etc/systemd/system/cloudflared.service"
CLOUDFLARED_BIN="/usr/local/bin/cloudflared"

cd "$PROJECT_DIR"

# --- 1. Extract tunnel token from config.yaml -----------------------------------
if [ ! -f config.yaml ]; then
  echo "ERROR: config.yaml not found. Copy config.yaml.example and fill in your token."
  exit 1
fi

TOKEN=$(python3 -c "
import yaml, sys
cfg = yaml.safe_load(open('config.yaml'))
token = (cfg.get('cloudflare') or {}).get('tunnel_token', '')
if not token:
    print('ERROR: cloudflare.tunnel_token is empty in config.yaml', file=sys.stderr)
    sys.exit(1)
print(token)
")

echo "Tunnel token found."

# --- 2. Install cloudflared binary (ARM64 .deb) ---------------------------------
if command -v cloudflared &>/dev/null; then
  echo "cloudflared already installed: $(cloudflared --version)"
else
  echo "Downloading cloudflared ARM64 package..."
  DEB_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
  TMP_DEB="$(mktemp /tmp/cloudflared-XXXX.deb)"
  curl -fsSL --output "$TMP_DEB" "$DEB_URL"
  dpkg -i "$TMP_DEB"
  rm -f "$TMP_DEB"
  echo "cloudflared installed: $(cloudflared --version)"
fi

# Verify binary is at the expected path (deb installs to /usr/local/bin)
if [ ! -x "$CLOUDFLARED_BIN" ]; then
  # Some deb versions install to /usr/bin — symlink if needed
  ACTUAL_BIN="$(command -v cloudflared)"
  if [ "$ACTUAL_BIN" != "$CLOUDFLARED_BIN" ]; then
    ln -sf "$ACTUAL_BIN" "$CLOUDFLARED_BIN"
    echo "Symlinked $ACTUAL_BIN -> $CLOUDFLARED_BIN"
  fi
fi

# --- 3. Write tunnel token to EnvironmentFile ------------------------------------
mkdir -p /etc/grandma-watcher
printf 'CLOUDFLARE_TUNNEL_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "Wrote tunnel token to $ENV_FILE (mode 600)."

# --- 4. Install and enable systemd service ----------------------------------------
cp "$SERVICE_SRC" "$SERVICE_DEST"
systemctl daemon-reload
systemctl enable cloudflared.service
systemctl restart cloudflared.service

echo ""
echo "Cloudflare Tunnel service started."
echo "Check status:  journalctl -u cloudflared -f"
echo "Verify tunnel: cloudflared tunnel info"
