#!/bin/bash
# Control-plane route: Pi -> Spark. The Pi's eth0 is the raw interlock wire (no IP)
# and the shared wireless LAN has client isolation, so the only working path is the
# Spark's outbound ssh to the Pi. Reverse-forward the demo server over it: the Pi
# then reaches the orchestrator at 127.0.0.1:8770.
#
# This is the CONTROL plane only. The prompt and response still cross the certified
# wire; nothing here carries payload.
case "${1:-start}" in
  start)
    ps -eo pid,args | awk '/ssh -N/ && /-R/ {print $1}' | xargs -r kill 2>/dev/null; sleep 1
    nohup ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -R 8770:127.0.0.1:8770 2a-rpi >/tmp/tunnel.log 2>&1 &
    disown
    sleep 5
    if ps -eo args | grep -q "^ssh -N"; then echo "TUNNEL UP"
    else echo "TUNNEL DEAD"; cat /tmp/tunnel.log; fi ;;
  stop) ps -eo pid,args | awk '/ssh -N/ && /-R/ {print $1}' | xargs -r kill 2>/dev/null
        echo "TUNNEL STOPPED" ;;
  test) ssh 2a-rpi curl -s -m 6 -o /dev/null -w 'pi->orchestrator:%{http_code}\n' \
             http://127.0.0.1:8770/ ;;
esac
