// Internal-loopback for CORETSE_1's MDIO bus.
//
// iter-4 architecture: CORETSE_1's MDIO bus is wholly internal to the FPGA
// fabric, not connected to the external bus that talks to VSC8575.
// CORETSE_1's master and slave communicate only with each other on this
// internal bus.
//
// Why: in our previous experiments, CORETSE_1's MDI was on the shared
// external bus but its master was idle (firmware accessed PHY 19 via
// CORETSE_0's master).  The CoreTSE slave appears to share an internal
// MDC wire with its own master — if the master is idle, MDC isn't
// toggling, and the slave can't decode bus traffic regardless of whether
// MDI is wired to the bus.
//
// iter-3 verified this empirically: PHY 19 was electrically identical
// to PHY 17 (unused address) — 0xFFFF with i=00 cycle=~0x72.  The slave
// wasn't responding at all.
//
// iter-4 fix: route CORETSE_1's MDO/MDOEN back to its own MDI through
// this tiny module.  Firmware accesses PHY 19 via TSE1_BASEADDR (so
// CORETSE_1's master is active and generates MDC), and the slave sees
// transactions on its own private bus.
//
// MDC handling: not exposed here.  CoreTSE's master and slave share
// internal MDC inside the module; the external MDC pin remains unused.
//
// Idle bus convention: when no driver is active (mdoen=0), drive mdi=1
// to mimic the pull-up that an external MDIO bus would have.

`timescale 1ns / 100ps

module tse1_loopback (
    // CoreTSE outputs (drive bus during write phase + slave response)
    input  wire mdo,
    input  wire mdoen,

    // CoreTSE input (master + slave both read from here)
    output wire mdi
);

    // Mirror the active driver onto MDI; idle = 1 (pull-up convention).
    assign mdi = mdoen ? mdo : 1'b1;

endmodule
