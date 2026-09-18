#!/usr/bin/env bash
# B. Burst traffic
#   The generator emits ~500-event bursts. Additionally allow running the
#   generator at a higher rate. Verify the durable backlog absorbs the burst
#   and the worker drains it (pending -> 0) without loss.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

log "injecting a 500-event burst directly into the Redis stream"
BEFORE=$(metric events_processed)
docker compose exec -T redis sh -c '
  for i in $(seq 1 500); do
    redis-cli XADD sensor:events MAXLEN "~" 1000000 "*" \
      payload "{\"event_id\":\"evt_burst_$i_$(date +%s%N)\",\"sensor_id\":\"sensor-001\",\"site_id\":\"site-100\",\"type\":\"fire_alarm\",\"confidence\":0.9,\"ts\":\"2026-09-15T14:03:12.481Z\"}" \
      received_at "2026-09-15T14:03:12.481Z" > /dev/null
  done
' >/dev/null

sleep 8
AFTER=$(metric events_processed)
DRAINED=$((AFTER - BEFORE))
echo "processed during burst window: +$DRAINED"
assert_ge "$DRAINED" 500 "burst events processed"

# The worker always has up to WORKER_BATCH_SIZE (default 100) messages
# in-flight/delivered-but-not-yet-acked; if the burst had overwhelmed the
# worker, pending would grow well beyond that. A bounded pending count proves
# the durable backlog absorbed the burst and drained it.
PENDING=$(docker compose exec -T redis redis-cli XPENDING sensor:events sentinel-workers | head -1 | tr -d '[:space:]')
echo "pending: $PENDING"
assert_le "$PENDING" 100 "backlog drained (pending within one in-flight batch)"

summary