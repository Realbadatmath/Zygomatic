#!/usr/bin/env bash
# Run the whole API test layer: A (pytest + Flask test_client, in-process) then
# B (Newman, the one live-safe Postman folder). Neither layer starts a pipeline,
# renders, trains, approves, deletes or POSTs to a live service.
#
# Exit code: 0 only if BOTH layers pass. A non-zero exit is normal while an
# open finding is on the board (see README.md "Findings") — read the names of
# the failing tests, not just the code.
#
# Usage:  bash apitests/run_all.sh          (python from PATH)
#         ZYG_PY=/path/to/venv/bin/python bash apitests/run_all.sh
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ZYG_PY:-python}"
cd "$REPO"
mkdir -p apitests/reports

echo "=============================================================="
echo "LAYER A — pytest + Flask test_client (in-process, no server)"
echo "=============================================================="
"$PY" -m pytest -o addopts= -q -p no:cacheprovider tests/api
rc_a=$?
echo "layer A exit: $rc_a"

echo
echo "=============================================================="
echo "LAYER B — Newman, folder 'Health (open, no login)' on 127.0.0.1"
echo "=============================================================="
bash apitests/run_newman.sh
rc_b=$?
echo "layer B exit: $rc_b"

echo
echo "--------------------------------------------------------------"
echo "Reports (JSON written by the tests themselves):"
for f in apitests/reports/get_smoke_dashboard.json \
         apitests/reports/post_dashboard.json \
         apitests/reports/medusa.json \
         apitests/reports/newman_health.json; do
  if [ -f "$f" ]; then echo "  $REPO/$f"; else echo "  $REPO/$f  (MISSING)"; fi
done
echo "Findings (markdown, written by the tests themselves):"
for f in apitests/reports/findings_*.md; do
  [ -e "$f" ] && echo "  $REPO/$f"
done
echo "Operator guide: $REPO/apitests/README.md"
echo "--------------------------------------------------------------"

if [ "$rc_a" -ne 0 ] || [ "$rc_b" -ne 0 ]; then
  echo "RESULT: FAIL  (layer A=$rc_a, layer B=$rc_b)"
  exit 1
fi
echo "RESULT: PASS  (both layers)"
