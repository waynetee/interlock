// Thin wrapper around the CoreTSE IP that exposes MDIO_PHYID as a
// per-instance Verilog parameter.
//
// Why this exists: Microchip's SmartDesign IP-generation flow bakes
// MDIO_PHYID into the auto-generated CORETSE_0.v wrapper at component-
// generation time. Both instances of the same component therefore have
// the same MDIO_PHYID (default 18). On a shared MDIO bus this causes
// the two CoreTSE internal-PCS slaves to collide.
//
// Generating two separate CORETSE components with different MDIO_PHYID
// values hits the ACT_UNIQUE_CORETSE_TOP duplicate-module synthesis
// error (sub-PR #3 iteration 1).
//
// This wrapper sidesteps both problems by exposing the underlying
// inner module's MDIO_PHYID as a parameter we can override per
// instance. We instantiate the same inner module twice with different
// parameters — no duplicate definitions, just multiple instantiations
// with different parameter overrides. Standard Verilog.
//
// Port list mirrors the auto-generated CORETSE_0.v wrapper exactly so
// that top.tcl wiring works without modification beyond switching the
// instantiation call from sd_instantiate_component to
// sd_instantiate_hdl_module.

`timescale 1ns / 100ps

module CoreTSE_with_param #(
    parameter MDIO_PHYID = 18
) (
    // Inputs
    input         MDI,
    input         MRXACPT,
    input         MRXCLK,
    input  [1:0]  MTXBYTEVALID,
    input         MTXCFRM,
    input         MTXCLK,
    input  [31:0] MTXDAT,
    input         MTXEOF,
    input         MTXRDY,
    input         MTXSOF,
    input  [31:0] PADDR,
    input         PCLK,
    input         PENABLE,
    input         PRESETN,
    input         PSEL,
    input  [31:0] PWDATA,
    input         PWRITE,
    input  [9:0]  RCG,
    input         RXCLK,
    input         SIGNAL_DETECT,
    input         STBP,
    input         TBI_RX_CLK,
    input         TBI_TX_CLK,
    input         TXCLK,
    // Outputs
    output [9:0]  ANX_STATE,
    output        MDC,
    output        MDO,
    output        MDOEN,
    output [1:0]  MRXBYTEVALID,
    output [31:0] MRXDAT,
    output        MRXEOF,
    output        MRXRDY,
    output        MRXSOF,
    output        MTXACPT,
    output        MTXHWM,
    output [31:0] PRDATA,
    output        PREADY,
    output        PSLVERR,
    output        RCG_ERROR,
    output        SYNC,
    output        TBI_TX_VALID,
    output [9:0]  TCG,
    output [31:0] TSM_CONTROL,
    output [1:0]  TSM_INTR
);

    // Tied-off signals replicating the SmartDesign-generated wrapper's
    // GMII-side constants (unused in TBI/SGMII mode).
    wire        GND_net = 1'b0;
    wire [7:0]  RXD_const_net = 8'h00;

    // Inner CoreTSE module (defined in CoreTSE.v, generated once by Libero).
    // All parameters except MDIO_PHYID match the SmartDesign defaults from
    // CORETSE_0.tcl.
    CORETSE_0_CORETSE_0_0_CORETSE #(
        .FAMILY      ( 26 ),
        .GMII_TBI    ( 1 ),
        .MDIO_PHYID  ( MDIO_PHYID ),    // ← parameterized
        .PACKET_SIZE ( 11 ),
        .SAL         ( 1 ),
        .SLIP_ENABLE ( 0 ),
        .STATS       ( 1 ),
        .WoL         ( 1 )
    ) the_tse (
        // Inputs
        .STBP          ( STBP ),
        .MTXCLK        ( MTXCLK ),
        .MTXRDY        ( MTXRDY ),
        .MTXSOF        ( MTXSOF ),
        .MTXEOF        ( MTXEOF ),
        .MTXDAT        ( MTXDAT ),
        .MTXBYTEVALID  ( MTXBYTEVALID ),
        .MTXCFRM       ( MTXCFRM ),
        .MRXCLK        ( MRXCLK ),
        .MRXACPT       ( MRXACPT ),
        .GTXCLK        ( GND_net ),
        .TXCLK         ( TXCLK ),
        .RXCLK         ( RXCLK ),
        .RXDV          ( GND_net ),
        .RXD           ( RXD_const_net ),
        .RXER          ( GND_net ),
        .CRS           ( GND_net ),
        .COL           ( GND_net ),
        .TBI_TX_CLK    ( TBI_TX_CLK ),
        .TBI_RX_CLK    ( TBI_RX_CLK ),
        .RCG           ( RCG ),
        .TBI_RX_VALID  ( GND_net ),
        .TBI_RX_READY  ( GND_net ),
        .SIGNAL_DETECT ( SIGNAL_DETECT ),
        .MDI           ( MDI ),
        .PCLK          ( PCLK ),
        .PRESETN       ( PRESETN ),
        .PADDR         ( PADDR ),
        .PSEL          ( PSEL ),
        .PENABLE       ( PENABLE ),
        .PWRITE        ( PWRITE ),
        .PWDATA        ( PWDATA ),
        // Outputs
        .MTXACPT       ( MTXACPT ),
        .MTXHWM        ( MTXHWM ),
        .MRXRDY        ( MRXRDY ),
        .MRXSOF        ( MRXSOF ),
        .MRXEOF        ( MRXEOF ),
        .MRXDAT        ( MRXDAT ),
        .MRXBYTEVALID  ( MRXBYTEVALID ),
        .TXEN          (  ),
        .TXD           (  ),
        .TXER          (  ),
        .TCG           ( TCG ),
        .TBI_TX_VALID  ( TBI_TX_VALID ),
        .RX_SLIP       (  ),
        .SYNC          ( SYNC ),
        .ANX_STATE     ( ANX_STATE ),
        .RCG_ERROR     ( RCG_ERROR ),
        .MDC           ( MDC ),
        .MDO           ( MDO ),
        .MDOEN         ( MDOEN ),
        .PREADY        ( PREADY ),
        .PRDATA        ( PRDATA ),
        .PSLVERR       ( PSLVERR ),
        .TSM_INTR      ( TSM_INTR ),
        .TSM_CONTROL   ( TSM_CONTROL )
    );

endmodule
