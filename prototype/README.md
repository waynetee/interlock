# Prototype (V1 + V2 + recomputation), on real Llama-2-7B

Short, runnable demo of the earlier milestones from `docs/prototype-plan.md`,
reusing the reference model in `../model/protocol.py` for all certificate and
challenge logic.

Two flavors:
- **`run_demo.py` / `chat.py`** (this folder) — compact, single process: one
  orchestrator instantiates the interlock/frontend/verifier objects and talks to
  `compute_server.py`. This is what the FPGA demo runs.
- **`nodes/`** — node-per-process: each design node (compute, interlock,
  frontend, verifier) is its own process talking over TCP, so the code maps
  one-to-one to the diagram. Start there to understand the node boundaries.

## Files

| File | Role | Lines |
|---|---|---|
| `transport.py` | length-prefixed framing over a TCP socket | ~25 |
| `compute_server.py` | inference compute node: Llama-2-7B `gen` + `score` over TCP | ~80 |
| `run_demo.py` | scripted orchestrator: V1 dataflow → V2 cert/challenge → recomputation U | ~120 |
| `chat.py` | interactive multi-turn chat + `/challenge` any past packet | ~150 |

## Interactive chat

`chat.py` is a CLI: hold a multi-turn Llama conversation, and challenge any past
response on demand. Start `compute_server.py` first, then:

```
# on the host (loopback):
cd ~/interlock-proto/prototype && python3 chat.py
# over the FPGA (client in a macvlan container on the USB port):
docker run -it --rm --network fpga_net --ip 10.10.10.3 -e COMPUTE_HOST=10.10.10.2 \
  -v ~/interlock-proto:/proto python:3-slim python3 /proto/prototype/chat.py
```

Commands: type a message to chat; `/challenge [id]` verifies a response packet
and prints its unexplained information U; `/tamper [id]` shows the challenge
catches a flipped byte; `/list` shows turns; `/quit`. Each turn is logged as a
request/response pair through the software interlock with a per-turn certificate.
(`chat.py` needs only the Python stdlib — no torch — so the container client is
`python:3-slim`.)

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
