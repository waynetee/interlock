"""Option 1 recomputation: a stateless recomputation interlock mediates a
commit-then-reveal scoring loop between the prover frontend and a
recomputation node inside the verifier enclosure. Scoring runs in ciphertext
space — the interlock never decrypts.
"""
import struct
from math import log2, inf

from wire import H, UNIT, mac, decrypt, encrypt, tokens_to_bytes, bytes_to_tokens

RVERSION = b"recomp-v1"
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


def parse_certificate(cert):
    m, tag = cert[:-32], cert[-32:]
    assert m[:9] == RVERSION
    return {"recomp_id": int.from_bytes(m[9:17], "big"), "nonce": m[17:33],
            "h1_in": m[33:65], "h2": m[65:97], "h1_out": m[97:129],
            "n_units": int.from_bytes(m[129:133], "big"),
            "U": struct.unpack(">d", m[133:141])[0], "m": m, "tag": tag}


class HonestNode:
    """Runs the declared computation D and predicts the true ciphertext units,
    holding back a little probability mass for (here unmodeled) hardware noise."""
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
