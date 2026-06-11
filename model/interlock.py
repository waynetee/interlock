"""Golden model of the verifier interlock.

Processes both packet streams on the fly, enforces the validity rules, and
emits one HMAC certificate per second. Holds only the current second of
state. Event-style to mirror the planned gateware: on_packet /
on_bucket_boundary / on_second.
"""
from wire import parse_packet, record, bucket_hash, certificate


class Interlock:
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
        length, rid, ct = parse_packet(direction, pkt)
        last = self.last_in_id if direction == "in" else self.last_out_id
        if length != len(ct) or length > self.s_max:
            return None
        if rid <= last:
            return None
        if self.used[direction] + len(pkt) > self.capacity:
            return None
        if direction == "in":
            self.last_in_id = rid
        else:
            self.last_out_id = rid
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
        cert = certificate(self.mac_key, self.interlock_id, self.bucket - self.n,
                           self.hashes["in"], self.hashes["out"], self.nonce)
        self.hashes = {"in": [], "out": []}
        return cert
