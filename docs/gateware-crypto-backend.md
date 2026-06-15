# Gateware crypto backend — where the Core's SHA-256 and HMAC come from

Decision record for the interlock Core (the gateware version of
`prototype/interlock.py`). The Core needs two crypto primitives:

- **SHA-256, at line rate** — every accepted packet is folded into a running
  per-direction bucket hash, buckets fold into a per-second window hash
  (`H(ciphertext)`, `record`, bucket, window). This runs continuously on the
  wire, ~hundreds of MB/s aggregate full-duplex.
- **HMAC-SHA-256, once per second** — the certificate tag over the 108-byte
  cert body. Tiny and occasional.

These have opposite profiles (streaming vs. occasional), so the backend choice
isn't one decision — it's two. Three sources were evaluated.

## Options

### 1. secworks/sha256 — open fabric core
Plain Verilog-2001 SHA-256 core (BSD-2-Clause), NIST-vector tested, silicon-proven
(ASIC + FPGA). `init`/`next` give native multi-block streaming — exactly the
running bucket/window contexts. 66 cycles/block → ~100 MB/s per instance at
100 MHz; instantiate one per context to hit aggregate throughput.

- **Needs:** a small `sha256_stream` wrapper (byte→512-bit block assembly +
  padding + length tracking + `init`/`next` sequencing), written once and reused;
  for HMAC, a thin FSM doing the two passes (`key⊕ipad`, `key⊕opad`).
- **Pros:** pure fabric, no CPU, fully inspectable (small TCB), line-rate, you
  own every line. Plain Verilog avoids the complex-SV synth-vs-sim trap that bit
  the deframe path.
- **Cons:** padding wrapper is yours to get right; HMAC key lives in fabric
  registers (protected only by the battery-backed key domain, not dedicated
  crypto hardware).
- **Repo:** https://github.com/secworks/sha256

### 2. PolarFire User Crypto / TeraFire — the on-chip HMAC hardware
Athena TeraFire EXP-F5200B, the `PF_CRYPTO` hard block. Natively does HMAC-SHA,
all SHA-2, AES, ECC, RNG; DPA-resistant; 56 KB sNVM secure key storage. Max
189 MHz. Present only on **"S"-grade** devices — our eval board
(`MPF300TS-1FCG1152`) qualifies.

- **Needs:** a **soft CPU** (Mi-V RV32) running Microchip's **CAL** C library to
  command it over AHB-Lite, plus the supporting fabric (two `CoreAHBL2AHBL`
  bridges for the separate 180 MHz crypto domain + DMA, SRAM buffer,
  `CoreSysServices_PF` for sNVM). The Mi-V is ~6.7k LUTs (~2% of MPF300).
- **Why the CPU:** the only *documented* control interface is the CAL library —
  the register/command protocol is encapsulated in it and not published. The
  block is a microcoded coprocessor commanded by software, not a fixed-function
  datapath unit. (A `START` pin documents a "standalone, no host processor" mode,
  but how to feed it operations is undocumented; every reference design, sample,
  and the CAL flow assume the coprocessor+CPU model.)
- **Pros:** hardware-protected key custody (DPA resistance + sNVM) — directly
  serves the interlock's "protect the HMAC secret" assumption; correctness is
  Microchip's, not ours.
- **Cons:** adds a soft CPU + firmware + a gated, black-box library (CAL) to the
  TCB — the opposite of "small, inspectable verifier." Coprocessor request/
  response model is **not** line-rate, so it can only serve the once/sec HMAC,
  not the streaming hashes. CAL and the design files are request-gated
  (`FPGA_marketing@microchip.com`); needs a Libero Eval/Gold/Platinum license.
- **Reference:** AC464 "Implementing Data Security Using User Cryptoprocessor"
  ([V11 PDF](https://ww1.microchip.com/downloads/aemDocuments/documents/FPGA/ApplicationNotes/ApplicationNotes/Microchip_PolarFire_FPGA_Implementing_Data_Security_Using_User_Cryptoprocessor_Application_Note_AC464_V11.pdf))
  — the canonical Mi-V + PF_CRYPTO reference design. Sample project
  `RV32_Message_Authentication` is the MAC/HMAC example; Appendix 2 covers
  simulating the block.

### 3. PolarFire System Services SHA-256 — CPU-free, but limited
The System Controller exposes a SHA-256 *system service*; `CoreSysServices_PF` is
a fabric master that issues it with no CPU.

- **Pros:** no soft CPU; uses a hardened SHA.
- **Cons:** SHA-256 only (HMAC's two passes still yours to wrap); routes through
  the System Controller mailbox — built for occasional ops (e.g. digesting device
  content), **not** line rate. Marginal benefit over option 1; key still lives in
  fabric.
- **Reference:** [PolarFire System Services User Guide](https://ww1.microchip.com/downloads/aemDocuments/documents/FPGA/ProductDocuments/UserGuides/PolarFire_FPGA_and_PolarFire_SoC_FPGA_System_Services_User_Guide_VD.pdf),
  [CoreSysServices_PF driver guide](https://github.com/polarfire-soc/polarfire-soc-documentation/blob/master/bare-metal-embedded-software/bare-metal-driver-user-guides/soft-ip-driver-user-guides/CoreSysServices-PF/coresysservices-pf-driver-user-guide.md).

## Summary

| | secworks fabric | User Crypto (TeraFire) | System Services SHA |
|---|---|---|---|
| Soft CPU needed | no | **yes** (Mi-V + CAL) | no |
| Line-rate streaming | **yes** | no | no |
| HMAC native | no (thin wrapper) | **yes** | no (thin wrapper) |
| Key custody | fabric regs | **DPA + sNVM** | fabric regs |
| TCB / inspectability | **small, all ours** | large (CPU + gated lib) | medium |
| Licensing | open (BSD) | gated (CAL, S-grade lic.) | in Libero |

## Recommendation

- **Streaming hashes (per-packet / bucket / window):** secworks fabric cores —
  the only line-rate option, and the simplest.
- **Once-per-second HMAC tag:** default to **secworks SHA + a small HMAC FSM** —
  no CPU, smallest TCB, fully inspectable. The key lives in the battery-backed
  fabric domain the interlock already assumes.
- **Take the User Crypto only if** hardware key custody (DPA + sNVM) is a hard
  requirement for the HMAC secret, and the cost of a Mi-V + CAL + a black-box in
  the TCB is acceptable. That is a security-vs-TCB tradeoff, not a default.

## Note on the conformance harness

The cocotb harness in [`gateware/tb/`](../gateware/tb/) checks the Core's emitted
certificate **byte-for-byte** against the Python golden model — so it is agnostic
to which backend above is chosen. Whichever SHA/HMAC source the Core uses, the
same test validates it.
