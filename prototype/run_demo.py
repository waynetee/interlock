"""End-to-end prototype of the earlier milestones, on real Llama-2-7B.

  V1  dataflow:   a request crosses a TCP socket to the compute node, which
                  runs Llama and returns a response.
  V2  cert/logic: the traffic is run through the reference model's interlock
                  (software), logged by the frontend, and a challenged packet
                  is opened and verified; tampering is shown to be caught.
  recomp:         unexplained information U is scored by a real Llama
                  recomputation — small for an honest response, large when
                  the response is corrupted.

Loopback TCP stands in for the netns + FPGA loop (no root / no FPGA needed
here); cert generation is software, so this validates dataflow and logic,
not the hardware trust boundary. See docs/prototype-plan.md.
"""
import json
import math
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "model"))
import protocol as P
from transport import send_msg, recv_msg

# Point the client at a remote compute node (e.g. the Spark, reached through
# the FPGA from a MacBook) by setting COMPUTE_HOST; default is local loopback.
HOST = os.environ.get("COMPUTE_HOST", "127.0.0.1")
PORT = int(os.environ.get("COMPUTE_PORT", 5555))
KEY = b"\x00" * 32
MAC, IID = P.H(b"interlock-key"), 7
NONCE = P.H(b"nonce")[:16]
N = 10                       # buckets per certificate (small for the demo)
CONF, VOCAB = 0.999, 32000   # prediction confidence and Llama vocab size


def rpc(req):
    s = socket.create_connection((HOST, PORT))
    send_msg(s, json.dumps(req).encode())
    out = json.loads(recv_msg(s))
    s.close()
    return out


def ids_to_bytes(ids):
    return b"".join(i.to_bytes(4, "big") for i in ids)


def run_buckets(ilock, fe, sched):
    """Push one second of scheduled packets through the interlock -> certificate."""
    for i in range(ilock.n):
        for d, pkt in sched.get(i, []):
            fwd = ilock.on_packet(d, pkt)
            if fwd is not None:
                fe.log_packet(ilock.bucket, d, fwd)
        ilock.on_bucket_boundary()
    cert = ilock.on_second()
    fe.log_certificate(cert)
    return cert


def token_U(prompt, resp_ids):
    """U = sum of per-token surprisals under a near-deterministic prediction:
    the recomputation predicts each token as the model's argmax with high
    confidence, so a matching token costs ~0 bits and a mismatch costs many.
    Returns (U_bits, number_of_unexplained_positions)."""
    preds = rpc({"op": "score", "prompt": prompt, "tokens": resp_ids})["argmax"]
    hit, miss = -math.log2(CONF), -math.log2((1 - CONF) / (VOCAB - 1))
    misses = sum(1 for p, t in zip(preds, resp_ids) if p != t)
    return len(resp_ids) * hit + misses * (miss - hit), misses


def main():
    # ---- V1: dataflow through the TCP socket to the Llama compute node ----
    prompt = "Q: What is the capital of France?\nA:"
    gen = rpc({"op": "gen", "prompt": prompt, "max_new": 24})
    resp_ids = gen["tokens"]
    print("=== V1 dataflow ===")
    print("prompt           :", repr(prompt))
    print("response (text)  :", repr(gen["text"]))
    print("response (tokens): %d ids" % len(resp_ids))

    # ---- V2: build packets, run the interlock / frontend / verifier ----
    ilock = P.Interlock(MAC, IID, buckets_per_cert=N)
    fe = P.Frontend(IID, buckets_per_cert=N)
    ver = P.Verifier(MAC, IID, buckets_per_cert=N)
    rid = 1
    fe.keys[rid] = KEY
    in_pkt = P.input_packet(rid, KEY, prompt.encode())
    out_pkt = P.output_packet(rid, ids_to_bytes(resp_ids))
    run_buckets(ilock, fe, {3: [("in", in_pkt)]})       # request in second 0
    ilock.on_nonce(NONCE)
    cert = run_buckets(ilock, fe, {7: [("out", out_pkt)]})  # response in second 1
    assert fe.audit_certificate(cert, NONCE), "prover-side certificate audit failed"
    B = ver.anchor(NONCE, cert)
    print("\n=== V2 certificate + challenge ===")
    print("certificate bytes:", len(cert), "; anchored current bucket:", B)
    y = N + 7
    binding = ver.verify_opening(y, 0, fe.open_challenge(y, 0))
    print(f"challenge (bucket {y}, byte 0): VERIFIED, bound request_id={binding['rid']}")

    # negative control: corrupt one logged response byte, re-challenge
    b, d, pkt = fe.log[1]
    fe.log[1] = (b, d, pkt[:-1] + bytes([pkt[-1] ^ 1]))
    try:
        v2 = P.Verifier(MAC, IID, buckets_per_cert=N)
        v2.anchor(NONCE, cert)
        v2.verify_opening(y, 0, fe.open_challenge(y, 0))
        print("tampered packet: NOT DETECTED  <-- bug")
    except Exception as e:
        print(f"tampered packet: REJECTED ({type(e).__name__}) as expected")
    fe.log[1] = (b, d, pkt)

    # ---- recomputation: unexplained information, honest vs corrupted ----
    print("\n=== recomputation: unexplained information U ===")
    u_honest, m_honest = token_U(prompt, resp_ids)
    corrupt = resp_ids[:]
    for j in range(min(5, len(corrupt))):
        corrupt[j] = (corrupt[j] + 1000) % VOCAB
    u_corrupt, m_corrupt = token_U(prompt, corrupt)
    print(f"U(honest response)    = {u_honest:7.3f} bits  ({m_honest} of {len(resp_ids)} tokens unexplained)")
    print(f"U(5 tokens corrupted) = {u_corrupt:7.1f} bits  ({m_corrupt} of {len(corrupt)} tokens unexplained)")
    print(f"ratio                 = {u_corrupt / max(u_honest, 1e-9):.0f}x")


def reachable():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    # Connect-or-spawn: if a compute node is already listening (e.g. the Spark,
    # reached from a MacBook through the FPGA) use it; otherwise spawn one
    # locally for a single-host demo. Same code path either way.
    server = None
    if not reachable():
        server = subprocess.Popen([sys.executable,
                                   os.path.join(os.path.dirname(__file__), "compute_server.py")])
        for _ in range(180):                 # wait for model load + listen
            if reachable():
                break
            time.sleep(1)
    try:
        print(f"compute node: {HOST}:{PORT}\n")
        main()
    finally:
        if server is not None:
            server.terminate()
