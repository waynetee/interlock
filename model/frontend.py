"""Prover frontend: logs everything, serves challenge openings.

Stores the log (forwarded packets with their bucket assignment), per-request
keys, and every certificate. Derived hashes are never stored — any second's
records and bucket hashes are recomputed from the log on demand.
"""
from wire import (H, HDR, parse_packet, record, bucket_hash, cert_body,
                  parse_certificate)


class Frontend:
    def __init__(self, interlock_id, buckets_per_cert=1000):
        self.interlock_id, self.n = interlock_id, buckets_per_cert
        self.log = []     # (bucket, direction, packet_bytes), forwarded packets only
        self.certs = {}   # bucket_start -> certificate bytes
        self.keys = {}    # request_id -> key

    def log_packet(self, bucket, direction, pkt):
        self.log.append((bucket, direction, pkt))

    def log_certificate(self, cert):
        self.certs[parse_certificate(cert)["bucket_start"]] = cert

    def audit_certificate(self, cert, expected_nonce):
        """The certificate body is a deterministic function of the log: byte-check it."""
        start = parse_certificate(cert)["bucket_start"]
        expect = cert_body(self.interlock_id, start,
                           self.second_hashes(start, "in"),
                           self.second_hashes(start, "out"), expected_nonce)
        return cert[:-32] == expect

    # --- derived from the log on demand ---------------------------------

    def bucket_packets(self, bucket, direction):
        return [p for b, d, p in self.log if b == bucket and d == direction]

    def second_hashes(self, start, direction):
        return [bucket_hash([record(direction, p) for p in self.bucket_packets(b, direction)])
                for b in range(start, start + self.n)]

    def _side(self, bucket, direction):
        start = bucket - bucket % self.n
        return {"cert": self.certs[start],
                "hashes": self.second_hashes(start, direction),
                "records": [record(direction, p) for p in self.bucket_packets(bucket, direction)]}

    def open_challenge(self, y, x):
        """Opening for byte x of output bucket y: the smallest log slice the
        verifier needs to recompute the certificates (see doc, Challenge step 3)."""
        out = self._side(y, "out")
        opening = {"y": y, "cert_out": out["cert"], "hashes_out": out["hashes"],
                   "records_out": out["records"]}
        pos = 0
        for pkt in self.bucket_packets(y, "out"):
            if pos <= x < pos + len(pkt):
                opening["header_out"] = pkt[:HDR["out"]]
                opening["h1_out"] = H(pkt[HDR["out"]:])
                rid = parse_packet("out", pkt)[1]
                w, in_pkt = next((b, p) for b, d, p in self.log
                                 if d == "in" and parse_packet("in", p)[1] == rid)
                inp = self._side(w, "in")
                opening.update({"w": w, "cert_in": inp["cert"], "hashes_in": inp["hashes"],
                                "records_in": inp["records"],
                                "header_in": in_pkt[:HDR["in"]],
                                "h1_in": H(in_pkt[HDR["in"]:])})
                return opening
            pos += len(pkt)
        return opening  # byte x is empty: the record list alone proves it

    def challenge_materials(self, rid):
        """Ciphertexts + key for the recomputation stage (prover side only)."""
        in_ct = next(parse_packet(d, p)[2] for _, d, p in self.log
                     if d == "in" and parse_packet(d, p)[1] == rid)
        out_ct = next(parse_packet(d, p)[2] for _, d, p in self.log
                      if d == "out" and parse_packet(d, p)[1] == rid)
        return in_ct, self.keys[rid], out_ct
