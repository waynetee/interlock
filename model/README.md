# Protocol reference model

Executable golden model of `docs/verification-protocol.md` (v5). Pure Python,
stdlib only, two files. Intended as the reference that the FPGA gateware and
a performant prover frontend are tested against: components exchange
serialized wire bytes, so a test vector here ("this packet stream in → this
certificate out") is byte-exact for any other implementation.

Run: `python3 test_protocol.py`

## Layout

`protocol.py` (~420 lines) holds everything, one section per component in
data-path order; the section banners mark the trust boundaries:

| Section | Trusted by | Spec section |
|---|---|---|
| Wire formats and hashes | shared definitions | Log format, Certificate format |
| Prover compute (`make_pair`) | nobody — its only contract is the bytes it emits | — |
| `Interlock` | verifier | Roles: interlock |
| `Frontend` | prover | Roles: prover frontend |
| `RecompInterlock` / `RecompNode` | verifier / prover (node runs in enclosure) | Recomputation certificate, Option 1 |
| `Verifier` | verifier — its methods are checks (a)–(f) | Challenge |

`test_protocol.py` is an honest end-to-end run plus one negative test per
check (tampered log, certificate gap, fabricated input, duplicate response,
drop rules, Σq ≤ 1, H2 ingress gate, nonce echo, covert output → large U).

`Interlock` is written event-style (`on_packet` / `on_bucket_boundary` /
`on_second`) with fixed-size state, mirroring the planned gateware, so a
cocotb testbench can drive the RTL and this model with the same event
sequence and compare state at every boundary.

## Simplifications vs. the spec

- **Cipher:** SHA-256-keystream XOR (domain-separated per direction) instead
  of AES-CTR. Position-addressable like CTR, which is all the protocol uses.
  Swap point: `protocol.encrypt`.
- **Bucket assignment** is passed to the frontend explicitly by the test
  driver instead of via in-stream boundary markers.
- **No wall clock:** anchor monotonicity is checked; counter-rate-vs-time and
  the 2× speedup bound are not modeled.
- **Probabilities are floats** (the spec suggests dyadic/fixed-point for
  hardware); the recomputation node runs a toy deterministic function, not an
  LLM — model quality only affects the size of U, not what verifies.
- **Cut-and-choose certificate release** is not modeled (certificates are
  handed over directly).
