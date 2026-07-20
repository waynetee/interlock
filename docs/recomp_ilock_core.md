# Recomputation Interlock Core Design Specification

This document describes the **recomputation interlock core** (`recomp_ilock_core.sv`) — implementing the recomputation interlock of `verification-protocol.md`: it mediates everything crossing the recomputation-enclosure boundary, commits the staged challenge slice, runs the estimate/reveal loop, and attests the result. Block internals live in their own docs.

```
                                                        ┌───────────┐
                                                        │   bucket  │
                                                        │   timer   │
                                                        └───────────┘
  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ┬  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──  ──
(x,o) in                                       outside region   inside region
                                                              │
        ┌──────────┐  ┌────────────┐    ┌────────────┐  ┌───────────┐    ┌────────────┐  ┌──────────┐
MAC0──▶ │   eth    │─▶│ canon proc │───▶│   traffic  │─▶│  buc│ket  │───▶│  recomp    │─▶│   eth    │──▶ MAC1
FIFO    │ deframe  │  │ + drop*    │    │   commit   │  │  buf fer  │    │  feed      │  │ reframe  │    FIFO
        └──────────┘  └────────────┘    └──────┬─────┘  └─────│─────┘    └─────┬──────┘  └──────────┘
tuser:                      │      len@beat#0  │  len@beat#0       len@beat#0  │  ▲  len@beat#0
                            │     swap(inline) │ swap(inline) │                │  │
                           s│                  │                               │  │
                           y│                  │              │                │  │
                           n│                  │  ┌────────────────────────────┘  │
                           c│                  │  │           │                   │
(m,τ) out                   │                  │  │                               │
                            │                  │  │           │                   │
                            ▼                  ▼  ▼                               │
        ┌──────────┐  ┌────────────┐    ┌───────────┐         │                   │      ┌──────────┐
MAC0◀── │   eth    │◀─│  2×1 mux   │◀───│   cert    │                             └──────│   eth    │◀── MAC1
FIFO    │ reframe  │  │            │    │   build   │         │                          │ deframe  │    FIFO
        └──────────┘  └────────────┘    └───────────┘                                    └──────────┘
tuser:           len@beat#0                                   │

* drop: a separate axis_pkt_gate after canon proc
```

## Deployment — bump on the enclosure boundary

Port 0 faces the **prover frontend**, port 1 the **recomputation enclosure**; forced station addresses (frontend `.01`, compute `.02`), one fabric clock, MAC FIFOs handle the line-side CDC. There is **one processed direction**: the challenge slice flows 0 → 1 through the full pipeline, while the return path (1 → 0) carries only estimate frames, consumed whole by `recomp_feed` — nothing from the enclosure is ever forwarded to the frontend. The frontend-bound egress carries exactly two streams: certificates and sync packets.

The frontend's side of the contract:

- stage the challenge slice as canonical packets — the context, then the **CTRL marker** (a header-only `ID = 0` packet), then the challenged response — and keep any other `ID = 0` packet out of the slice;
- carry the **challenge nonce** in the CTRL marker's `KEY_COMMIT` field: the same packet arms the response capture and latches the nonce for the certificate;
- stamp the **current bucket** — sync packets arrive back on port 0 for calibration, and bucket integrity gates admission;
- hold staging while a challenge runs: packets arriving mid-challenge are committed upstream but dropped whole by the feed, so a violation reads as lost packets in the digest, never as corrupted framing;

## Ingress path

The ingress is `deframe → canon_proc → drop gate → traffic_commit → batch_buffer` — so the slice is checked, committed, and bucketed exactly as the original traffic was. That reuse is what makes the slice commitment comparable: the verifier recomputes the same hierarchy from the opened production records and checks equality (see the protocol's Option 1).

## Recomputation loop

```
TODO handle drop flag from estimate eth_deframe
```
`recomp_feed` forwards context packets verbatim to the enclosure-facing reframe, the CTRL marker forwards too (it is the recomputation START trigger), and the challenged response is captured and fed back token-by-token against the enclosure's estimates, accumulating `Û`. The estimate return path is port 1's deframe feeding the estimate port directly; its truncation flag is unused — a malformed estimate frame is charged `PROB_MIN` regardless.

## Attestation and egress

A single `cert_build` runs with `RSP_SYNC = 0`: certificates follow the ingress digest cadence — INWARD carries the challenge-slice commitment, OUTWARD the last-dispatched `(id ‖ Û)` (zero before the first challenge, stale between) — and NONCE echoes the CTRL marker's `KEY_COMMIT`. The frontend egress is prod's mux with the packet input tied off: certificates on the default grant, sync packets on the priority input, reframed toward port 0. The device keeps the production timeline machinery — buckets, sync, certificate tiling — by decision; the protocol pins this layout and moves the H1/H2 checks to the verifier.

## Shared bucket clock

A single free-running timer paces the whole device: `TIMER_END = 79_999` → a 1 ms bucket at the 80 MHz fabric clock, `BKTS_PER_CERT = 1000` → one certificate per second. Its tick fans out to canon (bucket check, marker insertion, sync emission) and buffer (bank swap); every bucket index in the device derives from this one counter. The buffers' grace periods absorb upstream tail: 2000 cycles.
