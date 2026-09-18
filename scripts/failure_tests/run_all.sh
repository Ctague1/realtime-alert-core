#!/usr/bin/env bash
# Run the whole failure-test suite against the running compose stack.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOTAL_PASS=0
TOTAL_FAIL=0

for script in "$DIR"/{a_load,b_burst,c_worker_restart,d_backend_restart,e_redis_restart,f_dashboard_disconnect,g_duplicates,h_heartbeat_failure}.sh; do
  echo -e "\n\033[1;35m########## $(basename "$script") ##########\033[0m"
  if bash "$script"; then
    TOTAL_PASS=$((TOTAL_PASS+1))
  else
    TOTAL_FAIL=$((TOTAL_FAIL+1))
  fi
done

echo -e "\n\033[1;34m=== suite: $TOTAL_PASS passed, $TOTAL_FAIL failed ===\033[0m"
[ "$TOTAL_FAIL" -eq 0 ]