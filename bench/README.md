# bench/ — Spark flash + hardware-test scripts

Version-controlled copies of the scripts used to **flash** the interlock
bitstream onto the MPF300 board and **test** the live bitstream on real ethernet.
The full runbook is [`docs/flashing-and-testing.md`](../docs/flashing-and-testing.md).

These are the exact scripts that ran on the project's DGX Spark bench
(`spark-c191`), where they also live at `~/fpe/`. This directory is the canonical
copy so a collaborator can reproduce the workflow.

## How to use these on a bench

The flash VM and the tests both assume the scripts sit in a working directory on
the bench host. On the reference bench that directory is `~/fpe`. To reproduce:

```
# on the bench host (the machine with the FlashPro programmer + test NICs)
mkdir -p ~/fpe
cp bench/*.sh bench/*.py ~/fpe/
# flash_drive.sh is invoked from $HOME on the reference bench:
cp bench/flash_drive.sh ~/
```

## Two bench-specific values you MUST adjust

The scripts are kept **byte-faithful to what was verified on silicon**, so they
hardcode two things specific to the reference Spark. Change these for your bench:

1. **NIC names.** `enP7s7` (built-in) and `enxb8fbb3b1f53c` (USB dongle) — the two
   ports cabled to the board. Replace with your interface names (`ip link`).
2. **The docker mount path** `/home/claude/fpe`. The test scripts bind-mount it
   into the sender/capture containers (`-v /home/claude/fpe:/fpe`). Replace with
   the absolute path to your working dir (e.g. `-v $HOME/fpe:/fpe`).

Everything else (container images `python:3-slim` / `nicolaka/netshoot`, the USB
id `1514:2008`, the 9p tag `fpehost`, the guest login `ubuntu`/`ubuntu`) is
bench-agnostic.

## Script index

### Flash chain (host → box64test → x86 VM → FPExpress)

| Script | Runs on | Purpose |
|---|---|---|
| `flash_drive.sh` | host | Wrapper: `verify` / `launch` / `wait` / `tail` across the namespace chain. **Start here.** |
| `vmboot.sh` | box64test | The `qemu-system-x86_64` invocation (8 GB, USB + 9p passthrough). |
| `vmwait.sh` | box64test | Poll until the guest's ssh (`:2222`) answers. |
| `guest_run.sh` | guest | First-time guest bring-up: 9p mount + apt deps + `scan_chain`. |
| `gprog_launch.sh` | guest | Launch FPExpress `run_selected_actions` detached; writes `/tmp/prog.out`. |
| `gprog_wait.sh` | guest | Poll `/tmp/prog.out` for `PASSED`/`FAILED`. |
| `gprog.sh` | guest | Synchronous flash variant (mount + Xvfb + program, 1100 s timeout). |
| `launch_program.sh` / `do_program.sh` | guest | Older host-path variants; prefer the `gprog_*` path. |
| `greset.sh` | guest | Run a `DEVICE_INFO` action to confirm the chain is seen. |

### Data-plane tests (host NICs — independent of the flash VM)

| Script | Python deps | Tests |
|---|---|---|
| `canon_fwd.sh` | `canon_send.py` | Forwarding + DST/SRC sanitization (`ILOCKFWD` payload). |
| `type_drop.sh` | `canon_send.py`, `canon_send_type.py` | LENGTH forwards, TYPE (`0x86DD`) drops, no wedge after. |
| `fwd_spaced_test.sh` | `cert_send_spaced.py` | Spaced forwarding probe (safe for per-packet cert builds). |
| `canon_certtest.sh` | `canon_send_wire.py` | Bulk cert egress (`ilock-v5`) on the port-0 NIC. |
| `cert_onebyone_test.sh` | `cert_send_spaced.py`, `cert_parse.py` | One cert per packet; parse + verify `tau` = HMAC and `overall` binding. |
| `cert_spaced_test.sh` | `cert_send_spaced.py` | Spaced per-packet cert egress with version+id markers. |
| `canon_beacontest.sh` | `canon_beacon_parse.py` | Tick beacon (`ilbcn-v1`, DST `02:..:CB`), monotonic bucket. |
| `bucket_silicon_test.sh` | `bucket_silicon_test.py` | Beacon-driven bucket accept/drop on the combined build. |

### UART

| Script | Runs on | Purpose |
|---|---|---|
| `read_uart.sh` | guest | Bind `ftdi_sio` to the FlashPro FTDI and dump the Mi-V UART (`/dev/ttyUSBn`, 115200). See the runbook for the host-side read (the FTDI is single-holder). |

## Provenance

Flash chain verified end-to-end 2026-06-15; full interlock (forwarding + two
cert cores + cert egress) verified on silicon 2026-06-16. The wire constants baked
into the cert/beacon scripts track the bitstream that was live then — update the
relevant script if the gateware's cert/beacon format changes.
