#!/bin/bash
# SPACED bidirectional forwarding probe — safe for the per-packet cert build (no
# flood that would overrun the HMAC). Sends a few frames with a gap and counts the
# sanitized (forced-DST) frames that traversed the bridge.
#
# usage: fwd_spaced_test.sh [count] [gap_ms]
set -u
A=enP7s7
B=enxb8fbb3b1f53c
N=${1:-15}
GAP=${2:-20}
SEND=python:3-slim
CAP=nicolaka/netshoot

probe() {  # $1=send $2=recv $3=forced-DST
  local S=$1 R=$2 D=$3
  docker rm -f fcap >/dev/null 2>&1
  docker run -d --name fcap --network host --cap-add NET_RAW --cap-add NET_ADMIN \
    $CAP tcpdump -e -nn -c 80 -i "$R" "ether dst $D" >/dev/null 2>&1
  sleep 2.5
  docker run --rm --network host --cap-add NET_RAW -v /home/claude/fpe:/fpe \
    $SEND python3 /fpe/cert_send_spaced.py "$S" "$N" "$GAP" 16 >/dev/null 2>&1
  sleep 2
  docker logs fcap > /tmp/fwd_${R}.txt 2>&1
  docker rm -f fcap >/dev/null 2>&1
  local n s32 s148
  n=$(grep -c "$D" /tmp/fwd_${R}.txt)
  s32=$(grep -c "length 32" /tmp/fwd_${R}.txt)
  s148=$(grep -c "length 148" /tmp/fwd_${R}.txt)
  echo "  [$S -> $R] DST $D total=$n | fwd(len32)=$s32 | cert(len148)=$s148   (sent $N spaced @${GAP}ms)"
  grep -m1 -A1 "$D" /tmp/fwd_${R}.txt | head -2
}

echo "=== dir1: $A -> $B  (requests -> forced DST ..02 on port1) ==="
probe "$A" "$B" "02:00:00:00:00:02"
echo "=== dir2: $B -> $A  (responses -> forced DST ..01 on port0; certs also here) ==="
probe "$B" "$A" "02:00:00:00:00:01"
