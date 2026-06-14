"""Prover frontend — originates requests, stores the log, drives challenges.
   [diagram: Prover frontend]   Also the interactive chat CLI (the customer).

Connects to the interlock for the data path (frontend -> interlock -> compute) and
to the verifier for challenges. Holds the prover's log + certificates and builds
challenge openings from them.
"""
from common import (P, call, KEY, IID, N, HOST, PORT_INTERLOCK, PORT_VERIFIER,
                    ids_to_bytes, bytes_to_ids, opening_to_json)

fe = P.Frontend(IID, buckets_per_cert=N)
history = []          # (user, assistant) text, for multi-turn context
turns = {}            # rid -> response bucket
state = {"rid": 0}


def prompt_for(msg):
    ctx = "".join(f"Q: {u}\nA: {a}\n" for u, a in history)
    return ctx + f"Q: {msg}\nA:"


def say(msg):
    state["rid"] += 1
    rid = state["rid"]
    fe.keys[rid] = KEY
    req_pkt = P.input_packet(rid, KEY, prompt_for(msg).encode())
    r = call(HOST, PORT_INTERLOCK, {"op": "turn", "request_packet": req_pkt.hex()})
    resp_pkt = bytes.fromhex(r["response_packet"])
    # store the certified packets (buckets assigned by the interlock) + the certificate
    fe.log_packet(r["req_bucket"], "in", req_pkt)
    fe.log_packet(r["resp_bucket"], "out", resp_pkt)
    fe.log_certificate(bytes.fromhex(r["certificate"]))
    text = r["text"].split("\nQ:")[0].strip()
    history.append((msg, text))
    turns[rid] = r["resp_bucket"]
    return text, rid


def challenge(rid):
    """Open the response packet's commitment and hand it (plus recomputation
    materials) to the verifier; return the verifier's verdict."""
    op = fe.open_challenge(turns[rid], 0)
    in_ct, _key, out_ct = fe.challenge_materials(rid)
    return call(HOST, PORT_VERIFIER, {"op": "challenge",
                "opening": opening_to_json(op),
                "prompt": in_ct.hex(), "tokens": bytes_to_ids(out_ct)})


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
            if not r.get("verified"):
                print(f"  REJECTED: {r.get('reason', r.get('error'))}")
            elif not r.get("bound"):
                print(f"  certificate ok, but {r.get('reason')}")
            else:
                print(f"  packet #{r['rid']} VERIFIED — U = {r['U']:.3f} bits "
                      f"({r['misses']}/{r['n']} tokens unexplained)")
            continue
        text, rid = say(line)
        print(f"llama> {text}\n       [packet #{rid}]\n")


if __name__ == "__main__":
    main()
