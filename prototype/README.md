# Prototype (V1 + V2 + recomputation), on real Llama-2-7B

Short, runnable demo of the earlier milestones from `docs/prototype-plan.md`,
reusing the reference model in `../model/protocol.py` for all certificate and
challenge logic.

## Files

| File | Role | Lines |
|---|---|---|
| `transport.py` | length-prefixed framing over a TCP socket | ~25 |
| `compute_server.py` | inference compute node: Llama-2-7B `gen` + `score` over TCP | ~80 |
| `run_demo.py` | orchestrator: V1 dataflow → V2 cert/challenge → recomputation U | ~120 |

## Run — single host (Spark, loopback)

```
cd ~/interlock-proto/prototype && ~/venv-hf/bin/python run_demo.py
```

`run_demo.py` uses **connect-or-spawn**: if nothing is already listening it
spawns `compute_server.py` as a subprocess (loads the model once, ~1 min),
then runs all three milestones and prints a transcript. See `RESULTS.md`.

## Run — two hosts (MacBook client → FPGA → Spark compute)

The same code, no edits — just point the client at the Spark and run the
compute node there. This is the natural topology for the FPGA loop: two real
hosts, so traffic between them genuinely traverses the FPGA (no netns / root
needed, unlike a single-Spark loop).

```
# on the Spark (compute node) — its FPGA-facing NIC enP7s7 is 10.10.10.2/24:
~/venv-hf/bin/python compute_server.py            # binds 0.0.0.0:5555

# on the MacBook (frontend/client) — plug into the FPGA's other port,
# set the NIC to e.g. 10.10.10.3/24, then:
COMPUTE_HOST=10.10.10.2 python3 run_demo.py
```

`run_demo` sees the server is already reachable and connects instead of
spawning. The **MacBook client needs only the Python standard library** plus
`model/protocol.py` and `prototype/` — no torch/transformers (all the model
work is server-side on the Spark). If the FPGA re-originates frame MACs and ARP
won't resolve across it, add a static ARP entry on each host (`arp -s <ip>
<mac>` on macOS, `ip neigh add` on Linux) — no namespaces required.

## What it shows

- **V1 — dataflow.** A request crosses a TCP socket to the compute node, which
  runs Llama and returns a response.
- **V2 — certificate + challenge logic.** The request/response traffic is run
  through the reference model's interlock (software), logged by the frontend,
  and a challenged packet is opened and verified; corrupting one logged byte is
  shown to be rejected.
- **recomputation — unexplained information U.** A real Llama recomputation
  scores per-token surprisal: ~0 bits for an honest response (the recomputation
  reproduces it exactly), hundreds of bits when the response is corrupted.

## What is real vs. simulated here

Real: the inference dataflow, the certificate/challenge logic, and the U
measurement, all on real hardware and a real model. Simulated (deliberately,
per the plan): loopback TCP stands in for the netns + FPGA loop (no root, no
FPGA dependency); certificate generation is software, so the hardware trust
boundary is not yet established; payloads are plaintext (encryption is V3); and
everything shares one OS, so isolation is not real. Decoding is greedy
(deterministic); the hardware-nondeterminism noise model is deferred.
