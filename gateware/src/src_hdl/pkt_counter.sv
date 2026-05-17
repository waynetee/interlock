// Tiny packet counter for AN4623 baseline. Increments on each rising edge of
// frame_sof; led is bit 0 of the count, so it toggles on every accepted frame
// (one frame = one LED flip). Useful as a visible sanity check that traffic
// is reaching CoreTSE's MAC RX side without needing a UART.
module pkt_counter (
    input  logic clk,
    input  logic rst_n,
    input  logic frame_sof,
    output logic led
);
    logic [31:0] count;
    logic        sof_d;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 32'd0;
            sof_d <= 1'b0;
        end else begin
            sof_d <= frame_sof;
            if (frame_sof && !sof_d) count <= count + 32'd1;
        end
    end
    assign led = count[0];
endmodule
