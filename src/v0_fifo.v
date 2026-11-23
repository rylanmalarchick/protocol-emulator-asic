`default_nettype none

// A small synchronous FIFO. A push when full drops the data and pulses
// `drop`. A pop when empty does nothing. Push and pop can happen in the
// same cycle. Registers only, so the storage is not a program memory.

module v0_fifo #(
    parameter W  = 8,
    parameter LD = 4  // log2 of the depth
) (
    input  wire         clk,
    input  wire         rst_n,  // synchronous
    input  wire         clear,
    input  wire         push,
    input  wire [W-1:0] din,
    input  wire         pop,
    output wire [W-1:0] dout,
    output wire         empty,
    output wire         full,
    output wire         drop
);
  localparam DEPTH = 1 << LD;

  reg [W-1:0]  q [0:DEPTH-1];
  reg [LD-1:0] rp, wp;
  reg [LD:0]   n;

  assign empty = n == 0;
  assign full  = n == DEPTH;
  assign dout  = q[rp];

  wire do_pop  = pop && !empty;
  wire do_push = push && (!full || do_pop);
  assign drop  = push && !do_push;

  integer i;
  always @(posedge clk) begin
    if (!rst_n || clear) begin
      rp <= 0;
      wp <= 0;
      n  <= 0;
      for (i = 0; i < DEPTH; i = i + 1) q[i] <= {W{1'b0}};
    end else begin
      if (do_push) begin
        q[wp] <= din;
        wp    <= wp + 1'b1;
      end
      if (do_pop) rp <= rp + 1'b1;
      n <= n + {{LD{1'b0}}, do_push} - {{LD{1'b0}}, do_pop};
    end
  end

`ifdef FORMAL
  // Check only after a reset: the registers have no power-on value.
  reg f_rst = 1'b0;
  always @(posedge clk) if (!rst_n) f_rst <= 1'b1;
  always @(*) if (f_rst) begin
    a_count: assert (n <= DEPTH);
    a_ptrs:  assert (wp == rp + n[LD-1:0]);
  end
`endif
endmodule
