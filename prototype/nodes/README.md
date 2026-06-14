# Node-per-process prototype

The same prototype as the parent folder, but with **each node from the design as
its own process**, talking over TCP — so the code maps one-to-one to the diagram
instead of being objects inside one orchestrator. Use this to understand the node
boundaries; use `../run_demo.py` / `../chat.py` for the compact single-process
version (what the FPGA demo runs).

## Files → diagram nodes

| File | Diagram node | Trust | Role |
|---|---|---|---|
| `compute.py` | **Prover compute** (+ recomputation engine) | prover, untrusted | runs the LLM: `workload` (packet→packet) and `score` (for U) |
| `interlock.py` | **Verifier interlock** | verifier-trusted, in the data path | forwards each turn to compute, hashes packets, emits the per-turn certificate |
| `frontend.py` | **Prover frontend** (+ the chat CLI) | prover | originates requests, stores the log + certs, builds challenge openings |
| `verifier.py` | **External verifier** | verifier | checks the opening against the certificate and recomputes U |
| `common.py` | — | — | shared transport, ports, (de)serialization; node logic still from `../../model/protocol.py` |

## Wiring

```
  workload (data path):   frontend ──► interlock ──► compute
  challenge:              frontend ──► verifier ──► compute (score, for U)
```

- `frontend` is a pure client (to `interlock` and `verifier`).
- `compute`, `interlock`, `verifier` are servers; `interlock` and `verifier` are
  also clients to `compute`.
- The certificate is produced *in the data path* by `interlock` and stored by
  `frontend` — unlike the single-process version, the interlock is genuinely a
  separate in-path process here.

## Run

```
MOCK=1 ./run_all.sh     # wiring test, no Llama (canned compute)
./run_all.sh            # real Llama-2-7B on this host
COMPUTE_HOST=10.10.10.2 ./run_all.sh   # compute reached through the FPGA
```

Then chat; `/challenge [id]` verifies a past response and reports its unexplained
information U; `/list`; `/quit`.

## What's faithful vs. simplified

- **Faithful:** four separate processes with real socket boundaries; the
  interlock is in the data path and the only holder (with the verifier) of the
  MAC key; the verifier recomputes U itself and binds the recomputation materials
  to the certificate's committed hashes (`H(prompt)==h1_in`, `H(tokens)==h1_out`)
  — it never trusts a prover-supplied U.
- **Simplified (plaintext prototype):** payloads aren't encrypted, so the
  recomputation materials cross to the verifier in the clear (confidentiality is
  the V3/recomputation-option work); the recomputation reuses the `compute`
  process rather than a separate enclosed node; the interlock certifies the turn
  after forwarding rather than strictly inline.
