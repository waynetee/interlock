// Combines two CoreTSE instances' MDIO output drivers onto a single shared
// MDIO bus.  Necessary because CoreTSE's MDO/MDOEN outputs carry BOTH the
// master's transmit data AND the slave's response data on a shared internal
// path.  When two CoreTSE instances share an MDIO bus and each has its own
// internal slave (at distinct MDIO_PHYID addresses), both slaves need their
// MDO/MDOEN outputs combined onto the bus driver so the slave's response
// can reach the master.
//
// Sub-PR #8 iteration 6 had CORETSE_1's MDO/MDOEN marked unused — its
// slave at MDIO 19 was internally responsive but its response had nowhere
// to go, leaving PHY 19 silent on the bus.  This module fixes that by
// wire-ORing the output-enables and muxing the data.
//
// Arbitration: CORETSE_0 is the only instance that initiates MDIO
// transactions from firmware (we never write to CORETSE_1's APB MDIO
// registers).  So CORETSE_0:MDOEN is high during write-phase of every
// transaction; CORETSE_1:MDOEN is high only when CORETSE_1's slave is
// responding (to a read targeting PHY 19).  Those phases don't overlap,
// so the priority mux below works correctly without contention.

`timescale 1ns / 100ps

module mdio_combiner (
    // CoreTSE_0 (primary master + slave at MDIO_PHYID 18)
    input  wire mdo_0,
    input  wire mdoen_0,

    // CoreTSE_1 (slave at MDIO_PHYID 19; its master is unused but its slave
    // drives MDO/MDOEN when responding)
    input  wire mdo_1,
    input  wire mdoen_1,

    // Combined drivers → BIBUF_0:D and BIBUF_0:E
    output wire mdo,
    output wire mdoen
);

    // Output enable: either instance asserting drives the bus.
    assign mdoen = mdoen_0 | mdoen_1;

    // Data: CORETSE_0 wins if both are driving (shouldn't happen in normal
    // operation since CORETSE_0's transactions are time-multiplexed away
    // from CORETSE_1's slave response window).
    assign mdo = mdoen_0 ? mdo_0 : mdo_1;

endmodule
