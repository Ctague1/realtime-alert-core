#!/usr/bin/env bash
# Shared helpers for the failure-test suite.
# Assumes the compose stack is running with the sensor stream running manually
# on the host (see README):
#   docker compose up -d --build        # then: RATE=200 python scripts/stream.py
#
# Note: the optional containerized generator (docker compose --profile sensor
# up) is NOT used by this suite because test h_heartbeat_failure must stop and
# restart the generator process.

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
COMPOSE="docker compose"
PG_USER="sentinel"
PG_DB="sentinel"

PASS_COUNT=0
FAIL_COUNT=0

log()  { echo -e "\n\033[1;34m== $* ==\033[0m"; }
pass() { echo -e "\033[1;32mPASS\033[0m  $*"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo -e "\033[1;31mFAIL\033[0m  $*"; FAIL_COUNT=$((FAIL_COUNT+1)); }

metric() { # metric <name> -> value
  curl -sf "$BACKEND_URL/metrics" | python3 -c "
import json,sys
d=json.load(sys.stdin)
name='$1'
if name in d['counters']: print(d['counters'][name])
elif name in d['gauges']: print(d['gauges'][name])
else:
    for k,v in d['latency_ms'].items():
        if k==name and v.get('samples'): print(v.get('p50') or 0); break
"
}

db() { # db <sql> -> psql output
  docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -tAc "$1" 2>/dev/null
}

assert_ge() { # assert_ge <actual> <expected> <label>
  local a="$1" e="$2" label="$3"
  if [ "$(echo "$a" | tr -d ' ')" -ge "$e" ] 2>/dev/null; then
    pass "$label ($a >= $e)"
  else
    fail "$label (got $a, want >= $e)"
  fi
}

assert_eq() {
  local a="$1" e="$2" label="$3"
  if [ "$a" = "$e" ]; then
    pass "$label ($a)"
  else
    fail "$label (got $a, want $e)"
  fi
}

assert_le() {
  local a="$1" e="$2" label="$3"
  if [ "$a" -le "$e" ] 2>/dev/null; then
    pass "$label ($a <= $e)"
  else
    fail "$label (got $a, want <= $e)"
  fi
}

summary() {
  echo -e "\n\033[1;34m== results: $PASS_COUNT passed, $FAIL_COUNT failed ==\033[0m"
  [ "$FAIL_COUNT" -eq 0 ]
}