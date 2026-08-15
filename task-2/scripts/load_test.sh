#!/usr/bin/env bash
# Simulates a shift-change traffic spike against the deployed CareThread
# Lambda: a burst of concurrent /flag requests arriving at once, the
# realistic case a hospital's care-coordination tool sees at shift
# handoff, every outgoing nurse's patients get reviewed within a few
# minutes of each other, not spread evenly through the day. Real Lambda
# handles this by running multiple concurrent execution environments,
# no HPA/replica count to configure, the actual point of "confirm
# Lambda autoscaling handles a spike" rather than build one.
#
# Usage:
#   eval $(floci env)
#   ./task-2/scripts/load_test.sh <function-url> [requests] [concurrency]
set -euo pipefail

FUNCTION_URL="${1:?Usage: load_test.sh <function-url> [requests] [concurrency]}"
REQUESTS="${2:-200}"
CONCURRENCY="${3:-50}"

PATIENT_FILE="$(dirname "$0")/../../task-1/data/golden_patients/d15b23ed-02d5-3e28-efbd-2604425317c5.json"
PAYLOAD_FILE="$(mktemp)"
python3 -c "
import json
bundle = json.load(open('$PATIENT_FILE'))
print(json.dumps({'bundle': bundle, 'as_of': '2026-08-15'}))
" > "$PAYLOAD_FILE"

echo "Firing $REQUESTS requests at concurrency $CONCURRENCY against ${FUNCTION_URL}flag ..."
hey -n "$REQUESTS" -c "$CONCURRENCY" -m POST \
  -H "Content-Type: application/json" \
  -D "$PAYLOAD_FILE" \
  "${FUNCTION_URL}flag"

rm -f "$PAYLOAD_FILE"
