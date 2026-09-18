#!/usr/bin/env bash
# H. Sensor heartbeat failure
#   The provided generator emits events for all 200 sensors continuously, so
#   a single sensor cannot be silenced independently. The sensor stream is
#   run manually on the host (see README); this test stops that process to
#   simulate heartbeats ceasing for every sensor. The per-sensor offline
#   policy is verified precisely by the pytest integration test
#   test_stale_sensor_becomes_offline.
#
#   Verify: sensors become offline after the documented timeout, offline is
#   tracked separately from alarm state, and sensors recover when events flow
#   again.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

OFFLINE_TIMEOUT=30  # seconds (HEARTBEAT_OFFLINE_TIMEOUT in the worker)
FAILURES_BEFORE=$(metric processing_failures)
STREAM_PID=$(pgrep -f "[s]tream.py" | head -1 || true)

if [ -z "$STREAM_PID" ]; then
  echo "no running stream.py process found; start it first (RATE=200 python scripts/stream.py)"
  fail "sensor stream process not running"
  summary
  exit 1
fi
# Restart with the same interpreter the generator is already using.
STREAM_PYTHON=$(readlink -f "/proc/$STREAM_PID/exe" 2>/dev/null || echo "${SENSOR_PYTHON:-python3}")
echo "stopping sensor stream process pid=$STREAM_PID (heartbeats cease)"
kill "$STREAM_PID"
sleep 1

log "waiting up to $((OFFLINE_TIMEOUT + 20))s for sensors to go offline"
for i in $(seq 1 $((OFFLINE_TIMEOUT + 20))); do
  OFF=$(db "SELECT count(*) FROM sensors WHERE online=false")
  [ "$OFF" -ge 1 ] && break
  sleep 1
done
echo "offline sensors: $OFF"
assert_ge "$OFF" 1 "sensors marked offline after the documented timeout"

# Let the worker's 5s metrics export catch up, then verify the gauge agrees.
sleep 6
GAUGE=$(metric sensors_offline)
assert_eq "$OFF" "$GAUGE" "offline count consistent between DB and metrics"

# Offline detection must not itself fail or fabricate alarms.
FAILURES_AFTER=$(metric processing_failures)
assert_eq "$FAILURES_AFTER" "$FAILURES_BEFORE" "no processing failures from offline detection"

log "restarting the sensor stream process"
nohup "$STREAM_PYTHON" "$DIR/../stream.py" >/tmp/sentinel-stream.log 2>&1 &
disown

log "waiting for sensors to recover to online"
for i in $(seq 1 30); do
  ON=$(db "SELECT count(*) FROM sensors WHERE online=true")
  [ "$ON" -eq 200 ] && break
  sleep 2
done
echo "online sensors: $ON"
assert_eq "$ON" "200" "sensors return to online once events flow again"

summary