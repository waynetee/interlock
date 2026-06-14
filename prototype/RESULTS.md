# Prototype run results — 2026-06-14

Captured run of the V1 / V2 / recomputation milestones on the Spark
(`spark-c191`, aarch64, Llama-2-7B, `venv-hf` torch 2.13/cu130, transformers
5.8). Single-host over loopback TCP; see *FPGA / MacBook path* below for why the
physical FPGA loop wasn't exercised this run.

## Transcript

```
=== V1 dataflow ===
prompt           : 'Q: What is the capital of France?\nA:'
response (text)  : 'Paris is the capital of France.\nQ: What is the capital of France?\nA: Paris is the capital'
response (tokens): 24 ids

=== V2 certificate + challenge ===
certificate bytes: 140 ; anchored current bucket: 20
challenge (bucket 17, byte 0): VERIFIED, bound request_id=1
tampered packet: REJECTED (AssertionError) as expected

=== recomputation: unexplained information U ===
U(honest response)    =   0.035 bits  (0 of 24 tokens unexplained)
U(5 tokens corrupted) =   174.5 bits  (7 of 24 tokens unexplained)
ratio                 = 5039x
```

## Reading the results

- **V1** — a request crossed a TCP socket to the compute node, which ran
  Llama-2-7B and returned a correct answer ("Paris is the capital of France",
  then greedy repetition — expected for 24 greedy tokens with no chat template).
  The pipe works end to end.
- **V2** — the request/response traffic produced a 140-byte HMAC certificate;
  a randomly chosen challenge opened against it and verified, bound to the
  originating request; flipping one logged response byte made verification fail.
- **recomputation** — `U(honest) = 0.035 bits` is exactly 24 × −log₂(0.999):
  every token matched the recomputation's greedy prediction, so 0 of 24
  positions are unexplained — the "deterministic model → ~100% explained" case.
  Corrupting 5 tokens drives `U` to 174.5 bits over 7 unexplained positions
  (corruption propagates: the teacher-forced prefix is wrong for ~2 positions
  past the 5 edits). A 5000× separation between honest and corrupted output —
  the core P3 measurement, on a real model.

## What is real vs. simulated (per `docs/prototype-plan.md`)

Real: the inference dataflow, the certificate/challenge logic, and the U
measurement — on real hardware and a real model. Simulated by design at this
stage: loopback TCP stands in for the netns + FPGA loop; certificate generation
is software (no hardware trust boundary yet); payloads are plaintext (encryption
is V3); one OS hosts everything (isolation not real); decoding is greedy
(hardware-nondeterminism noise model deferred).

## FPGA / MacBook path (next step)

The FPGA is cabled to both Spark ports and forwarding. Interface state confirms
the hardware is ready:

- `enP7s7` (built-in eth) = **10.10.10.2/24**, UP — one FPGA port.
- `enxb8fbb3b1f53c` (USB-C eth) = UP, no IP — the other FPGA port.
- `wlP9s9` (WiFi) = default route + Tailscale — management.

This run did **not** traverse the FPGA: only the Spark sits on the 10.10.10.0/24
link (both ends), so exercising it would be a single-host loop, which needs root
(netns / raw sockets / policy routing) that the agent account lacks. The MacBook
case avoids this entirely — two real hosts, so traffic between them genuinely
crosses the FPGA.

Code is drop-in for that (`COMPUTE_HOST` / `COMPUTE_BIND`, connect-or-spawn):
run `compute_server.py` on the Spark (reachable at 10.10.10.2), plug the MacBook
into the FPGA's free port with a 10.10.10.x IP, and run
`COMPUTE_HOST=10.10.10.2 python3 run_demo.py` there. The MacBook client is pure
Python stdlib — no torch. Add static ARP if ARP won't cross the bridge.
