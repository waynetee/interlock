"""Prover frontend — the log + challenge openings, and the interactive chat CLI.
   [diagram: Prover frontend]

Originates requests, stores the certified packets + certificates, and builds
challenge openings from them. As a process it's the chat client: connects to the
interlock for the data path and to the verifier for challenges.
"""
from wire import *                       # noqa: F401,F403 - the wire vocabulary
from common import (call, KEY, IID, NONCE, N, HOST,
                    PORT_INTERLOCK, PORT_VERIFIER, opening_to_json)


class Frontend:
    """Stores forwarded packets (with their bucket) + certificates; recomputes
    derived hashes from the log on demand to build a challenge opening."""

    def __init__(self, interlock_id, buckets_per_cert=1000):
        self.interlock_id, self.n = interlock_id, buckets_per_cert
        self.log = []     # (bucket, direction, packet_bytes), forwarded packets only
        self.certs = {}   # bucket_start -> certificate bytes

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
        """Opening for byte x of output bucket y."""
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


# --- chat client (the customer + prover frontend, interactive) --------------

fe = Frontend(IID, buckets_per_cert=N)
history, turns, state = [], {}, {"rid": 0}


def prompt_for(msg):
    ctx = "".join(f"Q: {u}\nA: {a}\n" for u, a in history)
    return ctx + f"Q: {msg}\nA:"


def say(msg):
    state["rid"] += 1
    rid = state["rid"]
    req_pkt = input_packet(rid, KEY, prompt_for(msg).encode())
    r = call(HOST, PORT_INTERLOCK, {"op": "turn", "request_packet": req_pkt.hex()})
    resp_pkt = bytes.fromhex(r["response_packet"])
    fe.log_packet(r["req_bucket"], "in", req_pkt)
    fe.log_packet(r["resp_bucket"], "out", resp_pkt)
    cert = bytes.fromhex(r["certificate"])
    fe.log_certificate(cert)
    assert fe.audit_certificate(cert, NONCE), "certificate is not a function of the log"
    text = r["text"].split("\nQ:")[0].strip()
    history.append((msg, text))
    turns[rid] = r["resp_bucket"]
    return text, rid


def challenge(rid):
    return call(HOST, PORT_VERIFIER,
                {"op": "challenge", "opening": opening_to_json(fe.open_challenge(turns[rid], 0))})


def main():
    print("[frontend] chat with Llama — commands: /challenge [id], /list, /quit\n")
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
            for rid, y in turns.items():
                print(f"  #{rid}  response bucket {y}")
            continue
        if line.startswith("/challenge"):
            parts = line.split()
            rid = int(parts[1]) if len(parts) > 1 else state["rid"]
            if rid not in turns:
                print("  no such turn (use /list)")
                continue
            r = challenge(rid)
            if r.get("verified"):
                print(f"  packet #{r.get('rid', rid)} VERIFIED — it is the committed "
                      f"response to request #{r.get('rid', rid)}")
            else:
                print(f"  REJECTED: {r.get('reason', r.get('error'))}")
            continue
        text, rid = say(line)
        print(f"llama> {text}\n       [packet #{rid}]\n")


if __name__ == "__main__":
    main()
