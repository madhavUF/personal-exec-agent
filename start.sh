#!/bin/bash
# Starts the FastAPI web server and Telegram bot together.
# Both run as background processes; this script waits and forwards signals.

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PYTHON=$(which python3)
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

echo "Starting Personal AI Agent..."

# Start FastAPI server
"$PYTHON" app.py >> "$LOG_DIR/server.log" 2>&1 &
SERVER_PID=$!
echo "  Web server  PID=$SERVER_PID  → http://localhost:8000"

# Give the server a moment to bind
sleep 1

# Start Telegram bot
"$PYTHON" -m src.telegram_bot >> "$LOG_DIR/telegram.log" 2>&1 &
BOT_PID=$!
echo "  Telegram bot PID=$BOT_PID"

echo "Both running. Logs in $LOG_DIR/"
echo "Press Ctrl+C to stop."

# Forward Ctrl+C to both child processes
trap "echo 'Stopping...'; kill $SERVER_PID $BOT_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# Wait for either process to exit
wait $SERVER_PID $BOT_PID
