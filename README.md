# interlock

Hardware prototype of the verifier interlock described in the *Inference
Verification Prototype* design doc — a small FPGA that sits between AI
compute and the outside world, attesting to canonical packet streams via
HMAC-chained hashes.

This repo starts from Microchip's AN4623 (PolarFire 1G Ethernet Loopback
Using IOD CDR) demo as a working baseline. Modifications layer on top: a
packet counter and UART status print first, then port-to-port bridging,
then the actual interlock data path (hash chain, drop rules, HMAC
attestation via the PolarFire System Controller).

## Status

| Milestone | Status |
|---|---|
| AN4623 demo builds on Libero v2024.2 (with patched IP versions) | ✓ |
| AN4623 demo flashes and link comes up on MPF300-EVAL-KIT | ✓ |
| Mac→FPGA→Mac loopback verified via scapy + tcpdump | ✓ |
| Packet counter on LEDs (no firmware change) | — |
| RX frame count over UART (firmware change) | — |
| Port-to-port one-way bridge (variant B) | — |
| Bidirectional bridge with FIFO between MACs (variant C) | — |
| Mac → FPGA → DGX Spark physical setup | — |
| Hash-chain FSM (in fabric) | — |
| HMAC attestation via PF_USER_CRYPTO | — |

## Hardware target

- **Board:** Microchip MPF300-EVAL-KIT (Rev D), MPF300TS-1FCG1152I, Silver license tier
- **Tools:** Libero SoC v2024.2 on Linux, FlashPro Express v2024.2.0.13
- **External:** Mac (sender / test harness) and NVIDIA DGX Spark (eventual prover compute) wired into the board's two RJ45 ports

## Layout

```
interlock/
├── gateware/             # Microchip Tcl + RTL — patched AN4623 source for now
│   ├── common.tcl        # IP versions pinned at v2024.2-compatible values
│   ├── script.tcl        # Top-level: new_project → download cores → source flow scripts
│   └── src/
│       ├── 1_create_design.tcl    # SmartDesign assembly
│       ├── 2_constrain_design.tcl # I/O & timing constraints
│       ├── 4_implement_design.tcl # SYNTH → P&R → verify_timing → export
│       ├── 5_program_design.tcl   # generate .job
│       ├── src_components/        # per-IP create_and_configure_core calls
│       ├── src_constraints/       # .pdc and .sdc files
│       ├── src_hdl/               # custom Verilog (SSDetect.v from upstream + our additions)
│       └── src_softconsole/       # Mi-V firmware hex (precompiled iog_cdr.hex for now)
├── build.sh              # one-shot build wrapper
├── setup.sh              # pre-build environment checks
├── README.md
├── CLAUDE.md             # agent-loaded instructions for this repo
└── NOTES.md              # reproduction notes for the AN4623 patches
```

## Building

On the Hetzner box (or any machine with Libero v2024.2 + the vault populated
per `NOTES.md`):

```
./setup.sh        # verifies the license daemon and IP-vault state
./build.sh        # runs Libero, logs to /tmp/build_<timestamp>.log, sha256s the .job
```

Wall time: ~22 minutes (SYNTH 2.5 min, P&R 10 min, VERIFY/GEN/EXPORT 5 min).

### First-time setup on a fresh cloud VM

See [`docs/SETUP.md`](docs/SETUP.md) — step-by-step walkthrough from
"blank Ubuntu 24.04 cloud VM" to "can build this repo" (Libero download
+ install, license setup, lmgrd, libstdc++ workarounds, wrapper scripts,
swap, simulation toolchain). ~60–90 minutes of active work plus license
wait.

The resulting `.job` lands in `gateware/Libero_Project/designer/top/export/top.job`
(this directory is `.gitignored`; it's regenerated on every build).

## Flashing

On a machine with FlashPro Express + USB connection to the board:

```
scp <hetzner>:/root/fpga/interlock/gateware/Libero_Project/designer/top/export/top.job .
# then open FlashPro Express, load the .job, click RUN
```

## Testing

See `NOTES.md` for the scapy + tcpdump pattern that confirms ethernet
loopback from the Mac. Once the port-to-port bridge lands, the test will
extend to Mac → board → Spark roundtrip.

## License

The AN4623 source is from Microchip and retains its original licensing
(see `gateware/readme.txt` or Microchip's AN4623 page). Our additions are
MIT (or whatever — decide before going public).
