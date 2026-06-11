"""Reference model of docs/verification-protocol.md (v5).

One object per component, in data-path order; the section banners mark trust
boundaries. Components exchange serialized wire bytes, so test vectors here
are byte-exact for the FPGA gateware and any other implementation. Every
fixed-width message is defined once by a layout table; pack() and unpack()
are generated from the same table, so builders and parsers cannot disagree.

All integers are big-endian, fixed width. The cipher is a stand-in stream
cipher (SHA-256 keystream XOR, domain-separated per direction) so the model
has no dependencies; the real system uses AES-CTR. Both are
position-addressable, which is all the protocol relies on.
"""
import hashlib
import hmac as _hmac
import struct
from math import log2, inf
from typing import NamedTuple

UNIT = 4                 # bytes per token on the wire
TAG = 32                 # HMAC-SHA-256 tag size
VERSION = b"ilock-v5"    # 8 bytes
RVERSION = b"recomp-v1"  # 9 bytes


# ===========================================================================
# Wire formats and hashes (shared by every component)
# ===========================================================================

def pack(layout, fields):
    out = b""
    for name, size, kind in layout:
        v = fields[name]
        chunk = (v.to_bytes(size, "big") if kind == "int"
                 else struct.pack(">d", v) if kind == "float" else v)
        assert len(chunk) == size, name
        out += chunk
    return out


def unpack(layout, data):
    out, pos = {}, 0
    for name, size, kind in layout:
        chunk = data[pos:pos + size]
        out[name] = (int.from_bytes(chunk, "big") if kind == "int"
                     else struct.unpack(">d", chunk)[0] if kind == "float" else chunk)
        pos += size
    return out


# Packet = header | ciphertext. recomp_commitment = H(key) = H2.
HEADER = {
    "in":  [("length", 4, "int"), ("request_id", 8, "int"),
            ("recomp_commitment", 32, "bytes")],
    "out": [("length", 4, "int"), ("request_id", 8, "int")],
}
HDR = {d: sum(size for _, size, _ in l) for d, l in HEADER.items()}

# Record: what the interlock commits per packet (hashing step 1).
RECORD = [("length", 4, "int"), ("request_id", 8, "int"), ("packet_hash", 32, "bytes")]

# Certificate body m (the HMAC tag follows it on the wire).
CERT = [("version", 8, "bytes"), ("interlock_id", 8, "int"),
        ("bucket_start", 8, "int"), ("num_buckets", 4, "int"),
        ("overall_in", 32, "bytes"), ("overall_out", 32, "bytes"),
        ("nonce", 16, "bytes")]

# Recomputation certificate body (doc, Recomputation certificate).
RECOMP_CERT = [("version", 9, "bytes"), ("recomp_id", 8, "int"),
               ("nonce", 16, "bytes"), ("h1_in", 32, "bytes"), ("h2", 32, "bytes"),
               ("h1_out", 32, "bytes"), ("n_units", 4, "int"), ("U", 8, "float")]


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


def input_packet(request_id, key, ciphertext):
    return pack(HEADER["in"], {"length": len(ciphertext), "request_id": request_id,
                               "recomp_commitment": H(key)}) + ciphertext


def output_packet(request_id, ciphertext):
    return pack(HEADER["out"], {"length": len(ciphertext),
                                "request_id": request_id}) + ciphertext


def parse_packet(direction, pkt):
    """-> header fields plus "ciphertext"."""
    p = unpack(HEADER[direction], pkt)
    p["ciphertext"] = pkt[HDR[direction]:]
    return p


def packet_hash(direction, pkt):
    """H(header | H(ciphertext)) — the ciphertext hash is a separable leaf (H1)."""
    return H(pkt[:HDR[direction]] + H(pkt[HDR[direction]:]))


def record(direction, pkt):
    """Hashing step 1, per packet."""
    p = parse_packet(direction, pkt)
    return pack(RECORD, {"length": p["length"], "request_id": p["request_id"],
                         "packet_hash": packet_hash(direction, pkt)})


def bucket_hash(records):
    """Hashing step 2, per bucket: the ordered records (H of empty if none)."""
    return H(b"".join(records))


def overall_hash(bucket_hashes):
    """Hashing step 3, per second: the bucket-hash sequence, one per direction."""
    return H(b"".join(bucket_hashes))


def cert_body(interlock_id, bucket_start, hashes_in, hashes_out, nonce):
    """m — every field is derivable from the log + latched nonce (prover-auditable)."""
    return pack(CERT, {"version": VERSION, "interlock_id": interlock_id,
                       "bucket_start": bucket_start, "num_buckets": len(hashes_in),
                       "overall_in": overall_hash(hashes_in),
                       "overall_out": overall_hash(hashes_out), "nonce": nonce})


def parse_certificate(cert):
    m, tag = cert[:-TAG], cert[-TAG:]
    return {**unpack(CERT, m), "m": m, "tag": tag}


def parse_recomp_certificate(cert):
    m, tag = cert[:-TAG], cert[-TAG:]
    c = {**unpack(RECOMP_CERT, m), "m": m, "tag": tag}
    assert c["version"] == RVERSION
    return c


def locate(direction, records, x):
    """Index of the packet covering byte x of a bucket, walking the records by
    cumulative wire size; None means x is past the bucket's content (the
    record list alone proves emptiness). The frontend and the verifier both
    locate through this one function, so their size arithmetic cannot diverge."""
    pos = 0
    for i, rec in enumerate(records):
        size = HDR[direction] + unpack(RECORD, rec)["length"]
        if pos <= x < pos + size:
            return i
        pos += size
    return None


class Opening(NamedTuple):
    """Everything the prover transmits for one challenge (doc, Challenge
    step 3). Fields after records_out are None when byte x is empty."""
    y: int                    # challenged output bucket
    cert_out: bytes           # certificate covering y
    hashes_out: list          # that second's output bucket hashes
    records_out: list         # records of bucket y
    header_out: bytes = None  # header of the hit packet
    h1_out: bytes = None      # H(ciphertext) of the hit packet
    w: int = None             # bucket of the matching input packet
    cert_in: bytes = None     # certificate covering w
    hashes_in: list = None    # that second's input bucket hashes
    records_in: list = None   # records of bucket w
    header_in: bytes = None   # input header (carries the H2 commitment)
    h1_in: bytes = None       # H(ciphertext) of the input packet


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
        return cert[:-TAG] == expect

    def bucket_packets(self, bucket, direction):
        return [p for b, d, p in self.log if b == bucket and d == direction]

    def second_hashes(self, start, direction):
        return [bucket_hash([record(direction, p) for p in self.bucket_packets(b, direction)])
                for b in range(start, start + self.n)]

    def _side(self, bucket, direction):
        """-> (certificate, that second's bucket hashes, the bucket's records)."""
        start = bucket - bucket % self.n
        return (self.certs[start], self.second_hashes(start, direction),
                [record(direction, p) for p in self.bucket_packets(bucket, direction)])

    def open_challenge(self, y, x):
        """Opening for byte x of output bucket y (doc, Challenge step 3)."""
        cert_out, hashes_out, records_out = self._side(y, "out")
        hit = locate("out", records_out, x)
        if hit is None:
            return Opening(y, cert_out, hashes_out, records_out)
        pkt = self.bucket_packets(y, "out")[hit]
        rid = parse_packet("out", pkt)["request_id"]
        w, in_pkt = next((b, p) for b, d, p in self.log
                         if d == "in" and parse_packet("in", p)["request_id"] == rid)
        cert_in, hashes_in, records_in = self._side(w, "in")
        return Opening(y, cert_out, hashes_out, records_out,
                       header_out=pkt[:HDR["out"]], h1_out=H(pkt[HDR["out"]:]),
                       w=w, cert_in=cert_in, hashes_in=hashes_in, records_in=records_in,
                       header_in=in_pkt[:HDR["in"]], h1_in=H(in_pkt[HDR["in"]:]))

    def challenge_materials(self, rid):
        """Ciphertexts + key for the recomputation stage (prover side only)."""
        in_ct = next(parse_packet(d, p)["ciphertext"] for _, d, p in self.log
                     if d == "in" and parse_packet(d, p)["request_id"] == rid)
        out_ct = next(parse_packet(d, p)["ciphertext"] for _, d, p in self.log
                      if d == "out" and parse_packet(d, p)["request_id"] == rid)
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
        m = pack(RECOMP_CERT, {"version": RVERSION, "recomp_id": self.recomp_id,
                               "nonce": nonce, "h1_in": h1_in, "h2": h2,
                               "h1_out": H(output_ct), "n_units": len(units), "U": U})
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
        """(a) authentic: valid tag, this protocol, our device."""
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

    def _check_side(self, cert, overall_field, bucket, hashes, records):
        c = self.check_certificate(cert)                       # (a)
        start = c["bucket_start"]
        assert start <= bucket < start + self.n
        assert overall_hash(hashes) == c[overall_field]        # (b)
        assert bucket_hash(records) == hashes[bucket - start]  # (c)

    @staticmethod
    def _check_packet(direction, records, idx, header, h1):
        """The revealed header + ciphertext hash must reproduce the record."""
        rec, hdr = unpack(RECORD, records[idx]), unpack(HEADER[direction], header)
        assert (hdr["length"], hdr["request_id"]) == (rec["length"], rec["request_id"])
        assert H(header + h1) == rec["packet_hash"]
        return rec["request_id"]

    def verify_opening(self, y, x, op):
        """Doc checks (a)-(e). Returns None if byte x is empty, else the
        binding values {rid, h1_in, h2, h1_out} for the recomputation check."""
        assert op.y == y
        self._check_side(op.cert_out, "overall_out", y, op.hashes_out, op.records_out)
        hit = locate("out", op.records_out, x)                 # (d) byte x -> packet
        if hit is None:
            return None  # past the bucket's content: empty, done
        rid = self._check_packet("out", op.records_out, hit, op.header_out, op.h1_out)
        # (e) input binding: committed inbound, earlier bucket, ID match, single use
        self._check_side(op.cert_in, "overall_in", op.w, op.hashes_in, op.records_in)
        assert op.w <= y
        idx = next(i for i, r in enumerate(op.records_in)
                   if unpack(RECORD, r)["request_id"] == rid)
        assert self._check_packet("in", op.records_in, idx, op.header_in, op.h1_in) == rid
        assert rid not in self.used_ids
        self.used_ids.add(rid)
        return {"rid": rid, "h1_in": op.h1_in, "h1_out": op.h1_out,
                "h2": unpack(HEADER["in"], op.header_in)["recomp_commitment"]}

    def verify_recomp(self, cert, nonce, binding):
        """(f) the recomputation certificate matches the opened values;
        returns the attested unexplained information U in bits."""
        c = parse_recomp_certificate(cert)
        assert mac_ok(self.recomp_key, c["m"], c["tag"])
        assert c["recomp_id"] == self.recomp_id and c["nonce"] == nonce
        for k in ("h1_in", "h2", "h1_out"):
            assert c[k] == binding[k]
        return c["U"]


# ===========================================================================
# Challenge procedure (doc, Challenge steps 3-5)
#
# The protocol's own choreography: open the log, verify the opening,
# run the recomputation, check its certificate. The anchor/select steps
# (1-2) are Verifier.anchor and Verifier.select.
# ===========================================================================

def run_challenge(verifier, frontend, recomp_interlock, node, y, x, nonce):
    """Returns the attested U for byte x of output bucket y, or None if
    that byte is empty. Raises if any check fails."""
    binding = verifier.verify_opening(y, x, frontend.open_challenge(y, x))
    if binding is None:
        return None
    in_ct, key, out_ct = frontend.challenge_materials(binding["rid"])
    cert = recomp_interlock.run(nonce, binding["h1_in"], binding["h2"],
                                in_ct, key, out_ct, node)
    return verifier.verify_recomp(cert, nonce, binding)
