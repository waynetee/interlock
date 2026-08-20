#!/usr/bin/env bash
# Bring the whole interlock stack up after a reboot / board power cycle.
#
# This exists because the working invocations were NOT written down anywhere and
# had to be reconstructed from module docstrings after the last reboot.
#
# Order matters: the GPU back-end must answer before the wire half starts, or the
# wire half comes up warning that requests will fail.
#
#   ./bringup.sh            # backend + wire half
#   ./bringup.sh --watch    # also start the board-uptime watcher (see below)
#
# The board stops emitting its 1 kHz sync stream after ~4 hours (measured:
# 3h59m53s, idle, PHY link still up). That looks like a timer, not a fault --
# see bench/uptime_watch.py. --watch records the next lifetime cleanly.
set -euo pipefail

# Both repos locate each other relatively: VerInf is expected as a sibling
# checkout of the interlock repo. Override either with the environment.
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERINF="${VERINF:-$(cd "$APP/../.." && pwd)/VerInf}"
IFACE=${IFACE:-enP7s7}
LOGDIR=${LOGDIR:-/tmp/interlock-logs}
# MODEL_DIR picks the model for BOTH halves: model_backend.py generates with it
# and pins the prover's VERINF_MODEL to match.
#
# TinyLlama-1.1B-Chat is the demo model. Sense-checked on five prompts it
# answers 5/5 correctly ("4", "2, 3, and 5", "William Shakespeare"); llama-160m
# answered 1/5 -- it only knows the memorised "capital of France" and otherwise
# emits nonsense, so it cannot survive an unrehearsed question.
#
# It is also FASTER than llama-3.2-1b despite having more layers (22 vs 16):
#   TinyLlama-1.1B-Chat   102 s @ tq=10   263 s @ tq=80
#   llama-3.2-1b          122 s @ tq=10   357 s @ tq=80
# because proof cost tracks VOCABULARY and DEPTH, not parameter count -- the LM
# head is d x V, and 32000 vs 128256 makes it 4x cheaper. It also stops at 8
# tokens instead of padding to 24, shrinking SEQ.
#
# Any replacement must be LlamaForCausalLM with hidden_act=silu: the prover has
# a SiluClaim and no GELU equivalent, so Gemma (GeGLU), Qwen2 (QKV bias) and
# Phi need new claim types on BOTH the Python and Rust sides.
MODEL_DIR=${MODEL_DIR:-$VERINF/models/TinyLlama-1.1B-Chat-v1.0}
mkdir -p "$LOGDIR"

echo "== 1/3  GPU back-end (host venv, needs the CUDA install) =="
# Liveness is the PORT, not a process-name match. `pgrep -f model_backend.py`
# matches ANY command line containing that string -- including the shell that
# invokes this script, and any ssh command that mentions it -- so it reported
# "already running" when nothing was, and the wire half then came up talking to
# a backend that did not exist. The socket cannot lie.
if timeout 3 python3 -c "import socket;socket.create_connection(('127.0.0.1',9917),2)" 2>/dev/null; then
    echo "   already running"
else
    cd "$APP"
    PATH="$VERINF/venv/bin:$PATH" \
    VERINF="$VERINF" \
    MODEL_DIR="$MODEL_DIR" \
    PRELOAD_MODEL=1 \
    nohup "$VERINF/venv/bin/python" -u model_backend.py \
        > "$LOGDIR/backend.log" 2>&1 &
    echo "   started -> $LOGDIR/backend.log"
fi

echo "   waiting for 127.0.0.1:9917 (model load takes ~30 s) ..."
for _ in $(seq 1 90); do
    if python3 -c "import socket;socket.create_connection(('127.0.0.1',9917),1).close()" \
        2>/dev/null; then echo "   back-end up"; break; fi
    sleep 2
done

echo "== 2/3  wire half (container: this host has no sudo, and canon_tx needs"
echo "        CAP_NET_RAW + NET_ADMIN for promiscuous mode and SYS_NICE for RT) =="
# CHALLENGE_TQ = opened Ligero columns, the proof soundness knob. Proof wall time
# is linear in it: T ~= 137 s + 2.95 s * tq (measured on llama-3.2-1b, 12-token
# request / 24-token response). So 80 -> 373 s, 10 -> 167 s. About 137 s of that
# is a floor no tq setting can touch. That floor is NOT weight commitment --
# weights live in a persistent block committed once across proofs (Variable
# .persistent). It is the depth-independent claims (embedding + LM head), model
# load, and the ~13 s JSON proof dump. Shortening the response is NOT a useful
# speed lever -- cutting 24 -> 8 response tokens saved only 10%, and it changes
# U (U is summed over response positions).
# Default 10 is the grade VerInf's own quickstart gate uses; keeps demos ~2.8 min.
# Production soundness is 80:   CHALLENGE_TQ=80 ./bringup.sh
docker rm -f ilk_server >/dev/null 2>&1 || true
# Two extra read-only mounts for the wire crypto:
#   /app/ref  the prover's reference AES (prover/ref/token_recorder.py). MOUNTED,
#             not copied: the wire cipher and the cipher the ZK circuit proves
#             must be the same bytes, and a second copy in this directory would
#             be free to drift from the one the gadget is composed against.
#   /psk      the pre-shared secret both ends derive per-request keys from. It
#             never crosses the cable; only the 16-byte nonce does.
docker run -d --name ilk_server --network host \
    --cap-add NET_RAW --cap-add NET_ADMIN --cap-add SYS_NICE \
    -v "$APP":/app \
    -v "$VERINF/prover/ref":/app/ref:ro \
    -v "$HOME/.interlock":/psk:ro \
    -e ILK_PSK_FILE=/psk/psk \
    -e MAX_NEW_TOKENS=24 -e CHALLENGE_TQ="${CHALLENGE_TQ:-10}" \
    python:3-slim python3 -u /app/model_server.py "$IFACE" >/dev/null
sleep 6
docker logs ilk_server 2>&1 | head -8

if ! docker logs ilk_server 2>&1 | grep -q "locked: bucket="; then
    echo
    echo "   !! no bucket lock -- the board is not emitting sync."
    echo "      Power-cycle the interlock (a reflash alone does not restart it)."
    exit 1
fi

echo "== 3/3  ready =="
echo "   client (on the Pi, tokenize on this host and pass --hex):"
echo "     ssh 2a-rpi 'cd ~/fpe && sudo ./venv/bin/python -u infcli.py \\"
echo "        --iface eth0 --wait-ms 30000 send --hex <HEX>'"
echo "     ssh 2a-rpi 'cd ~/fpe && sudo ./venv/bin/python -u infcli.py \\"
echo "        --iface eth0 --challenge-timeout 2400 challenge <rid>'"

if [ "${1:-}" = "--watch" ]; then
    echo
    echo "== board-uptime watcher (passive; never transmits) =="
    ssh 2a-rpi "nohup sudo python3 ~/fpe/uptime_watch.py eth0 \
        ~/interlock_uptime.log > /dev/null 2>&1 &" || true
    echo "   running on the Pi -> ~/interlock_uptime.log"
    echo "   on stop it records the board's exact lifetime off the bucket counter"
fi
