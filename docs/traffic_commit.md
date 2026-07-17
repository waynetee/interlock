# Traffic Commitment Block Design Specification

This document describes the **traffic commitment block** — the attestation layer of the path, one instance per direction. It forwards each accepted packet verbatim toward the wire while folding it through a **layered hash hierarchy**, and emits, once per certificate period, a single 256-bit **overall digest** committing to all the traffic of that period in its direction.  The hierarchy, field names, and cadence follow the **Interlock Verification Protocol** (`verification-protocol.md`).

```
                       ┌──────────────────┐
  AXIS in ───────────▶ │                  │ ──▶ AXIS out
  swap(inline)         │  traffic_commit  │     swap(inline) (if OUTPUT_SWAP == 1)
                       │                  │ ──▶ overall[255:0]
                       └──────────────────┘
```

A packet arriving at the commitment block is, by construction, an **accepted** packet — the block neither checks nor drops; it commits exactly what it forwards. `tuser` is **passed through verbatim** and never read; the record lengths it commits come from its own streaming byte counter. A **bucket boundary** arrives as a standalone **empty beat** (`tkeep = 0`, `tlast`) between packets; it closes the current bucket hash and is not itself folded in. Whether that empty beat is re-emitted on the data master is set by the `OUTPUT_SWAP` parameter.

Note: the design assumes that the packet headers fit within a single hash input block (512 bits).

## Pass-through — commit what you emit

Each packet streams out unchanged: data in equals data out, beat for beat. An `axis_splitter` **forks** the packet stream — one copy is the verbatim pass-through that drives the data master, the other is the hash branch. Every packet byte that leaves on the data port is also the byte the hierarchy commits, and nothing else is: the commitment is a **tap** on the emitted stream, so a packet is committed if and only if it is forwarded. Certificates leave on the **separate port**.

The split between **header** and **payload** is fixed at `HDR_BYTES` and needs no parsing: the first `HDR_BYTES` bytes are the canonical header, the rest is the payload. The block is otherwise **format-agnostic** — it knows the header length, not the header's meaning. The length folded into each record is the **payload byte count as actually hashed** (a streaming counter), not the header's claimed `pld_len`; with the header length fixed, that pins the true emitted size, and the digest commits to what actually went out.

## The commitment hierarchy

The block implements the hash structure defined in **Interlock Verification Protocol** (`verification-protocol.md`). Each hash operator has it's own SHA core excpt for `pkt_digest = H(HEADER ‖ pld_digest)` which is split across two SHA cores (header and packet) to comfortably sustain line rate as here two 512 bit blocks must be processed for one 512 bit block of input worst case. The cores use 2x folding so complete one block in slightly more than 32 cycles.
Note: 4x folding did not manage to close timing on the FPGA.

A bucket closes on the swap beat. The close is not signalled out-of-band: the beat traverses the pipeline like a degenerate zero-byte packet — the per-packet stages run it through with discarded results in order to ensure that the bucket stage is ready to accept the closure (padding) with no cross-stage synchronisation logic. Only running the header hash stage is skipped entirely, since that can't propagate without the payload hash anyway. The swap's one real effect is at the bucket level: it finalises the bucket hash as a zero-byte element, contributing no bytes itself. Every `NUM_BUCKETS`-th bucket close also finalises the overall hash, which pulses `overall_valid`.

## Pipelining — sustaining line rate

```
             AXIS in
        ┌───────┴───────┐
        ▼               ▼
     hdr_core        pld_core
        │               │
        ▼               │
     hdr_fifo           │
        └───────┬───────┘
                ▼
             pkt_core
                │
                ▼
             bkt_core
                │
                ▼
             ovr_core
                │
                ▼
           overall out
```

The hierarchy is built from small **rate-matched** cores, each with it's own load stage (so processing a block and loading the next can happen in parallel).

The wire is only backpressured when the payload core is full. This backpressure is applied even if the in-progress packet ended and a header would follow. This does not limit throughput since loading can happen ~2x as fast as hashing so both a header block and a payload block can be loaded while the payload core completes the last block of the previous packet. Otherwise each stage is strictly faster than the one feeding it so those don't implement backpressure.

Past the payload core, elements (records and closes) move as **un-handshaked single-slot hand-offs** between the cores. This is safe because the element rate is throttled at the head of the pipe, not by the wire: every element costs at least one SHA block in the payload core and exactly one in the packet core (records also cost exactly one in the header core), and all cores share the same block period **B**.

```
TODO this is pretty ugly that a swap can reserve the stage for two rounds. Update the block to require two empty close beats (only start PAD1 (if needed) on the first and do PAD2 or single PAD only on the second)
```
The bucket close is the only point where the budget tightens, and it is (fortunately) protected by an exact trade-off. A record folds a bucket block only when it carries the block fill past 64 bytes (fill ≥ 30 before it), which leaves fill ≤ 32 after — always room for inline padding. Conversely, the two-block close (fill > 55, padding spills into a second block) can only follow a record that folded nothing. **Either the last record folds once and the close pads once, or the last record folds nothing and the close pads twice — never both** — so a (record, close) pair never costs more than two blocks against the two element slots it spans.

## Open items

- **Digest linkability.** Empty buckets produce identical overall digests and hence can be recognized in a certificate without any reveal from the prover.
