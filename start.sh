#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:$PATH"

echo "Starting OClip Backend on http://127.0.0.1:8000 ..."
cd "$ROOT_DIR/backend"
"$ROOT_DIR/backend/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 --reload &
BACK_PID=$!

cleanup() {
  echo "Stopping OClip..."
  kill "$BACK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting OClip Frontend on http://localhost:3000 ..."
cd "$ROOT_DIR/frontend"
npm run dev
