"""Recomputation stage, Option 1 (challenge time). Split out of protocol.py
so the workload dataflow can be read on its own; this file rejoins it at
run_challenge().

A stateless recomputation interlock (verifier hardware at the enclosure
boundary) mediates a commit-then-reveal scoring loop with a recomputation
node (prover hardware inside the verifier enclosure). Scoring runs in
ciphertext space — the interlock never decrypts.
"""
from math import log2, inf

from protocol import (H, UNIT, TAG, pack, unpack, mac, mac_ok,
                      encrypt, decrypt, tokens_to_bytes, bytes_to_tokens)

RVERSION = b"recomp-v1"  # 9 bytes

# Recomputation certificate body (doc, Recomputation certificate).
RECOMP_CERT = [("version", 9, "bytes"), ("recomp_id", 8, "int"),
               ("nonce", 16, "bytes"), ("h1_in", 32, "bytes"), ("h2", 32, "bytes"),
               ("h1_out", 32, "bytes"), ("n_units", 4, "int"), ("U", 8, "float")]

RESIDUAL_SPACE = 2 ** (8 * UNIT)  # unlisted units share the leftover probability


def parse_recomp_certificate(cert):
    m, tag = cert[:-TAG], cert[-TAG:]
    c = {**unpack(RECOMP_CERT, m), "m": m, "tag": tag}
    assert c["version"] == RVERSION
    return c


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


def verify_recomp(recomp_key, recomp_id, cert, nonce, binding):
    """Doc check (f), run by the external verifier: the recomputation
    certificate matches the opened values; returns the attested U in bits."""
    c = parse_recomp_certificate(cert)
    assert mac_ok(recomp_key, c["m"], c["tag"])
    assert c["recomp_id"] == recomp_id and c["nonce"] == nonce
    for k in ("h1_in", "h2", "h1_out"):
        assert c[k] == binding[k]
    return c["U"]


# ===========================================================================
# Challenge procedure (doc, Challenge steps 3-5)
#
# The protocol's full choreography: open the log, verify the opening,
# run the recomputation, check its certificate. The anchor/select steps
# (1-2) are Verifier.anchor and Verifier.select in protocol.py.
# ===========================================================================

def run_challenge(verifier, frontend, recomp_interlock, node, y, x, nonce,
                  recomp_key, recomp_id):
    """Returns the attested U for byte x of output bucket y, or None if
    that byte is empty. Raises if any check fails."""
    binding = verifier.verify_opening(y, x, frontend.open_challenge(y, x))
    if binding is None:
        return None
    in_ct, key, out_ct = frontend.challenge_materials(binding["rid"])
    cert = recomp_interlock.run(nonce, binding["h1_in"], binding["h2"],
                                in_ct, key, out_ct, node)
    return verify_recomp(recomp_key, recomp_id, cert, nonce, binding)
