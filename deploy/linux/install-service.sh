#!/bin/bash
set -euo pipefail

SERVICE_NAME="agenteum-net"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_BIN="$PROJECT_DIR/.venv/bin"
LOG_DIR="$PROJECT_DIR/logs"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

RUN_USER="${SUDO_USER:-$USER}"
if [ "$RUN_USER" = "root" ]; then
    RUN_USER="agenteum"
    id -u "$RUN_USER" &>/dev/null || useradd --system --no-create-home "$RUN_USER"
fi
RUN_GROUP="$(id -gn "$RUN_USER")"

if [ ! -x "$VENV_BIN/agenteum-net" ]; then
    echo "ERROR: agenteum-net not found in $VENV_BIN. Run 'uv sync' first." >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
chown "$RUN_USER:$RUN_GROUP" "$LOG_DIR"

sed -e "s|%USER%|$RUN_USER|g" \
    -e "s|%GROUP%|$RUN_GROUP|g" \
    -e "s|%PROJECT_DIR%|$PROJECT_DIR|g" \
    -e "s|%VENV_BIN%|$VENV_BIN|g" \
    "$(dirname "$0")/agenteum-net.service" \
    > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

echo "Service '$SERVICE_NAME' installed and started."
echo "Status: systemctl status $SERVICE_NAME"
echo "Logs: journalctl -u $SERVICE_NAME -f"
