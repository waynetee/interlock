#!/bin/bash
# Install the demo orchestrator as a boot service on port 80.
#
#   sudo ./install-service.sh          install, enable, start
#   sudo ./install-service.sh remove   stop, disable, delete
#
# WHY THIS IS A SCRIPT AND NOT A README LINE. Three of the steps below are easy
# to get subtly wrong by hand -- the capability that lets a non-root process bind
# port 80, the two hardening options that must NOT be set, and the fact that the
# unit has to be validated before it is enabled or the machine reboots into a
# demo that does not come up. Doing it once, here, is cheaper than doing it from
# memory in a hotel room the night before.
set -euo pipefail

UNIT=interlock-demo.service
SRC="$(cd "$(dirname "$0")" && pwd)/$UNIT"
DEST=/etc/systemd/system/$UNIT
PORT=80

if [ "$(id -u)" -ne 0 ]; then
  echo "needs root: sudo $0 ${1:-}" >&2; exit 1
fi

if [ "${1:-install}" = "remove" ]; then
  systemctl disable --now "$UNIT" 2>/dev/null || true
  rm -f "$DEST"
  systemctl daemon-reload
  echo "removed $UNIT"
  exit 0
fi

[ -f "$SRC" ] || { echo "missing $SRC" >&2; exit 1; }

# Anything already holding port 80 will make the service fail to bind, and it
# will do so five seconds after this script has cheerfully reported success.
# Find out now instead.
if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
  echo "something is already listening on port $PORT:" >&2
  ss -ltnp "sport = :$PORT" 2>/dev/null >&2
  echo "stop it first, or the service will not bind." >&2
  exit 1
fi

# A hand-started copy from demo_up.sh would hold the old port and answer requests
# that look like they came from the service. Clear it out.
pkill -f "python -u demo_server\.py" 2>/dev/null || true
sleep 1

install -m 644 -o root -g root "$SRC" "$DEST"
systemd-analyze verify "$DEST" || {
  echo "unit did not verify -- not enabling it" >&2; rm -f "$DEST"; exit 1; }

systemctl daemon-reload
systemctl enable "$UNIT"
systemctl restart "$UNIT"

# Starting is not the same as serving: the orchestrator hashes 2.2 GB of weights
# before it listens, so a check that runs immediately always fails. Wait for the
# socket, then confirm the page actually comes back.
echo -n "waiting for port $PORT "
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
    echo
    echo "$UNIT is up and serving on port $PORT"
    systemctl is-enabled "$UNIT" | sed 's/^/  enabled: /'
    exit 0
  fi
  echo -n .
  sleep 2
done

echo
echo "did not answer on port $PORT within 120s. Last log lines:" >&2
journalctl -u "$UNIT" -n 20 --no-pager >&2
exit 1
