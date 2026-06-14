"""External verifier — checks certificates and recomputes U.   [diagram: Verifier]

Trusted by itself only (holds the shared MAC key, never sees prover internals
beyond what's opened). On a challenge it: (1) verifies the opening against the
interlock's certificate, (2) checks the supplied recomputation materials hash to
the committed values, and (3) drives the recomputation (compute's `score`) to get
U. It never trusts a prover-supplied U — it recomputes against the commitments.
"""
import math

from common import (P, call, serve, MAC, IID, N, CONF, VOCAB,
                    COMPUTE_HOST, PORT_COMPUTE, PORT_VERIFIER,
                    ids_to_bytes, json_to_opening)


def handler(req):
    if req["op"] != "challenge":
        return {"error": "unknown op"}
    op = json_to_opening(req["opening"])
    try:
        binding = P.Verifier(MAC, IID, buckets_per_cert=N).verify_opening(op.y, 0, op)
    except Exception as e:                                   # noqa: BLE001
        return {"verified": False, "reason": f"certificate/opening check failed: {e}"}

    # bind the recomputation materials to what the certificate committed
    prompt_bytes = bytes.fromhex(req["prompt"])
    tokens = req["tokens"]
    if P.H(prompt_bytes) != binding["h1_in"]:
        return {"verified": True, "bound": False, "reason": "input doesn't match commitment"}
    if P.H(ids_to_bytes(tokens)) != binding["h1_out"]:
        return {"verified": True, "bound": False, "reason": "output doesn't match commitment"}

    # recompute U via the recomputation node (compute.score)
    argmax = call(COMPUTE_HOST, PORT_COMPUTE,
                  {"op": "score", "prompt": prompt_bytes.decode(errors="replace"),
                   "tokens": tokens})["argmax"]
    hit, miss = -math.log2(CONF), -math.log2((1 - CONF) / (VOCAB - 1))
    misses = sum(1 for p, t in zip(argmax, tokens) if p != t)
    U = len(tokens) * hit + misses * (miss - hit)
    return {"verified": True, "bound": True, "rid": binding["rid"],
            "U": U, "misses": misses, "n": len(tokens)}


if __name__ == "__main__":
    serve(PORT_VERIFIER, handler, "verifier")
