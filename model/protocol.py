"""Reference model of docs/verification-protocol.md (v5).

One object per component, in data-path order; the section banners mark trust
boundaries. Components exchange serialized wire bytes, so test vectors here
are byte-exact for the FPGA gateware and any other implementation.

All integers are big-endian, fixed width. The cipher is a stand-in stream
cipher (SHA-256 keystream XOR, domain-separated per direction) so the model
has no dependencies; the real system uses AES-CTR. Both are
position-addressable, which is all the protocol relies on.
"""
import hashlib
import hmac as _hmac
import struct
from math import log2, inf

UNIT = 4                # bytes per token on the wire
VERSION = b"ilock-v5"   # 8 bytes
RVERSION = b"recomp-v1"


# ===========================================================================
# Wire formats and hashes (shared by every component)
# ===========================================================================

def H(data):
    return hashlib.sha256(data).digest()


def mac(key, m):
    return _hmac.new(key, m, hashlib.sha256).digest()


def mac_ok(key, m, tag):
    return _hmac.compare_digest(mac(key, m), tag)


def encrypt(key, domain, data):  # stand-in cipher; swap for AES-CTR
    ks = b""
    block = 0
    while len(ks) < len(data):
        ks += H(key + domain + block.to_bytes(8, "big"))
        block += 1
    return bytes(a ^ b for a, b in zip(data, ks))


decrypt = encrypt  # XOR stream cipher is its own inverse


def tokens_to_bytes(tokens):
    return b"".join(t.to_bytes(UNIT, "big") for t in tokens)


def bytes_to_tokens(data):
    return [int.from_bytes(data[i:i + UNIT], "big") for i in range(0, len(data), UNIT)]


# input  packet: length(4) | request_id(8) | recomp_commitment(32) | ciphertext
# output packet: length(4) | request_id(8) | ciphertext
# Header = everything before the ciphertext. recomp_commitment = H(key) = H2.

HDR = {"in": 44, "out": 12}


def input_packet(request_id, key, ciphertext):
    return (len(ciphertext).to_bytes(4, "big") + request_id.to_bytes(8, "big")
            + H(key) + ciphertext)


def output_packet(request_id, ciphertext):
    return len(ciphertext).to_bytes(4, "big") + request_id.to_bytes(8, "big") + ciphertext


def parse_packet(direction, pkt):
    """-> (length, request_id, ciphertext). Header fields are pkt[:HDR[direction]]."""
    return (int.from_bytes(pkt[:4], "big"), int.from_bytes(pkt[4:12], "big"),
            pkt[HDR[direction]:])


def packet_hash(direction, pkt):
    """H(header | H(ciphertext)) — the ciphertext hash is a separable leaf (H1)."""
    return H(pkt[:HDR[direction]] + H(pkt[HDR[direction]:]))


# Log -> certificate hashing, the three steps:

def record(direction, pkt):
    """Step 1, per packet: length(4) | request_id(8) | packet_hash(32)."""
    return pkt[:12] + packet_hash(direction, pkt)


def bucket_hash(records):
    """Step 2, per bucket: hash of the ordered records (H of empty if none)."""
    return H(b"".join(records))


def overall_hash(bucket_hashes):
    """Step 3, per second: hash of the bucket-hash sequence, one per direction."""
    return H(b"".join(bucket_hashes))


def cert_body(interlock_id, bucket_start, hashes_in, hashes_out, nonce):
    """m — every field is derivable from the log + latched nonce (prover-auditable)."""
    return (VERSION + interlock_id.to_bytes(8, "big") + bucket_start.to_bytes(8, "big")
            + len(hashes_in).to_bytes(4, "big")
            + overall_hash(hashes_in) + overall_hash(hashes_out) + nonce)


def parse_certificate(cert):
    m, tag = cert[:-32], cert[-32:]
    return {"version": m[:8], "interlock_id": int.from_bytes(m[8:16], "big"),
            "bucket_start": int.from_bytes(m[16:24], "big"),
            "num_buckets": int.from_bytes(m[24:28], "big"),
            "overall_in": m[28:60], "overall_out": m[60:92], "nonce": m[92:108],
            "m": m, "tag": tag}


def parse_recomp_certificate(cert):
    m, tag = cert[:-32], cert[-32:]
    assert m[:9] == RVERSION
    return {"recomp_id": int.from_bytes(m[9:17], "big"), "nonce": m[17:33],
            "h1_in": m[33:65], "h2": m[65:97], "h1_out": m[97:129],
            "n_units": int.from_bytes(m[129:133], "big"),
            "U": struct.unpack(">d", m[133:141])[0], "m": m, "tag": tag}


# ===========================================================================
# Prover compute (untrusted, workload phase)
#
# Not a protocol participant: its only contract is the packet bytes it
# emits. The protocol can't see whether it honestly ran the declared
# computation — only whether its outputs are *explainable* at challenge time.
# ===========================================================================

def make_pair(request_id, prompt_tokens, key, respond):
    """Run a request/response through compute: respond() is the model
    (honest compute passes the declared computation; covert compute doesn't)."""
    in_ct = encrypt(key, b"in", tokens_to_bytes(prompt_tokens))
    out_ct = encrypt(key, b"out", tokens_to_bytes(respond(prompt_tokens)))
    return input_packet(request_id, key, in_ct), output_packet(request_id, out_ct)


# ===========================================================================
# Verifier interlock (verifier hardware, in the workload data path)
#
# Processes both streams on the fly, enforces validity rules, emits one HMAC
# certificate per second. Holds only the current second of state.
# Event-style to mirror the gateware: on_packet / on_bucket_boundary / on_second.
# ===========================================================================

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
        m = cert_body(self.interlock_id, self.bucket - self.n,
                      self.hashes["in"], self.hashes["out"], self.nonce)
        cert = m + mac(self.mac_key, m)
        self.hashes = {"in": [], "out": []}
        return cert


# ===========================================================================
# Prover frontend (prover hardware)
#
# Logs everything: forwarded packets with bucket assignment, per-request
# keys, every certificate. Derived hashes are never stored — recomputed from
# the log on demand. Serves challenge openings.
# ===========================================================================

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
        verifier needs to recompute the certificates (doc, Challenge step 3)."""
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


# ===========================================================================
# Recomputation, Option 1 (challenge time)
#
# A stateless recomputation interlock (verifier hardware at the enclosure
# boundary) mediates a commit-then-reveal scoring loop with a recomputation
# node (prover hardware inside the verifier enclosure). Scoring runs in
# ciphertext space — the interlock never decrypts.
# ===========================================================================

RESIDUAL_SPACE = 2 ** (8 * UNIT)  # unlisted units share the leftover probability


class RecompInterlock:
    def __init__(self, mac_key, recomp_id):
        self.mac_key, self.recomp_id = mac_key, recomp_id

    def run(self, nonce, h1_in, h2, input_ct, key_material, output_ct, node):
        """One challenge. Returns a certificate, or None if a check fails.
        Ingress is gated by commitments: only data matching H1_in/H2 reaches
        the node (the key material post-dates the response, so unpinned it
        could smuggle the answers in)."""
        if H(input_ct) != h1_in or H(key_material) != h2:
            return None
        node.load(input_ct, key_material)
        units = [output_ct[i:i + UNIT] for i in range(0, len(output_ct), UNIT)]
        U = 0.0
        for unit in units:                     # commit, check, look up, reveal
            table = node.commit()
            spent = sum(table.values())
            if spent > 1 + 1e-12:              # sub-distribution check: without it
                return None                    # the node could claim prob 1 for everything
            q = table.get(unit, (1 - spent) / (RESIDUAL_SPACE - len(table)))
            U = inf if q <= 0 else U - log2(q)
            node.reveal(unit)
        m = (RVERSION + self.recomp_id.to_bytes(8, "big") + nonce
             + h1_in + h2 + H(output_ct)
             + len(units).to_bytes(4, "big") + struct.pack(">d", U))
        return m + mac(self.mac_key, m)


class RecompNode:
    """Honest recomputation node: runs the declared computation and predicts
    the true ciphertext units, holding back a little probability mass for
    (here unmodeled) hardware noise."""
    def __init__(self, declared_d, confidence=0.999):
        self.d, self.confidence = declared_d, confidence

    def load(self, input_ct, key):
        prompt = bytes_to_tokens(decrypt(key, b"in", input_ct))
        self.ct = encrypt(key, b"out", tokens_to_bytes(self.d(prompt)))
        self.i = 0

    def commit(self):
        return {self.ct[self.i * UNIT:(self.i + 1) * UNIT]: self.confidence}

    def reveal(self, unit):
        self.i += 1


# ===========================================================================
# External verifier
#
# The verifier's TCB: anchors certificates, selects challenges, runs the
# opening checks (a)-(e) and the recomputation check (f) from the doc.
# ===========================================================================

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
        c = parse_recomp_certificate(cert)
        assert mac_ok(self.recomp_key, c["m"], c["tag"])
        assert c["recomp_id"] == self.recomp_id and c["nonce"] == nonce
        for k in ("h1_in", "h2", "h1_out"):
            assert c[k] == binding[k]
        return c["U"]
