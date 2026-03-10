#!/usr/bin/env bash
# Start the always-on money-earning orchestrator.
#
# Usage:
#   ./scripts/start_money_agent.sh          # one tick
#   ./scripts/start_money_agent.sh --loop  # every 30 min
#   ./scripts/start_money_agent.sh --loop 15 # every 15 min

set -e
cd "$(dirname "$0")/.."

# Activate venv if present
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Ensure config exists
mkdir -p config
if [ ! -f "config/money_instructions.yaml" ]; then
  echo "Creating config/money_instructions.yaml from example..."
  cp config/money_instructions.yaml.example config/money_instructions.yaml
  echo "Edit config/money_instructions.yaml with your objectives, then run again."
fi

python -m src.money_agent.orchestrator "$@"
