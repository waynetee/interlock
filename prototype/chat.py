"""Interactive multi-turn Llama-2-7B chat over the verified-interlock prototype.

Type a message to chat. Commands:
  /challenge [id]   verify a response packet and report unexplained information U
  /tamper [id]      flip a byte in a logged response and show the challenge catches it
  /list             list the turns so far and their request ids
  /quit

Connects to compute_server at COMPUTE_HOST:COMPUTE_PORT (default 127.0.0.1:5555),
so the same client runs locally (loopback) or through the FPGA (in a macvlan
container). Each turn is logged as a request/response pair through the software
interlock, committed by a per-turn certificate; /challenge opens that commitment,
verifies it, and recomputes U for the response.
"""
import json
import math
import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "model"))
import protocol as P
from transport import send_msg, recv_msg

HOST = os.environ.get("COMPUTE_HOST", "127.0.0.1")
PORT = int(os.environ.get("COMPUTE_PORT", 5555))
KEY, MAC, IID, NONCE = b"\x00" * 32, P.H(b"interlock-key"), 7, P.H(b"nonce")[:16]
N, CONF, VOCAB = 8, 0.999, 32000   # buckets/cert, prediction confidence, vocab


def rpc(req):
    s = socket.create_connection((HOST, PORT))
    send_msg(s, json.dumps(req).encode())
    out = json.loads(recv_msg(s))
    s.close()
    return out


def ids_to_bytes(ids):
    return b"".join(i.to_bytes(4, "big") for i in ids)


def bytes_to_ids(b):
    return [int.from_bytes(b[i:i + 4], "big") for i in range(0, len(b), 4)]


def token_U(prompt, resp_ids):
    """Unexplained information: predict each token as the model's argmax with
    high confidence; matches cost ~0 bits, mismatches cost ~32. Returns (U, misses)."""
    preds = rpc({"op": "score", "prompt": prompt, "tokens": resp_ids})["argmax"]
    hit, miss = -math.log2(CONF), -math.log2((1 - CONF) / (VOCAB - 1))
    misses = sum(1 for p, t in zip(preds, resp_ids) if p != t)
    return len(resp_ids) * hit + misses * (miss - hit), misses


class Session:
    def __init__(self):
        self.il = P.Interlock(MAC, IID, buckets_per_cert=N)
        self.fe = P.Frontend(IID, buckets_per_cert=N)
        self.il.on_nonce(NONCE)
        self.history = []   # (user, assistant) text, for multi-turn context
        self.turns = {}     # rid -> {bucket, ids, text}
        self.rid = 0

    def prompt_for(self, user_msg):
        ctx = "".join(f"Q: {u}\nA: {a}\n" for u, a in self.history)
        return ctx + f"Q: {user_msg}\nA:"

    def say(self, user_msg):
        prompt = self.prompt_for(user_msg)
        gen = rpc({"op": "gen", "prompt": prompt, "max_new": 48})
        ids, text = gen["tokens"], gen["text"].split("\nQ:")[0].strip()
        self.rid += 1
        rid = self.rid
        self.fe.keys[rid] = KEY
        in_pkt = P.input_packet(rid, KEY, prompt.encode())
        out_pkt = P.output_packet(rid, ids_to_bytes(ids))
        start = self.il.bucket
        sched = {0: [("in", in_pkt)], 1: [("out", out_pkt)]}   # request, then response
        for i in range(N):
            for d, pkt in sched.get(i, []):
                fwd = self.il.on_packet(d, pkt)
                if fwd is not None:
                    self.fe.log_packet(self.il.bucket, d, fwd)
            self.il.on_bucket_boundary()
        self.fe.log_certificate(self.il.on_second())
        self.history.append((user_msg, text))
        self.turns[rid] = {"bucket": start + 1, "ids": ids, "text": text}
        return text, rid

    def challenge(self, rid):
        y = self.turns[rid]["bucket"]
        binding = P.Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
            y, 0, self.fe.open_challenge(y, 0))
        in_ct, _key, out_ct = self.fe.challenge_materials(rid)
        U, misses = token_U(in_ct.decode(errors="replace"), bytes_to_ids(out_ct))
        return binding, U, misses, len(self.turns[rid]["ids"])

    def tamper(self, rid):
        """Flip a byte in the logged response, re-challenge (expect failure), restore."""
        i = next(k for k, (b, d, p) in enumerate(self.fe.log)
                 if d == "out" and P.parse_packet("out", p)["request_id"] == rid)
        b, d, p = self.fe.log[i]
        self.fe.log[i] = (b, d, p[:-1] + bytes([p[-1] ^ 1]))
        y = self.turns[rid]["bucket"]
        try:
            P.Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
                y, 0, self.fe.open_challenge(y, 0))
            caught = False
        except Exception:
            caught = True
        self.fe.log[i] = (b, d, p)
        return caught


def main():
    print(f"[connected to compute node {HOST}:{PORT}]")
    print("chat with Llama; commands: /challenge [id], /tamper [id], /list, /quit\n")
    s = Session()
    while True:
        try:
            line = input("you> ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/list":
            for rid, t in s.turns.items():
                print(f"  #{rid}  bucket {t['bucket']}  {t['text'][:60]!r}")
            continue
        if line.startswith("/challenge") or line.startswith("/tamper"):
            parts = line.split()
            rid = int(parts[1]) if len(parts) > 1 else s.rid
            if rid not in s.turns:
                print("  no such turn (use /list)")
                continue
            if parts[0] == "/challenge":
                binding, U, misses, n = s.challenge(rid)
                print(f"  packet #{rid} VERIFIED (bound request_id={binding['rid']})")
                print(f"  unexplained information U = {U:.3f} bits  "
                      f"({misses}/{n} tokens unexplained)")
            else:
                print("  tamper caught ✓" if s.tamper(rid)
                      else "  TAMPER NOT DETECTED (bug)")
            continue
        text, rid = s.say(line)
        print(f"llama> {text}\n       [packet #{rid}]\n")


if __name__ == "__main__":
    main()
