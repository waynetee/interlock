# Protocol reference model

Executable golden model of `docs/verification-protocol.md` (v5). Pure Python,
stdlib only. Intended as the reference that the FPGA gateware and a
performant prover frontend are tested against: every component speaks
serialized wire bytes, so a test vector here ("this packet stream in → this
certificate out") is byte-exact for any other implementation.

Run: `python3 test_protocol.py`

## Files (one per trust domain)

| File | Role | Spec section |
|---|---|---|
| `wire.py` | packet/record/certificate formats, the three hashing steps, stand-in cipher | Log format, Certificate format |
| `interlock.py` | the streaming state machine: validity rules, bucket hashing, per-second certificate, nonce latch | Roles: interlock |
| `frontend.py` | the log; derives hashes on demand; builds challenge openings; byte-audits certificates | Roles: prover frontend |
| `verifier.py` | anchor, challenge selection, opening checks (a)–(e), recomputation check (f). Its imports are the verifier's TCB | Challenge |
| `recomp.py` | Option 1: ingress gating on H1/H2, commit-then-reveal loop, Σq ≤ 1 check | Recomputation certificate |
| `test_protocol.py` | honest end-to-end run + one negative test per check | Properties P1–P4 |

`interlock.py` is written event-style (`on_packet` / `on_bucket_boundary` /
`on_second`) with fixed-size state, mirroring the planned gateware, so a
cocotb testbench can drive the RTL and this model with the same event
sequence and compare state at every boundary.

## Simplifications vs. the spec

- **Cipher:** SHA-256-keystream XOR (domain-separated per direction) instead
  of AES-CTR. Position-addressable like CTR, which is all the protocol uses.
  Swap point: `wire.encrypt`.
- **Bucket assignment** is passed to the frontend explicitly by the test
  driver instead of via in-stream boundary markers.
- **No wall clock:** anchor monotonicity is checked; counter-rate-vs-time and
  the 2× speedup bound are not modeled.
- **Probabilities are floats** (the spec suggests dyadic/fixed-point for
  hardware); the recomputation node is a toy deterministic function, not an
  LLM — model quality only affects the size of U, not what verifies.
- **Cut-and-choose certificate release** is not modeled (certificates are
  handed over directly).
