#!/usr/bin/env bash
# Start the local dev stack (generator + worker + backend) against the
# Dockerized Redis (db 0) and PostgreSQL (port 5433) used during development.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"
BACKEND="$ROOT/backend"
export PGPORT=5433 PGDATABASE=sentinel PGUSER=sentinel PGPASSWORD=sentinel
export REDIS_URL=redis://localhost:6379/0

kill_pattern() { pkill -f "$1" 2>/dev/null || true; }

start() {
  local name="$1" pattern="$2" dir="$3"
  shift 3
  kill_pattern "$pattern"
  sleep 0.3
  setsid env -C "$dir" "$@" < /dev/null > "/tmp/sentinel-$name.log" 2>&1 &
  disown
  echo "started $name (pid $!)"
}

case "${1:-all}" in
  generator)
    start generator "scripts/stream.py" "$ROOT" "$VENV" "$ROOT/scripts/stream.py"
    ;;
  worker)
    start worker "app.worker" "$BACKEND" "$VENV" -m app.worker
    ;;
  backend)
    start backend "uvicorn app.main" "$BACKEND" "$VENV" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  all)
    "$0" generator
    "$0" worker
    "$0" backend
    ;;
  *)
    echo "usage: $0 [all|generator|worker|backend]"
    exit 1
    ;;
esac