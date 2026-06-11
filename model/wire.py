"""Wire formats and hashes for the verification protocol (docs/verification-protocol.md).

All integers are big-endian, fixed width. The cipher is a stand-in stream
cipher (SHA-256 keystream XOR, domain-separated per direction) so the model
has no dependencies; the real system uses AES-CTR. Both are
position-addressable, which is all the protocol relies on.
"""
import hashlib
import hmac as _hmac

UNIT = 4            # bytes per token on the wire
VERSION = b"ilock-v5"  # 8 bytes


def H(data):
    return hashlib.sha256(data).digest()


def mac(key, m):
    return _hmac.new(key, m, hashlib.sha256).digest()


def mac_ok(key, m, tag):
    return _hmac.compare_digest(mac(key, m), tag)


# --- stand-in cipher (swap for AES-CTR in the real system) -----------------

def encrypt(key, domain, data):
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


# --- packets ----------------------------------------------------------------
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


# --- log -> certificate hashing (the three steps) ---------------------------

def record(direction, pkt):
    """Step 1, per packet: length(4) | request_id(8) | packet_hash(32)."""
    return pkt[:12] + packet_hash(direction, pkt)


def bucket_hash(records):
    """Step 2, per bucket: hash of the ordered records (H of empty if none)."""
    return H(b"".join(records))


def overall_hash(bucket_hashes):
    """Step 3, per second: hash of the bucket-hash sequence, one per direction."""
    return H(b"".join(bucket_hashes))


# --- certificate -------------------------------------------------------------

def cert_body(interlock_id, bucket_start, hashes_in, hashes_out, nonce):
    """m — every field is derivable from the log + latched nonce (prover-auditable)."""
    return (VERSION + interlock_id.to_bytes(8, "big") + bucket_start.to_bytes(8, "big")
            + len(hashes_in).to_bytes(4, "big")
            + overall_hash(hashes_in) + overall_hash(hashes_out) + nonce)


def certificate(mac_key, interlock_id, bucket_start, hashes_in, hashes_out, nonce):
    m = cert_body(interlock_id, bucket_start, hashes_in, hashes_out, nonce)
    return m + mac(mac_key, m)


def parse_certificate(cert):
    m, tag = cert[:-32], cert[-32:]
    return {"version": m[:8], "interlock_id": int.from_bytes(m[8:16], "big"),
            "bucket_start": int.from_bytes(m[16:24], "big"),
            "num_buckets": int.from_bytes(m[24:28], "big"),
            "overall_in": m[28:60], "overall_out": m[60:92], "nonce": m[92:108],
            "m": m, "tag": tag}
