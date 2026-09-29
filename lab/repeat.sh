#!/usr/bin/env bash
# Repeatability: run the same pytest selection N times and report tests whose outcome flips.
#
#   sudo lab/repeat.sh 3 -m failures
#   sudo lab/repeat.sh 5 -m faults -k link_interruption
set -uo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }
n=${1:?usage: $0 <runs> <pytest args...>}; shift

rm -rf reports/runs && mkdir -p reports/runs
for i in $(seq 1 "$n"); do
  echo "=== run $i/$n: pytest $*"
  .venv/bin/python -m testbed.preflight --clean >/dev/null
  .venv/bin/pytest -q --no-header -p no:warnings "$@" --junitxml="reports/runs/run-$i.xml" \
      --html="reports/runs/run-$i.html" | tail -1
done
.venv/bin/python -m testbed.compare --consistency reports/runs/run-*.xml
