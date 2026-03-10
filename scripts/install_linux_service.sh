#!/bin/bash
# Install systemd service for always-on Personal AI Agent (Linux).
# Run on your Lenovo: bash scripts/install_linux_service.sh
#
# Requires: Python 3.10+, project set up (bash scripts/install.sh)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="personal-ai-agent"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Check if running as root for systemctl
if [ "$(id -u)" -ne 0 ]; then
  echo "This script needs sudo to install the systemd service."
  echo "Run: sudo bash scripts/install_linux_service.sh"
  exit 1
fi

# Use venv python if available
PYTHON="$PROJECT_DIR/.venv/bin/python3"
if [ ! -f "$PYTHON" ]; then
  PYTHON="$(which python3)"
fi

# Check required files
if [ ! -f "$PROJECT_DIR/credentials/.secrets.env" ]; then
  echo "Warning: credentials/.secrets.env not found. Create it with your API keys."
fi

echo "Installing Personal AI Agent systemd service..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $PYTHON"

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Personal AI Agent (web + Telegram)
After=network.target

[Service]
Type=simple
User=$(logname 2>/dev/null || echo "$SUDO_USER")
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON $PROJECT_DIR/app.py
Restart=always
RestartSec=10
Environment="PATH=$PROJECT_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"

# Load .env (required) and credentials (create if missing)
EnvironmentFile=-$PROJECT_DIR/.env
EnvironmentFile=-$PROJECT_DIR/credentials/.secrets.env

# Logs
StandardOutput=append:$PROJECT_DIR/logs/systemd.log
StandardError=append:$PROJECT_DIR/logs/systemd.log

[Install]
WantedBy=multi-user.target
EOF

# Second service for Telegram bot (runs alongside)
BOT_UNIT="/etc/systemd/system/${SERVICE_NAME}-telegram.service"
cat > "$BOT_UNIT" <<EOF
[Unit]
Description=Personal AI Agent - Telegram Bot
After=network.target ${SERVICE_NAME}.service

[Service]
Type=simple
User=$(logname 2>/dev/null || echo "$SUDO_USER")
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON -m src.telegram_bot
Restart=always
RestartSec=10
Environment="PATH=$PROJECT_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=-$PROJECT_DIR/.env
EnvironmentFile=-$PROJECT_DIR/credentials/.secrets.env
StandardOutput=append:$PROJECT_DIR/logs/telegram.log
StandardError=append:$PROJECT_DIR/logs/telegram.log

[Install]
WantedBy=multi-user.target
EOF

mkdir -p "$PROJECT_DIR/logs"
chown "$(logname 2>/dev/null || echo "$SUDO_USER"):" "$PROJECT_DIR/logs" 2>/dev/null || true

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" "${SERVICE_NAME}-telegram"
systemctl start "$SERVICE_NAME" "${SERVICE_NAME}-telegram"

echo ""
echo "Done. Services installed and started."
echo ""
echo "  Web dashboard:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):8000"
echo "  Telegram:      Bot will respond when you message it"
echo ""
echo "Commands:"
echo "  sudo systemctl status $SERVICE_NAME          # check web server"
echo "  sudo systemctl status ${SERVICE_NAME}-telegram  # check Telegram bot"
echo "  sudo systemctl restart $SERVICE_NAME         # restart both"
echo "  sudo journalctl -u $SERVICE_NAME -f          # follow logs"
echo ""
