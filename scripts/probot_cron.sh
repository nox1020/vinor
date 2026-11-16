#!/usr/bin/env bash
# 1probot keep-alive for cPanel cron (every 5 minutes is enough):
#   */5 * * * * /bin/bash /home/vinorir/public_html/vinor/scripts/probot_cron.sh >/dev/null 2>&1
# Usage: scripts/probot_cron.sh [ensure|restart|stop|status]   (default: ensure)
# "ensure" is a no-op when the bot is already running or not configured.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${VINOR_VENV_PYTHON:-/home/vinorir/virtualenv/vinor/3.11/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
export INSTANCE_PATH="${INSTANCE_PATH:-$ROOT/instance}"
export VINOR_VENV_PYTHON="$PY"
cd "$ROOT"
exec "$PY" -m probot.run "${1:-ensure}"
