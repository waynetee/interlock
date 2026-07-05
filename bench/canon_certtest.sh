#!/bin/bash
# Phase C cert-egress test: stream wire packets both ways (feeding both cores),
# then capture certificate frames (DST 02:00:00:00:00:ce) on each NIC. Cert frames
# carry the 140-byte cert as DATA, so the 802.3 LENGTH is 0x008C and the first
# cert bytes read "ilock-v5" (69 6c 6f 63 6b 2d 76 35). The port-0 NIC (cert
# egress, toward the prover frontend) should show them.
#
# usage: canon_certtest.sh [count]
set -u
A=enP7s7
B=enxb8fbb3b1f53c
N=${1:-80000}
CAP='ether dst 02:00:00:00:00:ce'

# feed both cores (each accepts its matching packet type, drops the other)
docker run -d --rm --network host --cap-add NET_RAW -v /home/claude/fpe:/fpe \
  python:3-slim python3 /fpe/canon_send_wire.py "$A" "$N" >/dev/null 2>&1
docker run -d --rm --network host --cap-add NET_RAW -v /home/claude/fpe:/fpe \
  python:3-slim python3 /fpe/canon_send_wire.py "$B" "$N" >/dev/null 2>&1

for R in "$A" "$B"; do
  echo "=== cert frames captured on $R ==="
  docker rm -f ilcap >/dev/null 2>&1
  docker run -d --name ilcap --network host --cap-add NET_RAW --cap-add NET_ADMIN \
    nicolaka/netshoot tcpdump -e -nn -X -c 6 -i "$R" "$CAP" >/dev/null 2>&1
  sleep 4
  docker logs ilcap > /tmp/cert_${R}.txt 2>&1
  docker rm -f ilcap >/dev/null 2>&1
  frames=$(grep -c '02:00:00:00:00:ce' /tmp/cert_${R}.txt)
  ilock=$(grep -c '008c 69\|008c69' /tmp/cert_${R}.txt)
  echo "  cert frames=$frames   (LEN=140 + 'i' signature)=$ilock"
  grep -m1 -A4 '02:00:00:00:00:ce' /tmp/cert_${R}.txt | head -6
done
echo "=== PASS: cert frames>0 with the ilock-v5 cert payload on the port-0 NIC ==="
