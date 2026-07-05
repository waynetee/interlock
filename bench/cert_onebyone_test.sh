#!/bin/bash
# ONE-PACKET-AT-A-TIME per-packet-certificate test + parse/verify.
#
# This build emits a certificate for EVERY request and EVERY response. Each cert is
# an HMAC that takes time and CANNOT overlap: two packets too close together put the
# cert path in a bad state. So we send strictly one packet at a time with a large
# gap (default 300 ms) and exercise the two pipelines SEPARATELY (request, then
# response) so a request-cert and a response-cert never collide at the shared egress.
#
# Each phase captures port-0 egress (SRC 02:..:02) to a pcap, then cert_parse.py
# decodes every cert and VERIFIES it: tau == HMAC-SHA256(key=0x..02, m), and the
# overall hash binds one of the known test packets.
#
# usage: cert_onebyone_test.sh [count] [gap_ms]
set -u
A=enxb8fbb3b1f53c   # port 0 (cert egress / prover-frontend side) -- cables swapped
B=enP7s7            # port 1
N=${1:-10}
GAP=${2:-300}
DLEN=32             # test data-packet DATA length (16B header + 16B payload)
SEND=python:3-slim
CAP=nicolaka/netshoot
FPE=/home/claude/fpe

phase() {  # $1=label  $2=send-iface
  rm -f $FPE/ph_$1.pcap
  docker rm -f cph >/dev/null 2>&1
  docker run -d --name cph --network host --cap-add NET_RAW --cap-add NET_ADMIN -v $FPE:/fpe \
    $CAP tcpdump -nn -U -Z root -c 400 -i "$A" -w /fpe/ph_$1.pcap "ether src 02:00:00:00:00:02" >/dev/null 2>&1
  sleep 3
  docker run --rm --network host --cap-add NET_RAW -v $FPE:/fpe \
    $SEND python3 /fpe/cert_send_spaced.py "$2" "$N" "$GAP" $((DLEN-16))
  sleep 2
  docker stop -t 3 cph >/dev/null 2>&1; docker rm -f cph >/dev/null 2>&1
  echo "--- parse/verify phase $1 ---"
  docker run --rm -v $FPE:/fpe $SEND python3 /fpe/cert_parse.py /fpe/ph_$1.pcap $DLEN
}

echo "=== link carrier: enP7s7=$(cat /sys/class/net/$A/carrier 2>/dev/null) enxb8=$(cat /sys/class/net/$B/carrier 2>/dev/null) ==="
echo ""
echo "############ Phase A: $N REQUESTS into port0 ($A) @${GAP}ms -> expect $N request certs ############"
phase A "$A"
echo ""
echo "############ Phase B: $N RESPONSES into port1 ($B) @${GAP}ms -> expect $N response certs ############"
phase B "$B"
echo ""
echo "=== expect each phase: certs == $N, tau valid == $N, overall bound == $N ==="
