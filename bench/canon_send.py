"""Send canonical 802.3 LENGTH frames into one MPF300 port for the interlock
forwarding test. The L/T field is set to the DATA length (<= 1500), so the
interlock's deframe accepts it (not a TYPE frame). DST/SRC are arbitrary — the
interlock FORCES them to 02:..:0X, which is how we prove a captured frame went
THROUGH the bridge rather than leaking around it.

usage: canon_send.py <iface> [count] [length]
"""
import socket, struct, sys

ifn   = sys.argv[1]
count = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
plen  = int(sys.argv[3]) if len(sys.argv) > 3 else 64      # DATA length == L/T field

assert 1 <= plen <= 1500
# distinctive, position-tagged payload so we can confirm content survives intact
base = b"ILOCKFWD" + bytes(range(256))
payload = (base * (plen // len(base) + 1))[:plen]
dst = b"\xde\xad\xbe\xef\x00\x01"     # arbitrary -> interlock forces to 02:..:0X
src = b"\xde\xad\xbe\xef\x00\x02"
frame = dst + src + struct.pack("!H", plen) + payload   # 802.3: DST SRC LEN DATA
if len(frame) < 60:                                      # min frame (NIC adds FCS)
    frame += b"\x00" * (60 - len(frame))

s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
s.bind((ifn, 0))
for _ in range(count):
    s.send(frame)
print("sent %d canonical 802.3 frames (L/T=%d, payload 'ILOCKFWD...') on %s"
      % (count, plen, ifn))
