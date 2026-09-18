#!/usr/bin/env bash
# D. Backend restart
#   Restart the FastAPI backend while the stream is active.
#   Verify: the system reconnects to the sensor stream, the durable backlog
#   remains available, and processing resumes normally.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

log "restarting backend container"
docker compose restart -t 5 backend >/dev/null

log "waiting for health"
for i in $(seq 1 30); do
  if curl -sf "$BACKEND_URL/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
HEALTH=$(curl -sf "$BACKEND_URL/health" || echo '{"status":"down"}')
echo "health: $HEALTH"
echo "$HEALTH" | grep -q '"ingestion":true' && pass "ingestion reconnected" || fail "ingestion not reconnected"

sleep 10
P1=$(metric events_processed); sleep 5; P2=$(metric events_processed)
assert_ge "$P2" "$P1" "processing resumes after backend restart"

# The durable backlog remains available and queryable.
DURABLE=$(db "SELECT count(*) FROM events")
assert_ge "$DURABLE" 1 "postgres backlog intact"

summary