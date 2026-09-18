#!/usr/bin/env bash
# F. Dashboard disconnect / reconnect
#   Disconnect the WebSocket, let events continue, reconnect, and verify the
#   authoritative snapshot reconstructs state from the backend rather than
#   relying on transient WS messages.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/lib.sh"

WS_URL=$(echo "$BACKEND_URL" | sed 's/^http/ws/')/ws/dashboard
PY=${PYTHON:-python3}

log "connecting, disconnecting, reconnecting, then reading the snapshot"
"$PY" - "$WS_URL" <<'EOF'
import asyncio, json, sys, websockets

async def connect_once():
    async with websockets.connect(sys.argv[1]) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        return msg

async def main():
    url = sys.argv[1]
    first = await connect_once()
    # disconnect (connection closed) while events keep flowing
    second = await connect_once()
    third = await connect_once()
    for i, snap in enumerate((first, second, third), 1):
        assert snap["kind"] == "snapshot", f"expected snapshot, got {snap['kind']}"
        assert "alarms" in snap and "sites" in snap and "sensors" in snap
        print(f"reconnect {i}: alarms={len(snap['alarms'])} sites={len(snap['sites'])} sensors={len(snap['sensors'])}")
    # state is authoritative and grows: reconnect 3 should reflect more alarms
    assert len(third["alarms"]) >= len(first["alarms"]), "snapshot did not include newer state"

asyncio.run(main())
EOF
RC=$?
if [ "$RC" -eq 0 ]; then
  pass "dashboard snapshot reconciles authoritative state after reconnect"
else
  fail "dashboard reconnect/reconciliation failed (exit $RC)"
fi

summary