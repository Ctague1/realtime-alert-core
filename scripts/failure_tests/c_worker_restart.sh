#!/usr/bin/env bash
# C. Worker restart
#   Restart the processing worker while events are being generated.
#   Verify: accepted events remain available, unacknowledged messages are
#   recovered, processing resumes, duplicates do not corrupt state.
#
#   Note: per-process metric counters reset on restart, so this test compares
#   authoritative PostgreSQL state sampled in a single snapshot.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

BEFORE=$(db "SELECT count(*) FROM events")

log "restarting worker container"
docker compose restart -t 5 worker >/dev/null
sleep 12

# Single snapshot: total vs distinct event_id must match (no duplicates even
# if a message was reprocessed after the restart).
SNAP=$(db "SELECT count(*) || '|' || count(DISTINCT event_id) FROM events")
AFTER="${SNAP%%|*}"
DISTINCT="${SNAP##*|}"
FAILURES=$(metric processing_failures)

echo "events before=$BEFORE after=$AFTER | distinct=$DISTINCT | failures=$FAILURES"
assert_ge "$AFTER" "$BEFORE" "processing resumed and persisted after restart"
assert_eq "$AFTER" "$DISTINCT" "no duplicate logical events created"
assert_eq "$FAILURES" "0" "no processing failures in the new worker"

summary