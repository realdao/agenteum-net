#!/bin/bash
set -euo pipefail

SERVICE_NAME="agenteum-net"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "$SERVICE_FILE"
systemctl daemon-reload

echo "Service '$SERVICE_NAME' removed."
