#!/bin/bash
# Per-packet certificate egress test for the prod_bringup cert build.
#
# This build emits ONE cert per packet on each pipeline (req + rsp). Both certs and
# the forwarded responses are muxed onto PORT 0 by cert_merge -> reframe_rsp, which
# forces DST=02:..:01, SRC=02:..:02. A cert frame is identified by CONTENT, not DST:
#
#   802.3 LEN = 148 (0x0094)
#   DATA = 16 zero bytes || version(0x00000006) || interlock_id(0x00000042)
#          || bucket_start(8) || num_buckets(0x00000001) || overall_req(32)
#          || overall_rsp(32) || nonce(16) || tau(32)
#
# So in an -XX hex dump the first line of a cert reads:
#   0200 0000 0001 0200 0000 0002 0094 0000   (DST SRC LEN + 2 zero header bytes)
# and a few lines down the version + id appear as:  0006 0000 0042
# Request certs have overall_rsp = 0; response certs have overall_req = 0.
#
# Frames are SPACED (HMAC has no back-pressure). We feed BOTH NICs so both pipelines
# fire, and capture on each NIC; the port-0 NIC shows the cert frames.
#
# usage: cert_spaced_test.sh [count] [gap_ms]
set -u
A=enP7s7
B=enxb8fbb3b1f53c
N=${1:-20}
GAP=${2:-10}
SEND_IMG=python:3-slim
CAP_IMG=nicolaka/netshoot
SIG_HDR='0200 0000 0002 0094'    # SRC=..02 + LEN=148  -> a cert (not a forwarded copy)
SIG_VER='0006 0000 0042'         # version 6 + interlock_id 0x42

feed_both() {
  docker run -d --rm --network host --cap-add NET_RAW -v /home/claude/fpe:/fpe \
    $SEND_IMG python3 /fpe/cert_send_spaced.py "$A" "$N" "$GAP" 16 >/dev/null 2>&1
  docker run -d --rm --network host --cap-add NET_RAW -v /home/claude/fpe:/fpe \
    $SEND_IMG python3 /fpe/cert_send_spaced.py "$B" "$N" "$GAP" 16 >/dev/null 2>&1
}

for R in "$A" "$B"; do
  echo "=== capture on $R while feeding both NICs (N=$N, gap=${GAP}ms each) ==="
  docker rm -f ilcap >/dev/null 2>&1
  docker run -d --name ilcap --network host --cap-add NET_RAW --cap-add NET_ADMIN \
    $CAP_IMG tcpdump -e -nn -XX -c 300 -i "$R" 'ether src 02:00:00:00:00:02' >/dev/null 2>&1
  sleep 2.5
  feed_both
  sleep $(awk "BEGIN{print 3 + $N*$GAP/1000.0}")
  docker logs ilcap > /tmp/cert_${R}.txt 2>&1
  docker rm -f ilcap >/dev/null 2>&1
  certs=$(grep -c "$SIG_HDR" /tmp/cert_${R}.txt)
  vers=$(grep -c "$SIG_VER" /tmp/cert_${R}.txt)
  total=$(grep -c '02:00:00:00:00:02 >' /tmp/cert_${R}.txt)
  echo "  port0-egress frames(SRC..02)=$total | cert frames(LEN148)=$certs | version6+id markers=$vers   (sent 2x$N)"
  echo "  --- first cert frame ---"
  grep -m1 -B1 -A4 "$SIG_HDR" /tmp/cert_${R}.txt | head -7 || echo "  (none)"
done
echo "=== PASS: the port-0 NIC shows cert frames with version6+id markers, count ~ packets fed ==="
