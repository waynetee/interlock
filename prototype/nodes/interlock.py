"""Verifier interlock — sits in the data path.   [diagram: Verifier interlock]

Trusted by the verifier (holds the shared MAC key). The frontend connects here;
for each turn the interlock forwards the request to compute, hashes the
request/response packets, advances its hash-chain/bucket state, and emits a
per-turn certificate that it returns to the frontend (the prover stores it).
The interlock never originates or interprets payloads — it forwards and certifies.
"""
from common import (P, call, serve, MAC, IID, NONCE, N,
                    COMPUTE_HOST, PORT_COMPUTE, PORT_INTERLOCK)

il = P.Interlock(MAC, IID, buckets_per_cert=N)
il.on_nonce(NONCE)


def handler(req):
    if req["op"] != "turn":
        return {"error": "unknown op"}
    req_pkt = bytes.fromhex(req["request_packet"])
    # forward through to compute, get the response packet back
    r = call(COMPUTE_HOST, PORT_COMPUTE,
             {"op": "workload", "request_packet": req_pkt.hex(), "max_new": req.get("max_new", 48)})
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


if __name__ == "__main__":
    serve(PORT_INTERLOCK, handler, "interlock")
