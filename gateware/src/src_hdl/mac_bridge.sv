// mac_bridge — frame-forwarding async FIFO between two MAC clock domains.
//
// One-way data path. CoreTSE_0's MAC RX bytes are streamed in on the rx_*
// AXI-Stream-like interface (rx_clk domain), held in a dual-clock FIFO, and
// streamed out on the tx_* interface (tx_clk domain) into CoreTSE_1's MAC TX.
//
// This is the placeholder where the eventual interlock "Core" (drop rules,
// hash chain, attestation FSM) will plug in — the AXIS interface on both
// sides is deliberately the shape downstream logic needs.
//
// Interface:
//   *_tvalid : data valid this cycle
//   *_tready : downstream ready (back-pressure)
//   *_tdata  : 8-bit byte payload
//   *_tlast  : asserted with the last byte of a frame
//   *_tuser  : error flag (carried end-to-end; not interpreted here)
//
// Implementation: Cliff-Cummings dual-clock FIFO with Gray-code pointers
// crossed via two-flop synchronizers, plus a first-word-fall-through (FWFT)
// output register on the read side so tx_tdata is always stable when
// tx_tvalid is high.

`default_nettype none

module mac_bridge #(
    parameter int unsigned DEPTH_LOG2 = 11  // 2^11 = 2048 entries — fits one max-size standard ethernet frame
) (
    // RX side — rx_clk domain
    input  wire        rx_clk,
    input  wire        rx_rst_n,
    input  wire        rx_tvalid,
    output wire        rx_tready,
    input  wire [7:0]  rx_tdata,
    input  wire        rx_tlast,
    input  wire        rx_tuser,

    // TX side — tx_clk domain
    input  wire        tx_clk,
    input  wire        tx_rst_n,
    output wire        tx_tvalid,
    input  wire        tx_tready,
    output wire [7:0]  tx_tdata,
    output wire        tx_tlast,
    output wire        tx_tuser
);
    localparam int unsigned PTR_W  = DEPTH_LOG2;
    localparam int unsigned DEPTH  = 1 << DEPTH_LOG2;
    localparam int unsigned DATA_W = 8 + 1 + 1;  // tdata + tlast + tuser

    // FIFO storage (synthesizes to dual-port BRAM/LSRAM)
    logic [DATA_W-1:0] mem [DEPTH];

    // Pointers — one extra bit so full/empty are distinguishable
    logic [PTR_W:0] wr_ptr_bin;     // rx_clk domain
    logic [PTR_W:0] wr_ptr_gray;    // rx_clk domain
    logic [PTR_W:0] rd_ptr_bin;     // tx_clk domain
    logic [PTR_W:0] rd_ptr_gray;    // tx_clk domain

    // Two-FF pointer synchronizers (each into the OPPOSITE domain)
    logic [PTR_W:0] wr_ptr_gray_sync_tx_q1, wr_ptr_gray_sync_tx;
    logic [PTR_W:0] rd_ptr_gray_sync_rx_q1, rd_ptr_gray_sync_rx;

    function automatic logic [PTR_W:0] bin_to_gray(input logic [PTR_W:0] b);
        return b ^ (b >> 1);
    endfunction

    // -- Write side (rx_clk) --
    logic wr_en;
    logic wr_full;

    assign wr_en = rx_tvalid & rx_tready;
    // Full when next-write would equal read pointer (Gray-pointer trick:
    // top two bits inverted means N-deep-ahead).
    assign wr_full = (wr_ptr_gray == {~rd_ptr_gray_sync_rx[PTR_W:PTR_W-1],
                                       rd_ptr_gray_sync_rx[PTR_W-2:0]});
    assign rx_tready = ~wr_full;

    always_ff @(posedge rx_clk or negedge rx_rst_n) begin
        if (!rx_rst_n) begin
            wr_ptr_bin             <= '0;
            wr_ptr_gray            <= '0;
            rd_ptr_gray_sync_rx_q1 <= '0;
            rd_ptr_gray_sync_rx    <= '0;
        end else begin
            rd_ptr_gray_sync_rx_q1 <= rd_ptr_gray;
            rd_ptr_gray_sync_rx    <= rd_ptr_gray_sync_rx_q1;

            if (wr_en) begin
                mem[wr_ptr_bin[PTR_W-1:0]] <= {rx_tuser, rx_tlast, rx_tdata};
                wr_ptr_bin                 <= wr_ptr_bin + 1'b1;
                wr_ptr_gray                <= bin_to_gray(wr_ptr_bin + 1'b1);
            end
        end
    end

    // -- Read side (tx_clk) — first-word-fall-through output register --
    logic                fifo_not_empty;
    logic                out_valid;
    logic [DATA_W-1:0]   out_data;
    logic                rd_en;
    logic                do_pull;

    assign fifo_not_empty = (rd_ptr_gray != wr_ptr_gray_sync_tx);
    assign tx_tvalid      = out_valid;
    assign rd_en          = tx_tvalid & tx_tready;
    // Pull a new byte from mem into the output register whenever (a) the
    // output is empty, or (b) the consumer just took the byte we had.
    assign do_pull        = fifo_not_empty & (~out_valid | rd_en);
    assign {tx_tuser, tx_tlast, tx_tdata} = out_data;

    always_ff @(posedge tx_clk or negedge tx_rst_n) begin
        if (!tx_rst_n) begin
            rd_ptr_bin             <= '0;
            rd_ptr_gray            <= '0;
            wr_ptr_gray_sync_tx_q1 <= '0;
            wr_ptr_gray_sync_tx    <= '0;
            out_valid              <= 1'b0;
            out_data               <= '0;
        end else begin
            wr_ptr_gray_sync_tx_q1 <= wr_ptr_gray;
            wr_ptr_gray_sync_tx    <= wr_ptr_gray_sync_tx_q1;

            if (do_pull) begin
                out_data    <= mem[rd_ptr_bin[PTR_W-1:0]];
                out_valid   <= 1'b1;
                rd_ptr_bin  <= rd_ptr_bin + 1'b1;
                rd_ptr_gray <= bin_to_gray(rd_ptr_bin + 1'b1);
            end else if (rd_en) begin
                // Consumer took the byte and FIFO is empty — output becomes invalid.
                out_valid <= 1'b0;
            end
        end
    end

endmodule

`default_nettype wire
