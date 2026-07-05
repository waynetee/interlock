#!/bin/bash
# Bidirectional forwarding test through the MPF300 interlock bridge, via Docker
# (claude has no sudo but is in the docker group). Sends canonical 802.3 LENGTH
# frames into one port and captures (promisc) on the other, FILTERED to the
# interlock's forced DST MACs (02:..:01 / :02) — so every captured packet is, by
# construction, a frame that traversed and was sanitized by the bridge.
#
# usage: canon_fwd.sh [count] [length]
set -u
A=enP7s7
B=enxb8fbb3b1f53c
N=${1:-3000}
PLEN=${2:-64}
FILT='ether dst 02:00:00:00:00:01 or ether dst 02:00:00:00:00:02'
SEND_IMG=python:3-slim
CAP_IMG=nicolaka/netshoot

cap_and_send() {  # $1=send-iface  $2=recv-iface
  local S=$1 R=$2 before after
  before=$(cat /sys/class/net/$R/statistics/rx_packets)
  docker rm -f iltcap >/dev/null 2>&1
  docker run -d --name iltcap --network host --cap-add NET_RAW --cap-add NET_ADMIN \
    $CAP_IMG tcpdump -e -nn -X -c 100 -i "$R" $FILT >/dev/null 2>&1
  sleep 2.5   # container/tcpdump startup
  docker run --rm --network host --cap-add NET_RAW -v /home/claude/fpe:/fpe \
    $SEND_IMG python3 /fpe/canon_send.py "$S" "$N" "$PLEN"
  sleep 2
  docker logs iltcap > /tmp/cap_${R}.txt 2>&1
  docker rm -f iltcap >/dev/null 2>&1
  after=$(cat /sys/class/net/$R/statistics/rx_packets)
  local fwd ilock
  fwd=$(grep -cE '02:00:00:00:00:0[12]' /tmp/cap_${R}.txt)
  ilock=$(grep -c 'ILOCKFWD' /tmp/cap_${R}.txt)
  echo "  [$S -> $R] rx_packets delta=$((after-before)) | sanitized-frames(forced DST)=$fwd | ILOCKFWD-payload=$ilock"
  echo "  --- sample (forced MACs + payload) ---"
  grep -m1 -A2 '02:00:00:00:00:0[12]' /tmp/cap_${R}.txt | head -4 || echo "  (none captured)"
}

echo "=== direction 1: $A -> $B ==="
cap_and_send "$A" "$B"
echo "=== direction 2: $B -> $A ==="
cap_and_send "$B" "$A"
echo "=== forwarding works iff sanitized-frames>0 AND ILOCKFWD-payload>0 on the recv side ==="
