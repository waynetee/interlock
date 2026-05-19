# Mi-V firmware source (iteration 1)

The Mi-V soft RISC-V CPU on the FPGA runs `iog_cdr.hex` at boot to
initialize CoreTSE_0 and the VSC8575 PHY. This directory holds our
modifications to the AN4623 reference firmware.

## What's here

- `main.c` — modified application entry point. Adapted from
  Microsemi/Microchip's AN4623 `iog_cdr/main.c`. Adds UART early, an
  MDIO bus scan, progress prints, and a status-poll idle loop.
- `iog_cdr.hex` — current pre-built firmware (the AN4623 reference,
  baked into sNVM by the Libero build flow). To be replaced when we
  rebuild our `main.c` into a new hex.

## Workflow (using SoftConsole on UTM Ubuntu VM)

See `../../../docs/firmware-iteration.md` for the full setup. Short
version once SoftConsole is up:

1. Download the AN4623 SoftConsole project from the Hetzner box:
   ```
   scp -r <hetzner>:/root/fpga/an4623/mpf_an4623_v2022p3_df ~/
   ```
2. Copy this directory's `main.c` over the AN4623 source's `main.c`:
   ```
   cp <local-interlock-clone>/gateware/src/src_softconsole/main.c \
       ~/mpf_an4623_v2022p3_df/SoftConsole_Project/iog_cdr/main.c
   ```
3. In SoftConsole: `File → Import → Existing Projects` →
   `~/mpf_an4623_v2022p3_df/SoftConsole_Project/iog_cdr/`.
4. `Project → Build Configurations → Set Active → Debug`.
5. `Project → Build All` (Ctrl-B).
6. `Run → Debug Configurations` → create a "GDB OpenOCD Debugging" entry
   pointing at `Debug/iog_cdr.elf`. Tick "Reset target before download"
   and "Load image".
7. Click `Debug`. Firmware JTAG-loads into TCM at `0x80000000` and runs.
8. On macOS (or the host running screen): `screen /dev/tty.usbserial-XXX 115200`
   to see UART output.

The bitstream on the FPGA doesn't change — only the firmware in TCM.

## What iteration 1 prints

On boot:
- `[boot] interlock firmware iter-1 starting`
- `[boot] configure_zl30364` (and `done`)
- `[boot] tse_init (MAC 0, ...)` (and `done`)
- `[scan] sweeping MDIO 0..31 ...` followed by one line per PHY that
  responds (`[scan]   addr=N  ID1=0x....  ID2=0x....`)
- `[boot] Phy_advertise` / `phy_autonegotiation` (with `done`)
- `[state] PHY28 (copper) status=0x.... link=N aneg_done=N`
- `[state] PHY18 (SGMII)  status=0x.... link=N aneg_done=N`
- `[probe] CoreTSE_1 at 6000...:  MAC_CONFIG_1 reads 0x....`
- `[boot] init complete — polling port 0 status`
- Once per second: `[poll t=N] PHY28 status=0x.... link=N`

## What iteration 1 tells us

- **The MDIO scan output identifies port 1's PHY addresses.** Expected
  to be 29 (copper) and 19 (SGMII) by analogy with port 0 (28 / 18),
  but we should verify against actual hardware before writing init for
  iteration 2.
- **The CoreTSE_1 probe** confirms whether `TSE1_BASEADDR = 0x60003000`
  is the right slot-3 address. If `MAC_CONFIG_1` reads back `0x00000000`
  (post-reset state) the slot mapping is correct. If it reads
  `0xFFFFFFFF` or causes a bus hang, the APB decode is wrong.
- **The poll loop** confirms link state on port 0 stays up after init
  (sanity check that we didn't break the existing port).

## Iteration 2 (planned, not in this commit)

Once iteration 1 confirms port 1 PHY addresses and CoreTSE_1 base:

- Add `tse1_init()` — same register sequence as `tse_init()` but at
  `TSE1_BASEADDR`. Skips the `phy_init()` call because CoreTSE_1's MDIO
  master pins aren't wired (see `top.tcl`).
- Add `phy1_init(phy_copper, phy_sgmii)` — issues the same MDIO writes
  as `Phy_advertise()` + `phy_autonegotiation()` but parameterised on
  PHY address. Targets the port 1 PHY addresses through CoreTSE_0's
  MDIO master.
- Wire both into `main()` after the port 0 init.

## Files NOT in this directory

The rest of the AN4623 SoftConsole project (drivers, HAL, linker
scripts) lives in Microchip's distribution at:

```
/root/fpga/an4623/mpf_an4623_v2022p3_df/SoftConsole_Project/iog_cdr/
```

We only override `main.c`. Don't copy the rest into this repo —
Microsemi licence applies.
