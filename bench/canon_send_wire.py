"""Send wire.py-format packets wrapped in 802.3 frames to exercise BOTH interlock
cores. Each rid emits an INPUT packet (req core, s_dir=0) and an OUTPUT packet
(rsp core, s_dir=1); each core accepts its matching type and drops the other, so
running this on either NIC feeds the core on that port regardless of mapping.

  input_packet  = [len:4 BE][rid:8 BE][SHA256(key):32][ct]
  output_packet = [len:4 BE][rid:8 BE][ct]

usage: canon_send_wire.py <iface> [count]
"""
import hashlib
import socket
import sys
import time


def H(d):
    return hashlib.sha256(d).digest()


def input_packet(rid, key, ct):
    return len(ct).to_bytes(4, "big") + rid.to_bytes(8, "big") + H(key) + ct


def output_packet(rid, ct):
    return len(ct).to_bytes(4, "big") + rid.to_bytes(8, "big") + ct


def frame(pkt):
    dst = b"\x02\x00\x00\x00\x00\x0a"
    src = b"\x02\x00\x00\x00\x00\x0b"
    f = dst + src + len(pkt).to_bytes(2, "big") + pkt
    return f + b"\x00" * (60 - len(f)) if len(f) < 60 else f


ifn = sys.argv[1]
count = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
key = H(b"k")
ct = b"\xa5" * 8

s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
s.bind((ifn, 0))
for rid in range(1, count + 1):
    s.send(frame(input_packet(rid, key, ct)))
    s.send(frame(output_packet(rid, ct)))
    if rid % 40 == 0:
        time.sleep(0.003)
print("sent %d in + %d out wire-packets on %s" % (count, count, ifn))
