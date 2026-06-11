"""External verifier. This file is the verifier's TCB: it imports only the
wire formats and stdlib crypto, and its checks are the protocol's checks
(doc, Challenge step 5)."""
import struct

from wire import (H, VERSION, mac_ok, parse_certificate, overall_hash,
                  bucket_hash)

import recomp


class Verifier:
    def __init__(self, mac_key, interlock_id, recomp_key, recomp_id,
                 buckets_per_cert=1000, capacity=100_000):
        self.mac_key, self.interlock_id = mac_key, interlock_id
        self.recomp_key, self.recomp_id = recomp_key, recomp_id
        self.n, self.capacity = buckets_per_cert, capacity
        self.anchors = []   # bucket_start of each anchored certificate
        self.used_ids = set()

    def check_certificate(self, cert):
        c = parse_certificate(cert)
        assert mac_ok(self.mac_key, c["m"], c["tag"])
        assert c["version"] == VERSION and c["interlock_id"] == self.interlock_id
        assert c["num_buckets"] == self.n
        return c

    def anchor(self, nonce, cert):
        """Check the certificate echoes our nonce; returns current bucket B."""
        c = self.check_certificate(cert)
        assert c["nonce"] == nonce
        assert not self.anchors or c["bucket_start"] > self.anchors[-1]
        self.anchors.append(c["bucket_start"])
        return c["bucket_start"] + self.n

    def select(self, rng, current_bucket, window):
        """Uniform over (bucket, byte): size-weighted sampling of transmitted bytes."""
        return (rng.randrange(max(0, current_bucket - window), current_bucket),
                rng.randrange(self.capacity))

    def _check_side(self, cert, direction, bucket, hashes, records):
        c = self.check_certificate(cert)
        start = c["bucket_start"]
        assert start <= bucket < start + self.n
        assert overall_hash(hashes) == c["overall_" + direction]
        assert bucket_hash(records) == hashes[bucket - start]

    @staticmethod
    def _check_packet(records, idx, header, h1):
        assert header[:12] == records[idx][:12]       # length + request_id
        assert H(header + h1) == records[idx][12:44]  # packet_hash
        return int.from_bytes(header[4:12], "big")    # request_id

    def verify_opening(self, y, x, op):
        """Doc checks (a)-(e). Returns None if byte x is empty, else the
        binding values {rid, h1_in, h2, h1_out} for the recomputation check."""
        assert op["y"] == y
        self._check_side(op["cert_out"], "out", y, op["hashes_out"], op["records_out"])
        pos, hit = 0, None
        for i, rec in enumerate(op["records_out"]):   # locate byte x by cumulative size
            size = 12 + int.from_bytes(rec[:4], "big")
            if pos <= x < pos + size:
                hit = i
                break
            pos += size
        if hit is None:
            assert x >= pos        # past the bucket's content: empty, done
            return None
        rid = self._check_packet(op["records_out"], hit, op["header_out"], op["h1_out"])
        # input binding: committed inbound, earlier bucket, ID match, single use
        self._check_side(op["cert_in"], "in", op["w"], op["hashes_in"], op["records_in"])
        assert op["w"] <= y
        idx = next(i for i, r in enumerate(op["records_in"])
                   if int.from_bytes(r[4:12], "big") == rid)
        assert self._check_packet(op["records_in"], idx, op["header_in"], op["h1_in"]) == rid
        assert rid not in self.used_ids
        self.used_ids.add(rid)
        return {"rid": rid, "h1_in": op["h1_in"], "h2": op["header_in"][12:44],
                "h1_out": op["h1_out"]}

    def verify_recomp(self, cert, nonce, binding):
        """Doc check (f): the recomputation certificate matches the opened
        values; returns the attested unexplained information U in bits."""
        c = recomp.parse_certificate(cert)
        assert mac_ok(self.recomp_key, c["m"], c["tag"])
        assert c["recomp_id"] == self.recomp_id and c["nonce"] == nonce
        for k in ("h1_in", "h2", "h1_out"):
            assert c[k] == binding[k]
        return c["U"]
