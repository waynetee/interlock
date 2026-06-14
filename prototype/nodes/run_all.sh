#!/bin/bash
# Launch the three server nodes in the background, then the frontend (interactive).
#   MOCK=1 ./run_all.sh     # no-Llama wiring test (canned compute)
#   ./run_all.sh            # real Llama (compute loads the model, ~1 min)
# To put compute on another host (e.g. through the FPGA): COMPUTE_HOST=10.10.10.2
cd "$(dirname "$0")"
PY="${PY:-python3}"
$PY compute.py   & C=$!
$PY interlock.py & I=$!
$PY verifier.py  & V=$!
trap "kill $C $I $V 2>/dev/null" EXIT
echo "started: compute($C) interlock($I) verifier($V) — frontend retries until they're up"
$PY frontend.py
