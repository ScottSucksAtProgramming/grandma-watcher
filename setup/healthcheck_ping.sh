#!/usr/bin/env bash
# OS-level Healthchecks.io heartbeat for grandma-watcher.
#
# Pings the system-level Healthchecks.io check every time it is called.
# Cron calls this every 5 minutes, independent of the Python application.
# If the Pi crashes, loses power, or the OS freezes, these pings stop
# and Healthchecks.io alerts the builder.
#
# Usage (manual test):
#   HEALTHCHECKS_SYSTEM_URL=https://hc-ping.com/<uuid> bash setup/healthcheck_ping.sh
#
# The URL is injected via environment variable from the crontab entry
# written by setup/install.sh.

set -euo pipefail

if [[ -z "${HEALTHCHECKS_SYSTEM_URL:-}" ]]; then
    echo "HEALTHCHECKS_SYSTEM_URL is not set — nothing to ping." >&2
    exit 1
fi

curl -fsS --retry 3 --retry-delay 2 "${HEALTHCHECKS_SYSTEM_URL}" > /dev/null
