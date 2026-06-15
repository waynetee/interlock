# Interlock Core — cocotb conformance harness

Tests the (future) gateware Core against the Python golden model in
`../../prototype` (`wire.py` + `interlock.py`). It drives the DUT and a Python
`Interlock` with the **same** events (packets, bucket ticks, nonce) and asserts
the emitted certificate is **byte-identical** — so the model is the checker and a
single cert-equality assertion transitively covers hashing, bucket/window
folding, cert assembly, and HMAC. Per-packet accept/drop is checked alongside, so
the drop rules are covered too.

- `test_interlock_core.py` — the harness (and, in its docstring, the **assumed
  Core port list** — the contract the RTL implements).
- `Makefile` — cocotb runner. The Core RTL is TBD; set `VERILOG_SOURCES` to it
  (and the SHA-256 blocks) once written, then `make` (default sim: verilator).

Develop the Core entirely against this in sim; flash only once it's green, then
re-run the same cert-byte comparison on the real device as the final gate
(remember: sim passing != silicon — see the deframe synth-vs-sim history).

The harness is **backend-agnostic** — it checks cert bytes, not how they're
produced. For the SHA-256 / HMAC source decision (secworks fabric core vs the
PolarFire User Crypto vs System Services), see
[`../../docs/gateware-crypto-backend.md`](../../docs/gateware-crypto-backend.md).
