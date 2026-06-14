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

## Run — single host (loopback, no FPGA)

```
MOCK=1 ./run_all.sh     # wiring test, no Llama (canned compute)
./run_all.sh            # real Llama-2-7B, all four nodes on this host
```

## Run — over the FPGA

The FPGA can't sit in a single-host loop (the kernel loopback-shortcuts past it).
Split it: **compute on the host's built-in-NIC side**, the **client nodes in a
macvlan container on the USB-NIC side**, so their calls to compute cross the FPGA.

```
# on the Spark host (built-in NIC = 10.10.10.2), with torch:
cd ~/interlock-proto/prototype/nodes && ~/venv-hf/bin/python compute.py

# client nodes in a container on the USB-NIC side:
docker run -it --rm --network fpga_net --ip 10.10.10.3 -e COMPUTE_HOST=10.10.10.2 \
  -v ~/interlock-proto:/proto python:3-slim bash /proto/prototype/nodes/run_clients.sh
```

`interlock → compute` and `verifier → compute` then traverse the FPGA. Note the
FPGA is the **transparent passthrough wire** on those legs; `interlock.py` is
still the logical interlock doing the certificate logic in software — moving that
logic into the gateware is the later V3b step.

Status: this topology is validated end-to-end with a **mock compute**
(`MOCK=1 python3 compute.py` on the host) — chat turns + `/challenge` ran with
the compute legs crossing the FPGA (interface counters matched, `usb_tx == enP7s7_rx`).
The only remaining step for a real run is swapping the mock for real Llama
(`~/venv-hf/bin/python compute.py`), which just needs GPU memory headroom.

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
