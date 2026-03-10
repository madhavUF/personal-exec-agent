#!/bin/bash
# Encrypted backup script (local-first).
# Backs up:
#   - data/*.db
#   - data/documents.json
#   - vector index path from config (default data/chroma_db)
#
# Usage:
#   BACKUP_PASSPHRASE='strong-passphrase' bash scripts/backup_encrypted.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then
  # shellcheck disable=SC2046
  export $(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env | xargs)
fi

BACKUP_OUTPUT_DIR="${BACKUP_OUTPUT_DIR:-backups}"
PASSPHRASE="${BACKUP_PASSPHRASE:-}"

if [ -z "$PASSPHRASE" ]; then
  echo "Error: BACKUP_PASSPHRASE is required."
  exit 1
fi

mkdir -p "$BACKUP_OUTPUT_DIR"
STAMP="$(date +%Y-%m-%d)"
TMP_TAR="${BACKUP_OUTPUT_DIR}/agent-backup-${STAMP}.tar.gz"
ENC_FILE="${BACKUP_OUTPUT_DIR}/agent-backup-${STAMP}.tar.gz.enc"

# Resolve vector path from config.yaml if present
VECTOR_PATH="data/chroma_db"
if [ -f "config.yaml" ]; then
  FOUND="$(python3 - <<'PY'
import yaml
try:
    with open("config.yaml","r",encoding="utf-8") as f:
        cfg=yaml.safe_load(f) or {}
    p=(cfg.get("vector_db",{}) or {}).get("path","data/chroma_db")
    print(p)
except Exception:
    print("data/chroma_db")
PY
)"
  VECTOR_PATH="${FOUND:-data/chroma_db}"
fi

tar -czf "$TMP_TAR" \
  --ignore-failed-read \
  data/*.db \
  data/documents.json \
  "$VECTOR_PATH"

openssl enc -aes-256-cbc -salt -pbkdf2 \
  -in "$TMP_TAR" \
  -out "$ENC_FILE" \
  -pass "pass:$PASSPHRASE"

rm -f "$TMP_TAR"
echo "Encrypted backup created: $ENC_FILE"

