"""End-to-end run plus one negative test per verifier/interlock check.

Run with: python3 test_protocol.py
"""
import random

from protocol import (H, input_packet, output_packet, make_pair, Interlock,
                      Frontend, Verifier, RecompInterlock, RecompNode,
                      run_challenge)

N = 50  # buckets per certificate (1000 in production; small here for readability)
ILOCK_KEY, ILOCK_ID = H(b"interlock-key"), 7
RECOMP_KEY, RECOMP_ID = H(b"recomp-key"), 8
NONCE, CHALLENGE_NONCE = H(b"nonce")[:16], H(b"challenge")[:16]


def declared_d(prompt_tokens):
    """Toy stand-in for the declared computation (an LLM in the real system)."""
    return [(sum(prompt_tokens) + 7 * i) % 2**16 for i in range(8)]


def run_second(ilock, fe, schedule):
    """schedule: {bucket_offset: [(direction, packet), ...]} for one second."""
    for i in range(ilock.n):
        for direction, pkt in schedule.get(i, []):
            fwd = ilock.on_packet(direction, pkt)
            if fwd is not None:
                fe.log_packet(ilock.bucket, direction, fwd)
        ilock.on_bucket_boundary()
    cert = ilock.on_second()
    fe.log_certificate(cert)
    return cert


def honest_run(respond=declared_d):
    """Two seconds of traffic: request in second 0, response in second 1 (bucket N+7)."""
    ilock = Interlock(ILOCK_KEY, ILOCK_ID, buckets_per_cert=N)
    fe = Frontend(ILOCK_ID, buckets_per_cert=N)
    ver = Verifier(ILOCK_KEY, ILOCK_ID, RECOMP_KEY, RECOMP_ID, buckets_per_cert=N)
    key = H(b"pair-key")
    in_pkt, out_pkt = make_pair(1, [10, 20, 30], key, respond)
    fe.keys[1] = key
    run_second(ilock, fe, {3: [("in", in_pkt)]})
    ilock.on_nonce(NONCE)
    cert = run_second(ilock, fe, {7: [("out", out_pkt)]})
    assert fe.audit_certificate(cert, NONCE)  # cert body == deterministic fn of log
    current = ver.anchor(NONCE, cert)
    assert current == 2 * N
    return ilock, fe, ver


def challenge(fe, ver, y, x):
    return run_challenge(ver, fe, RecompInterlock(RECOMP_KEY, RECOMP_ID),
                         RecompNode(declared_d), y, x, CHALLENGE_NONCE)


def raises(fn):
    try:
        fn()
    except (AssertionError, KeyError, StopIteration):
        return True
    return False


# --- tests -------------------------------------------------------------------

def test_honest_end_to_end():
    _, fe, ver = honest_run()
    u = challenge(fe, ver, N + 7, 0)        # byte 0 of the response packet
    assert u is not None and u < 0.1        # ~0.0014 bits/token honest overhead


def test_empty_byte_and_empty_bucket():
    _, fe, ver = honest_run()
    assert challenge(fe, ver, N + 7, 99_000) is None  # past the bucket's content
    assert challenge(fe, ver, N + 9, 0) is None       # empty bucket
    random.seed(0)                                    # random sampling never errors
    for _ in range(20):
        challenge(fe, ver, *ver.select(random, 2 * N, window=2 * N))


def test_covert_output_detected():
    _, fe, ver = honest_run(respond=lambda p: [99] * 8)  # output not explained by D(x)
    assert challenge(fe, ver, N + 7, 0) > 30             # ~42 bits per unexplained unit


def test_interlock_drop_rules():
    ilock = Interlock(ILOCK_KEY, ILOCK_ID, s_max=100, buckets_per_cert=N)
    key = H(b"k")
    ok_in, ok_out = make_pair(5, [1], key, declared_d)
    assert ilock.on_packet("in", ok_in) is not None
    assert ilock.on_packet("in", ok_in) is None                      # replayed inbound ID
    assert ilock.on_packet("in", input_packet(4, key, b"x")) is None  # non-monotonic inbound
    big = input_packet(6, key, bytes(101))
    assert ilock.on_packet("in", big) is None                        # oversize
    assert ilock.on_packet("out", ok_out) is not None
    assert ilock.on_packet("out", ok_out) is None                    # non-monotonic in bucket
    ilock.on_bucket_boundary()
    assert ilock.on_packet("out", ok_out) is not None                # comparator reset
    bad_len = ok_out[:3] + b"\xff" + ok_out[4:]
    assert ilock.on_packet("out", bad_len) is None                   # length field mismatch


def test_capacity_overflow_drops():
    ilock = Interlock(ILOCK_KEY, ILOCK_ID, capacity=100, buckets_per_cert=N)
    a = output_packet(1, bytes(40))
    b = output_packet(2, bytes(40))
    assert ilock.on_packet("out", a) is not None
    assert ilock.on_packet("out", b) is None  # would exceed bucket capacity


def test_tampered_log_rejected():
    _, fe, ver = honest_run()
    b, d, pkt = fe.log[1]                       # the response packet
    fe.log[1] = (b, d, pkt[:-1] + bytes([pkt[-1] ^ 1]))
    assert raises(lambda: challenge(fe, ver, N + 7, 0))


def test_certificate_gap_rejected():
    _, fe, ver = honest_run()
    del fe.certs[0]                             # lose the second containing the input
    assert raises(lambda: challenge(fe, ver, N + 7, 0))


def test_fabricated_input_rejected():
    _, fe, ver = honest_run()
    fake_in, _ = make_pair(1, [7, 7, 7], H(b"other-key"), declared_d)
    fe.log[0] = (3, "in", fake_in)              # same ID, different content
    fe.keys[1] = H(b"other-key")
    assert raises(lambda: challenge(fe, ver, N + 7, 0))


def test_duplicate_response_rejected():
    ilock, fe, ver = honest_run()
    key = fe.keys[1]
    _, dup = make_pair(1, [10, 20, 30], key, lambda p: [42] * 8)
    ilock.on_nonce(NONCE)
    run_second(ilock, fe, {2: [("out", dup)]})  # second response, same request ID
    assert challenge(fe, ver, N + 7, 0) is not None
    assert raises(lambda: challenge(fe, ver, 2 * N + 2, 0))  # single use of the ID


def test_recomp_ingress_and_sum_checks():
    _, fe, ver = honest_run()
    binding = ver.verify_opening(N + 7, 0, fe.open_challenge(N + 7, 0))
    in_ct, key, out_ct = fe.challenge_materials(binding["rid"])
    ri = RecompInterlock(RECOMP_KEY, RECOMP_ID)
    args = (CHALLENGE_NONCE, binding["h1_in"], binding["h2"])
    assert ri.run(*args, in_ct, H(b"wrong-key"), out_ct, RecompNode(declared_d)) is None

    class CheatNode(RecompNode):                 # claims prob 1 for many units
        def commit(self):
            return {i.to_bytes(4, "big"): 1.0 for i in range(4)}
    assert ri.run(*args, in_ct, key, out_ct, CheatNode(declared_d)) is None


def test_wrong_nonce_rejected():
    ilock = Interlock(ILOCK_KEY, ILOCK_ID, buckets_per_cert=N)
    fe = Frontend(ILOCK_ID, buckets_per_cert=N)
    ver = Verifier(ILOCK_KEY, ILOCK_ID, RECOMP_KEY, RECOMP_ID, buckets_per_cert=N)
    cert = run_second(ilock, fe, {})            # nonce register still zero
    assert raises(lambda: ver.anchor(NONCE, cert))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
