"""Verifier interlock — in the data path.   [diagram: Verifier interlock]

Holds the interlock logic (validity rules, hashing, per-second certificate) and,
run as a process, forwards each turn to compute and emits the certificate the
prover stores. Verifier-trusted: it holds the shared MAC key. It never originates
or interprets payloads — it forwards and certifies.
"""
from wire import *                       # noqa: F401,F403 - the wire vocabulary
from common import (call, serve, MAC, IID, NONCE, N,
                    COMPUTE_HOST, PORT_COMPUTE, PORT_INTERLOCK)


class Interlock:
    """Processes both streams; emits one HMAC certificate per `buckets_per_cert`
    boundaries. Event-style to mirror the gateware: on_packet / on_bucket_boundary
    / on_second. Holds only the current second of state."""

    def __init__(self, mac_key, interlock_id, s_max=100_000, capacity=100_000,
                 buckets_per_cert=1000):
        self.mac_key, self.interlock_id = mac_key, interlock_id
        self.s_max, self.capacity, self.n = s_max, capacity, buckets_per_cert
        self.bucket = 0                       # monotonic counter (battery-backed with key)
        self.nonce = bytes(16)                # latched verifier nonce
        self.last_in_id = -1                  # inbound comparator, session-wide
        self.last_out_id = -1                 # outbound comparator, resets per bucket
        self.records = {"in": [], "out": []}  # current bucket
        self.used = {"in": 0, "out": 0}       # current bucket bytes
        self.hashes = {"in": [], "out": []}   # closed buckets this second

    def on_nonce(self, nonce):
        self.nonce = nonce  # latch unauthenticated; verifier credits only its own nonces

    def on_packet(self, direction, pkt):
        """Forward (return pkt) or drop (return None). Drops are never hashed."""
        p = parse_packet(direction, pkt)
        last = self.last_in_id if direction == "in" else self.last_out_id
        if p["length"] != len(p["ciphertext"]) or p["length"] > self.s_max:
            return None
        if p["request_id"] <= last:
            return None
        if self.used[direction] + len(pkt) > self.capacity:
            return None
        if direction == "in":
            self.last_in_id = p["request_id"]
        else:
            self.last_out_id = p["request_id"]
        self.records[direction].append(record(direction, pkt))
        self.used[direction] += len(pkt)
        return pkt

    def on_bucket_boundary(self):
        """Close the 1 ms bucket: hash its records, reset per-bucket state."""
        for d in ("in", "out"):
            self.hashes[d].append(bucket_hash(self.records[d]))
            self.records[d], self.used[d] = [], 0
        self.last_out_id = -1
        self.bucket += 1

    def on_second(self):
        """After the n-th boundary: emit the certificate, discard the bucket hashes."""
        assert len(self.hashes["in"]) == self.n
        m = cert_body(self.interlock_id, self.bucket - self.n,
                      self.hashes["in"], self.hashes["out"], self.nonce)
        self.hashes = {"in": [], "out": []}
        return m + mac(self.mac_key, m)


if __name__ == "__main__":
    il = Interlock(MAC, IID, buckets_per_cert=N)
    il.on_nonce(NONCE)

    def handler(req):
        if req["op"] != "turn":
            return {"error": "unknown op"}
        req_pkt = bytes.fromhex(req["request_packet"])
        # forward through to compute, get the response packet back
        r = call(COMPUTE_HOST, PORT_COMPUTE, {"op": "workload",
                 "request_packet": req_pkt.hex(), "max_new": req.get("max_new", 48)})
        resp_pkt = bytes.fromhex(r["response_packet"])
        # certify this turn: request in bucket `start`, response in `start+1`
        start = il.bucket
        sched = {0: [("in", req_pkt)], 1: [("out", resp_pkt)]}
        for i in range(N):
            for direction, pkt in sched.get(i, []):
                il.on_packet(direction, pkt)
            il.on_bucket_boundary()
        cert = il.on_second()
        return {"response_packet": resp_pkt.hex(), "certificate": cert.hex(),
                "req_bucket": start, "resp_bucket": start + 1, "text": r["text"]}

    serve(PORT_INTERLOCK, handler, "interlock")
