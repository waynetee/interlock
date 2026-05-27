# Interlock Wire Protocol v1

Custom Ethernet protocol for FPGA-mediated traffic between Mac and Spark.
The FPGA is the only Layer-2 endpoint visible to either host; it
terminates incoming frames, strips headers, and re-originates them with
its own addresses.

This document is the canonical wire-format specification. The Mac code,
Spark code, and FPGA fabric MUST agree on this format. When the protocol
changes, this document changes in the same PR.

## Goals

- Provide a wire format both Mac/Spark and the FPGA fabric can implement
  with minimal code.
- Allow per-frame loss detection via sequence numbers.
- Reserve room for future attestation features (HMAC, hash chain) without
  changing v1 framing.
- Stay word-aligned (32-bit) so the FPGA parser/builder doesn't need
  byte-shift logic.

## Non-goals (v1)

- Not IP/UDP/TCP. Single EtherType, single point-to-point link per
  direction.
- Not routable across IP networks.
- No reliability, retransmission, or ordering guarantees beyond what
  Ethernet provides. App layer handles these if needed.
- No payload confidentiality. Mac and Spark encrypt end-to-end before
  sending; FPGA never sees plaintext.

## Frame format

20-byte header (5 × 32-bit words, naturally aligned) followed by opaque
payload. All multi-byte fields are **big-endian** (network byte order).

| Offset | Size | Field         | Type      | Description |
|--------|------|---------------|-----------|-------------|
| 0      | 6    | Dest MAC      | bytes     | Standard Ethernet destination address |
| 6      | 6    | Source MAC    | bytes     | Standard Ethernet source address |
| 12     | 2    | EtherType     | uint16 BE | **0x88B5** (IEEE 802 Local Experimental EtherType 1) |
| 14     | 2    | Magic         | uint16 BE | **0xFADE** (protocol identifier; reject if mismatched) |
| 16     | 2    | Sequence      | uint16 BE | Monotonic per sender, per direction; wraps mod 2¹⁶ |
| 18     | 1    | Version       | uint8     | **0x01** for this protocol version |
| 19     | 1    | Flags         | uint8     | bit 0 = data frame, bit 1 = attestation frame (FPGA-originated), bits 2–7 reserved (MUST be 0) |
| 20+    | var  | Payload       | bytes     | Opaque to FPGA; Mac/Spark application-defined |

**Payload size**: 0 to 1494 bytes (frame total 60–1514 bytes, fits
standard Ethernet MTU of 1500-byte payload). Larger logical messages must
be fragmented at the application layer in v1.

## MAC addresses

The FPGA has two MAC addresses, one per port. Each host has its own.

| Role             | Address              | Notes |
|------------------|----------------------|-------|
| FPGA, Mac side   | `02:00:00:00:00:01`  | Locally administered (bit 1 of first byte = 1) — see open question 3 |
| FPGA, Spark side | `02:00:00:00:00:02`  | Locally administered — see open question 3 |
| Mac              | (host's actual MAC)  | Whatever the host's NIC reports |
| Spark            | (host's actual MAC)  | Whatever the host's NIC reports |

## Required behaviors

### Mac (sender)

1. Construct frame with `dst = FPGA_M_mac`, `src = Mac_mac`,
   `EtherType = 0x88B5`, `Magic = 0xFADE`.
2. Set `Sequence = mac_send_counter` and increment counter after each send.
3. Set `Version = 0x01`, `Flags = 0x01` (data frame).
4. Append application payload (≤ 1494 bytes).
5. Send via raw socket (Linux: `AF_PACKET, SOCK_RAW`; macOS: BPF). Root
   required on both.

### Mac (receiver)

1. Receive frame with `EtherType = 0x88B5` (raw-socket filter).
2. Validate `Magic == 0xFADE` (else drop and count).
3. Validate `Version == 0x01` (else drop and count).
4. Check `Sequence` vs `expected_recv_seq`:
   - `==`: normal; advance expected by 1.
   - `>` (modular): gap of (recv − expected) frames; log and advance.
   - `<` (modular): duplicate or wrap; drop, count.
5. Pass payload to application.

### Spark

Symmetric to Mac.

### FPGA (Mac → Spark direction)

On RX from `CORETSE_0:MRX`:
1. Parse Ethernet header. Drop if `EtherType ≠ 0x88B5`.
2. Parse interlock header. Drop if `Magic ≠ 0xFADE` or `Version ≠ 0x01`.
3. Compare `Sequence` against `expected_mac_seq`; update gap counter on
   mismatch; advance expected.
4. Stream payload into TX-side FIFO.

On TX to `CORETSE_1:MTX`:
1. Build Ethernet header: `dst = Spark_mac`, `src = FPGA_S_mac`,
   `EtherType = 0x88B5`.
2. Build interlock header: `Magic = 0xFADE`,
   `Sequence = fpga_to_spark_counter++`, `Version = 0x01`,
   `Flags = 0x01`.
3. Emit header + payload.

**The FPGA must NOT preserve Mac's sequence number** — it generates its
own outbound sequence on the Spark-side link. Architectural commitment:
the FPGA is the "sender" Spark sees.

### FPGA (Spark → Mac direction)

Symmetric to above, with TX/RX sides swapped and using
`CORETSE_1:MRX` → `CORETSE_0:MTX`.

## Sequence number semantics

- 16-bit, big-endian, increments by 1 per frame sent.
- Wraps modulo 2¹⁶ after 65,535.
- Each sender × direction has its own counter (so there are FOUR
  independent counters in the system: Mac→FPGA, FPGA→Spark, Spark→FPGA,
  FPGA→Mac).
- Gap comparison uses modular arithmetic. The check
  `(int16_t)(received_seq - expected_seq) > 0` correctly identifies
  forward progress for gaps less than 32,768 (which is far larger than
  any plausible loss event).

## Error handling

| Error                                | FPGA behavior                                           | Host behavior            |
|--------------------------------------|---------------------------------------------------------|--------------------------|
| FCS error                            | CoreTSE drops automatically; fabric never sees frame    | N/A                      |
| Wrong EtherType                      | Drop silently                                           | Drop silently            |
| Wrong magic                          | Drop, increment `bad_magic_count`                       | Drop, log                |
| Wrong version                        | Drop, increment `bad_version_count`                     | Drop, log (forward-compat) |
| Sequence gap                         | Forward anyway; increment `gap_count`                   | Log; advance expected     |
| Sequence ≤ expected (modular)        | Forward anyway; increment `duplicate_count`             | Drop, log                 |
| Frame too short (< 60 bytes total)   | CoreTSE may filter per `hstdrplt64` config              | N/A                      |
| Frame too large (> MTU)              | CoreTSE filters per Maximum Frame Length register       | N/A                      |
| FPGA payload FIFO full               | See open question 2                                     | Sender may see drops      |

All FPGA counters exposed via APB (read by Mi-V firmware and printed via
UART periodically).

## Counters exposed by FPGA

Each direction has its own counter set, mapped to APB-readable registers.

| Counter             | Width | Description                          |
|---------------------|-------|--------------------------------------|
| `rx_frames_total`   | 32    | All frames received                  |
| `rx_frames_valid`   | 32    | Frames passing all validation        |
| `rx_bad_etype`      | 16    | EtherType mismatch                   |
| `rx_bad_magic`      | 16    | Magic mismatch                       |
| `rx_bad_version`    | 16    | Version mismatch                     |
| `rx_gap_count`      | 16    | Sequence gaps detected               |
| `rx_duplicate_count`| 16    | Sequence duplicate/old               |
| `tx_frames_total`   | 32    | Frames sent                          |

Mi-V firmware reads these via APB and prints periodically (e.g., once per
second) via UART. Future versions may emit a status frame on demand.

## Annotated example

A data frame with payload "Hello!" (`48 65 6C 6C 6F 21`), Mac→FPGA,
sequence 42:

```
Offset  Bytes                                              Field
------  -----------------------------------------          -----
0x00    02 00 00 00 00 01                                  Dest MAC = FPGA_M_mac
0x06    DE AD BE EF CA FE                                  Source MAC = Mac_mac (example)
0x0C    88 B5                                              EtherType = 0x88B5
0x0E    FA DE                                              Magic = 0xFADE
0x10    00 2A                                              Sequence = 42
0x12    01                                                 Version = 1
0x13    01                                                 Flags = 0x01 (data)
0x14    48 65 6C 6C 6F 21                                  Payload = "Hello!"
```

Total payload bytes on wire: 26. After Ethernet minimum-frame padding,
the actual on-wire frame is 64 bytes (Ethernet's 60-byte minimum + 4-byte
FCS added by hardware). Larger payloads scale directly.

## Open questions (not finalized in v1)

These are tracked here rather than picked because they affect security,
operations, or interop and deserve explicit confirmation before being
frozen.

### 1. Source-MAC validation by FPGA

Options:

- **(a) No validation.** FPGA accepts any source MAC in incoming frames.
  Simplest; lowest fabric complexity. Recommended default for v1.
- **(b) Strict allowlist.** FPGA drops frames whose source MAC isn't on a
  configured list (one entry per port). Tighter security; protects
  against a compromised host on the same link.
- **(c) Equality check against single expected MAC per port.** Halfway
  between (a) and (b). Slightly less flexible than (b) but easier to
  manage.

### 2. FPGA payload-FIFO-full behavior

Options:

- **(a) Backpressure ingress.** When the cross-direction TX FIFO fills,
  stall the RX-side handshake to CoreTSE; eventually the upstream MAC
  FIFO fills and CoreTSE drops at the wire. Drops are detected at the
  sender via sequence gaps. Simpler; recommended default.
- **(b) Drop oldest pending frame.** Pop the head of the FIFO and admit
  the new frame. Preserves freshness at the cost of older losses;
  application sees more gaps under load.
- **(c) Drop incoming new frame.** Refuse the new frame; gap appears in
  inbound sequence. Slightly easier to implement than (b).

### 3. FPGA MAC addresses

Options:

- **(a) Hardcoded** `02:00:00:00:00:01` (Mac side) and
  `02:00:00:00:00:02` (Spark side). Locally administered; easy to
  remember; risk of collision if multiple interlocks share a subnet
  (we don't expect this).
- **(b) Per-device derived** from PolarFire System Controller's device
  serial number, e.g., low 5 bytes of serial OR'd with `0x02` in the
  first byte. Unique per FPGA; requires reading device serial at boot.
- **(c) Firmware-configurable** via UART command or a config file.
  Maximum flexibility; small additional firmware work.

### 4. Hash/HMAC coverage range (for iter-6+)

Once attestation is added, the hash function will cover some subset of
each frame. Options:

- **(a) Bytes 14 onward** (magic through end of payload). Excludes the
  Ethernet header so that header-rewriting by the FPGA doesn't disturb
  the chain. Probably the right choice.
- **(b) Bytes 16 onward** (sequence through end of payload). Excludes
  magic too. Useful if the magic gets rewritten or version-bumped during
  forwarding.
- **(c) Payload only** (bytes 20+). Cleanest separation from framing but
  excludes sequence number from attestation (a sequence-replay attack
  isn't covered).
- **(d) Entire frame** (bytes 0+). Hashes Ethernet header too; would
  require Mac/Spark to predict FPGA's outbound MAC addresses to verify.

Will be decided in the v2 protocol document that adds attestation.

### 5. Attestation frame format (for iter-6+)

When the FPGA originates an attestation frame (`Flags & 0x02`), the
payload structure is TBD. Likely components:

- A sequence range covered (start, end)
- A hash digest of frames in that range
- An HMAC tag using FPGA's private key
- A timestamp (if the FPGA has access to one)

Out of scope for v1; will be specified in the v2 protocol document.

### 6. Jumbo frame support

Options:

- **(a) Standard MTU only** (1500-byte payload, 1494-byte interlock
  payload). Simplest; works for any modern Ethernet. Recommended for v1.
- **(b) Jumbo frames** (up to ~4000-byte payload by setting CoreTSE's
  Maximum Frame Length register higher and configuring Mac/Spark MTU).
  Useful only if individual application messages exceed ~1480 bytes.
- **(c) Application-layer fragmentation.** Mac/Spark split large
  messages into multiple frames; receiver reassembles. Independent of
  Ethernet MTU.

For v1, recommend (a); add (c) at the app level if individual messages
get too large.

### 7. Counter access mechanism

Mi-V firmware reads counters via APB; how does it expose them?

- **(a) Periodic UART dump.** Print all counter values once per second.
  Simplest; available now.
- **(b) On-demand UART command.** Mi-V watches UART input for a "dump
  counters" command; prints on request. Less spam, requires basic
  command parser.
- **(c) Counter-status frames.** FPGA emits a status frame on the
  network periodically; Mac/Spark read via raw socket. Better for remote
  monitoring; more code.

Recommend (a) for v1; revisit when we have iter-5 working.

## Versioning policy

- **v1** is this document. Frozen except for clarifications and bugfix
  edits.
- **v2** is any wire-format change (new field, removed field, changed
  semantics). v2 must increment the `Version` byte in the frame header.
  Implementations MUST reject mismatched versions to avoid silent
  misinterpretation.
- Reserved flag bits are NOT a version bump — adding new flag bits is
  backward-compatible as long as old implementations ignore them
  (which the spec requires above).

## Related documents

- `docs/multi-port-ethernet-findings.md` — physical layer, CoreTSE
  configuration, and the dual-bus MDIO architecture iter-4 settled on.
- `docs/firmware-iteration.md` — SoftConsole + JTAG iteration workflow.
- `CLAUDE.md` (repo root) — project conventions and toolchain.
