#!/bin/bash
# One-command setup for Personal AI Agent.
# Usage: from repo root, run: bash scripts/install.sh
# Or: curl -sSL https://raw.githubusercontent.com/.../install.sh | bash (if you clone first)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "Personal AI Agent — Setup"
echo "  Project: $PROJECT_DIR"
echo ""

# Python 3.10+
if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found. Install Python 3.10 or later."
  exit 1
fi
PYVER=$(python3 -c 'import sys; print(sys.version_info.major, sys.version_info.minor)' 2>/dev/null || true)
echo "  Python:  $(python3 --version)"

# Virtual environment
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "  Creating virtualenv at .venv ..."
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -q -r requirements.txt
echo "  Dependencies installed."

# .env + credentials split
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "  Created .env from .env.example"
else
  echo "  .env already exists; skipping."
fi

mkdir -p "$PROJECT_DIR/credentials"
if [ ! -f "$PROJECT_DIR/credentials/.secrets.env" ]; then
  cp "$PROJECT_DIR/credentials/.secrets.env.example" "$PROJECT_DIR/credentials/.secrets.env"
  echo "  Created credentials/.secrets.env from template"
fi

echo ""
echo "  Add your Anthropic API key to credentials/.secrets.env (required):"
echo "    ANTHROPIC_API_KEY=sk-ant-..."
echo ""
read -p "  Paste your ANTHROPIC_API_KEY (or press Enter to skip): " key
if [ -n "$key" ]; then
  if grep -q "^ANTHROPIC_API_KEY=" "$PROJECT_DIR/credentials/.secrets.env"; then
    sed -i.bak "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$key|" "$PROJECT_DIR/credentials/.secrets.env"
  else
    echo "ANTHROPIC_API_KEY=$key" >> "$PROJECT_DIR/credentials/.secrets.env"
  fi
  echo "  API key saved."
fi

# Data dirs
mkdir -p "$PROJECT_DIR/my_data" "$PROJECT_DIR/data"
echo "  my_data/ and data/ ready."
echo ""
echo "Done. To run:"
echo "  source .venv/bin/activate   # or: . .venv/bin/activate"
echo "  python app.py"
echo "  Then open http://localhost:8000"
echo ""
echo "Optional:"
echo "  python load_documents.py   # index files from my_data/"
echo "  bash scripts/install_daemon.sh   # auto-start at login (macOS)"
echo ""
