"""Shared helpers for the node-per-process prototype.

Each node (compute / interlock / frontend / verifier) is its own process and
talks to the others over TCP with length-prefixed JSON. Packet/byte fields are
carried as hex strings. The node *logic* still comes from ../../model/protocol.py.
"""
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))   # protocol.py
sys.path.insert(0, os.path.join(HERE, ".."))                  # transport.py
import protocol as P
from transport import send_msg, recv_msg

HOST = "127.0.0.1"
PORT_COMPUTE   = int(os.environ.get("PORT_COMPUTE", 5551))
PORT_INTERLOCK = int(os.environ.get("PORT_INTERLOCK", 5552))
PORT_VERIFIER  = int(os.environ.get("PORT_VERIFIER", 5554))
COMPUTE_HOST   = os.environ.get("COMPUTE_HOST", HOST)   # compute may be remote (e.g. over the FPGA)

KEY   = b"\x00" * 32              # per-request key material (plaintext prototype)
MAC   = P.H(b"interlock-mac-key") # shared secret: interlock signs, verifier checks
IID   = 7
NONCE = P.H(b"nonce")[:16]
N, CONF, VOCAB = 8, 0.999, 32000  # buckets/cert, prediction confidence, vocab


def call(host, port, req, tries=60):
    """Send one JSON request, return the JSON reply (retries while a server starts)."""
    for _ in range(tries):
        try:
            s = socket.create_connection((host, port), timeout=10)
            break
        except OSError:
            time.sleep(2)
    else:
        raise ConnectionError(f"cannot reach {host}:{port}")
    send_msg(s, json.dumps(req).encode())
    out = json.loads(recv_msg(s))
    s.close()
    return out


def serve(port, handler, name):
    """Single-threaded request/reply server: one JSON message per connection."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen()
    print(f"[{name}] listening on {port}", flush=True)
    while True:
        c, _ = srv.accept()
        try:
            reply = handler(json.loads(recv_msg(c)))
        except Exception as e:                      # noqa: BLE001 - report to caller
            reply = {"error": f"{type(e).__name__}: {e}"}
        try:
            send_msg(c, json.dumps(reply).encode())
        finally:
            c.close()


def ids_to_bytes(ids):
    return b"".join(i.to_bytes(4, "big") for i in ids)


def bytes_to_ids(b):
    return [int.from_bytes(b[i:i + 4], "big") for i in range(0, len(b), 4)]


def opening_to_json(op):
    """P.Opening (bytes / list[bytes] / int / None fields) -> JSON-safe dict."""
    out = {}
    for field, v in op._asdict().items():
        if isinstance(v, bytes):
            out[field] = v.hex()
        elif isinstance(v, list):
            out[field] = [x.hex() for x in v]
        else:
            out[field] = v          # int or None
    return out


def json_to_opening(d):
    kw = {}
    for field, v in d.items():
        if v is None or isinstance(v, int):
            kw[field] = v
        elif isinstance(v, list):
            kw[field] = [bytes.fromhex(x) for x in v]
        else:
            kw[field] = bytes.fromhex(v)
    return P.Opening(**kw)
