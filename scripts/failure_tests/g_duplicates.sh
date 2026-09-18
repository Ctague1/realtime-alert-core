#!/usr/bin/env bash
# G. Duplicate events
#   Deliver the same event_id multiple times through the stream and verify
#   processing stays idempotent (a single event + single alarm in Postgres).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

EVENT_ID="evt_dup_$(date +%s)"
PAYLOAD="{\"event_id\":\"$EVENT_ID\",\"sensor_id\":\"sensor-150\",\"site_id\":\"site-125\",\"type\":\"door_forced\",\"confidence\":0.8,\"ts\":\"2026-09-15T14:03:12.481Z\"}"

log "publishing the same event_id 3 times"
for i in 1 2 3; do
  docker compose exec -T redis redis-cli XADD sensor:events "*" payload "$PAYLOAD" received_at "2026-09-15T14:03:12.481Z" >/dev/null
done

log "waiting for the duplicate event to be processed (poll up to 30s)"
EVENTS=0
for i in $(seq 1 30); do
  EVENTS=$(db "SELECT count(*) FROM events WHERE event_id='$EVENT_ID'")
  [ "$EVENTS" -ge 1 ] && break
  sleep 1
done
ALARMS=$(db "SELECT count(*) FROM alarms WHERE event_id='$EVENT_ID'")
DUPS=$(metric duplicates_detected)

echo "events rows=$EVENTS alarms rows=$ALARMS duplicates_detected=$DUPS"
assert_eq "$EVENTS" 1 "single event row despite 3 deliveries"
assert_eq "$ALARMS" 1 "single alarm row despite 3 deliveries"

summary