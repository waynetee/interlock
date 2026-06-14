#!/bin/bash
# Client-side nodes only (interlock + verifier + frontend) — for the FPGA topology,
# where compute runs on the host and these run in a macvlan container on the USB
# side so their calls to compute cross the FPGA. Point them at the host:
#   COMPUTE_HOST=10.10.10.2 ./run_clients.sh
cd "$(dirname "$0")"
PY="${PY:-python3}"
$PY interlock.py & I=$!
$PY verifier.py  & V=$!
trap "kill $I $V 2>/dev/null" EXIT
echo "started: interlock($I) verifier($V); compute expected at ${COMPUTE_HOST:-127.0.0.1} — frontend retries until reachable"
$PY frontend.py
