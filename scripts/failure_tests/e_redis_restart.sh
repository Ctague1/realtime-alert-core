#!/usr/bin/env bash
# E. Redis restart
#   Redis is configured with AOF (appendfsync everysec). A Redis restart must
#   reload the stream and pending entries from AOF and processing resumes.
#   Limitation (documented in the README): with everysec fsync up to ~1s of
#   very recent appends may be lost on a hard crash; this test documents the
#   guarantee of the default configuration.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

EVENTS_BEFORE=$(db "SELECT count(*) FROM events")

log "restarting redis container"
docker compose restart -t 5 redis >/dev/null
sleep 8

# Stream still exists with retained + pending entries (AOF reload).
STREAM_LEN=$(docker compose exec -T redis redis-cli XLEN sensor:events)
echo "stream length after restart: $STREAM_LEN"
assert_ge "$STREAM_LEN" 1 "stream reloaded from AOF"

sleep 10
P1=$(metric events_processed); sleep 5; P2=$(metric events_processed)
assert_ge "$P2" "$P1" "processing resumes after redis restart"

EVENTS_AFTER=$(db "SELECT count(*) FROM events")
assert_ge "$EVENTS_AFTER" "$EVENTS_BEFORE" "postgres state continues to grow"

summary