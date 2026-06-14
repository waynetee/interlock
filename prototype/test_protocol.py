"""Tests for the certificate/challenge layer (run: python3 test_protocol.py).

Covers the inference-time verification dataflow: the interlock's drop rules,
per-second certificates, and the verifier's opening checks — honest path plus one
negative per check. (Recomputation / U is a later step and not tested here.)
"""
import wire as W
from interlock import Interlock
from frontend import Frontend
from verifier import Verifier

MAC, IID, NONCE, KEY = W.H(b"mac"), 7, W.H(b"nonce")[:16], b"\x00" * 32
N = 50  # buckets per certificate (1000 in production; small here for readability)


def make_pair(rid, prompt_tokens, key, resp_tokens):
    in_ct = W.encrypt(key, b"in", W.tokens_to_bytes(prompt_tokens))
    out_ct = W.encrypt(key, b"out", W.tokens_to_bytes(resp_tokens))
    return W.input_packet(rid, key, in_ct), W.output_packet(rid, out_ct)


def run_second(il, fe, sched):
    for i in range(il.n):
        for d, pkt in sched.get(i, []):
            fwd = il.on_packet(d, pkt)
            if fwd is not None:
                fe.log_packet(il.bucket, d, fwd)
        il.on_bucket_boundary()
    cert = il.on_second()
    fe.log_certificate(cert)
    return cert


def honest_run(resp=(3681, 338, 278, 7483)):
    il = Interlock(MAC, IID, buckets_per_cert=N)
    fe = Frontend(IID, buckets_per_cert=N)
    ver = Verifier(MAC, IID, buckets_per_cert=N)
    key = W.H(b"pair-key")
    in_pkt, out_pkt = make_pair(1, [10, 20, 30], key, list(resp))
    run_second(il, fe, {3: [("in", in_pkt)]})       # request in second 0
    il.on_nonce(NONCE)
    cert = run_second(il, fe, {7: [("out", out_pkt)]})  # response in second 1
    assert fe.audit_certificate(cert, NONCE)
    assert ver.anchor(NONCE, cert) == 2 * N
    return il, fe, ver


def raises(fn):
    try:
        fn()
    except (AssertionError, KeyError, StopIteration):
        return True
    return False


def test_honest_end_to_end():
    _, fe, ver = honest_run()
    binding = ver.verify_opening(N + 7, 0, fe.open_challenge(N + 7, 0))
    assert binding["rid"] == 1


def test_empty_byte_and_empty_bucket():
    _, fe, _ = honest_run()
    assert Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
        N + 7, 99_000, fe.open_challenge(N + 7, 99_000)) is None
    assert Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
        N + 9, 0, fe.open_challenge(N + 9, 0)) is None


def test_interlock_drop_rules():
    il = Interlock(MAC, IID, s_max=100, buckets_per_cert=N)
    key = W.H(b"k")
    ok_in, ok_out = make_pair(5, [1], key, [2])
    assert il.on_packet("in", ok_in) is not None
    assert il.on_packet("in", ok_in) is None                       # replayed inbound id
    assert il.on_packet("in", W.input_packet(4, key, b"x")) is None  # non-monotonic
    assert il.on_packet("in", W.input_packet(6, key, bytes(101))) is None  # oversize
    assert il.on_packet("out", ok_out) is not None
    assert il.on_packet("out", ok_out) is None                     # non-monotonic in bucket
    il.on_bucket_boundary()
    assert il.on_packet("out", ok_out) is not None                 # comparator reset
    bad = ok_out[:3] + b"\xff" + ok_out[4:]
    assert il.on_packet("out", bad) is None                        # length field mismatch


def test_capacity_overflow_drops():
    il = Interlock(MAC, IID, capacity=100, buckets_per_cert=N)
    assert il.on_packet("out", W.output_packet(1, bytes(40))) is not None
    assert il.on_packet("out", W.output_packet(2, bytes(40))) is None


def test_tampered_log_rejected():
    _, fe, _ = honest_run()
    b, d, pkt = fe.log[1]
    fe.log[1] = (b, d, pkt[:-1] + bytes([pkt[-1] ^ 1]))
    assert raises(lambda: Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
        N + 7, 0, fe.open_challenge(N + 7, 0)))


def test_certificate_gap_rejected():
    _, fe, _ = honest_run()
    del fe.certs[0]                                # lose the second with the input
    assert raises(lambda: Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
        N + 7, 0, fe.open_challenge(N + 7, 0)))


def test_fabricated_input_rejected():
    _, fe, _ = honest_run()
    fake_in, _ = make_pair(1, [7, 7, 7], W.H(b"other-key"), [1])  # same id, other content
    fe.log[0] = (3, "in", fake_in)
    assert raises(lambda: Verifier(MAC, IID, buckets_per_cert=N).verify_opening(
        N + 7, 0, fe.open_challenge(N + 7, 0)))


def test_duplicate_response_rejected():
    il, fe, ver = honest_run()
    _, dup = make_pair(1, [10, 20, 30], W.H(b"pair-key"), [42, 42, 42, 42])
    il.on_nonce(NONCE)
    run_second(il, fe, {2: [("out", dup)]})       # second response, same request id
    assert ver.verify_opening(N + 7, 0, fe.open_challenge(N + 7, 0))["rid"] == 1
    assert raises(lambda: ver.verify_opening(2 * N + 2, 0,
                  fe.open_challenge(2 * N + 2, 0)))  # single-use of the id


def test_wrong_nonce_rejected():
    il = Interlock(MAC, IID, buckets_per_cert=N)
    fe = Frontend(IID, buckets_per_cert=N)
    ver = Verifier(MAC, IID, buckets_per_cert=N)
    cert = run_second(il, fe, {})                  # nonce register still zero
    assert raises(lambda: ver.anchor(NONCE, cert))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
