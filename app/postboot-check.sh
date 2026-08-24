#!/bin/bash
# Did the demo come back by itself?
#
# Run after a reboot with nothing else touched. It checks the things that are
# separately capable of being down while the others look fine -- a service can be
# active without ever having bound its port, a bound port can serve the shell of a
# page whose bundle is missing, and the whole dashboard can look healthy while the
# backend the proof needs is gone.
#
# Exit 0 only if every REQUIRED check passes. The board and the Pi agent are
# reported but not required: the board is powered separately, and the Pi is a
# different machine that this reboot did not touch.
PORT="${PORT:-80}"
fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
note() { printf '  --    %s\n' "$1"; }

echo "uptime: $(uptime -p)  (booted $(uptime -s))"
echo
echo "orchestrator"
systemctl is-enabled interlock-demo.service >/dev/null 2>&1 \
  && ok "enabled at boot" || bad "NOT enabled at boot"
systemctl is-active interlock-demo.service >/dev/null 2>&1 \
  && ok "active" || bad "not active"

# How long after boot did it start serving? This is the number that says whether
# someone opening the case has to wait, and it is invisible from is-active.
S=$(systemctl show interlock-demo.service -p ActiveEnterTimestampMonotonic --value 2>/dev/null)
[ -n "$S" ] && [ "$S" != "0" ] && note "started $((S/1000000))s after boot"

echo
echo "http on :$PORT"
code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
[ "$code" = "200" ] && ok "/ -> 200" || bad "/ -> ${code:-no answer}"
for p in /lab /favicon.svg; do
  c=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:$PORT$p" 2>/dev/null)
  [ "$c" = "200" ] && ok "$p -> 200" || bad "$p -> ${c:-no answer}"
done
# The shell is served even when the build is missing -- demo_server falls back to
# a 503 with instructions -- so check that the JS bundle is really there.
if curl -s -m 10 "http://127.0.0.1:$PORT/" 2>/dev/null | grep -q '_app/immutable'; then
  ok "dashboard bundle referenced"
else bad "page served but no bundle -- run: cd dashboard && pnpm build"; fi

# Socket.IO is how every value reaches the page; a dashboard that loads and never
# populates looks like a hang rather than a fault.
sio=$(curl -s -m 10 -o /dev/null -w '%{http_code}' \
      "http://127.0.0.1:$PORT/socket.io/?EIO=4&transport=polling" 2>/dev/null)
[ "$sio" = "200" ] && ok "socket.io handshake" || bad "socket.io -> ${sio:-no answer}"

echo
echo "proof backend"
if timeout 4 python3 -c "import socket;socket.create_connection(('127.0.0.1',9917),3)" 2>/dev/null
then ok "ilk_server listening on 9917"
else bad "ilk_server DOWN -- the page works, the proof will not"; fi
docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' ilk_server 2>/dev/null \
  | grep -q "unless-stopped" && ok "container set to restart on boot" \
  || bad "container restart policy is not unless-stopped"

echo
echo "not required by this reboot"
TS=$(docker logs -t --tail 60 ilk_server 2>&1 | grep -a "hits=" | tail -1 | awk '{print $1}')
if [ -n "${TS:-}" ] && AGE=$(( $(date +%s) - $(date -d "$TS" +%s) )) 2>/dev/null \
   && [ "$AGE" -le 40 ]; then note "board LIVE (last sync ${AGE}s ago)"
else note "board quiet -- power-cycle the interlock when you want a real run"; fi
if timeout 12 ssh -o BatchMode=yes -o ConnectTimeout=6 2a-rpi \
     "pgrep -f pi_agent.py >/dev/null" 2>/dev/null
then note "pi agent running (separate machine; survives a Spark reboot)"
else note "pi agent not running -- ./demo_up.sh start"; fi

echo
[ "$fail" = 0 ] && echo "PASS -- the demo came back on its own." \
                || echo "FAIL -- see the lines above."
exit "$fail"
