#!/bin/bash
# Installs a daily cron job for encrypted backups at 02:30 local time.
#
# Prerequisite:
#   export BACKUP_PASSPHRASE='your-strong-passphrase'
#   (or put BACKUP_PASSPHRASE in .env)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="$PROJECT_DIR/scripts/backup_encrypted.sh"

if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Error: backup script missing at $SCRIPT_PATH"
  exit 1
fi

LINE="30 2 * * * cd $PROJECT_DIR && /bin/bash $SCRIPT_PATH >> $PROJECT_DIR/logs/backup.log 2>&1"

mkdir -p "$PROJECT_DIR/logs"

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "backup_encrypted.sh" > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "Installed daily backup cron:"
echo "  $LINE"

