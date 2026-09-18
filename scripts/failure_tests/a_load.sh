#!/usr/bin/env bash
# A. Sustained baseline load
#   The provided generator runs at RATE=200 (its effective rate is higher due
#   to built-in bursts). Verify: events accepted, processed, no unexpected
#   loss, no persistent processing failures.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

DURATION="${DURATION:-30}"

log "sampling for ${DURATION}s"
R1=$(metric events_received); A1=$(metric events_accepted); P1=$(metric events_processed)
FAIL_BEFORE=$(metric processing_failures)
sleep "$DURATION"
R2=$(metric events_received); A2=$(metric events_accepted); P2=$(metric events_processed)
FAIL_AFTER=$(metric processing_failures)

RATE_MSGS=$((R2 - R1))
ACCEPTED=$((A2 - A1))
PROCESSED=$((P2 - P1))
echo "received +$RATE_MSGS | accepted +$ACCEPTED | processed +$PROCESSED | failures +$((FAIL_AFTER - FAIL_BEFORE))"

assert_ge "$RATE_MSGS" 1 "events arriving"
assert_ge "$ACCEPTED" 1 "events accepted"
assert_ge "$PROCESSED" 1 "events processed"

# No unexpected loss: accepted == received (ingestion rejects nothing valid).
# A small gap is allowed because the two counters are sampled sequentially
# while ~1000 events/sec are in flight (the gap represents events that were
# received but are still in the small bounded ingestion buffer, accepted
# moments later).
TOLERANCE=$(( RATE_MSGS / 50 + 20 ))
if [ "$ACCEPTED" -ge $((RATE_MSGS - TOLERANCE)) ]; then
  pass "no unexpected loss (accepted $ACCEPTED / received $RATE_MSGS, tolerance $TOLERANCE)"
else
  fail "accepted $ACCEPTED vs received $RATE_MSGS"
fi
assert_eq "$FAIL_AFTER" "$FAIL_BEFORE" "zero new processing failures"

summary