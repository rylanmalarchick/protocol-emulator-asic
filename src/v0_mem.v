`default_nettype none

// Program memory wrapper. All program memory goes through this module.
// One write port and one read port. The read is synchronous: rdata is the
// word at the raddr of the cycle before. The ASIC build uses flip-flops.
// An SRAM macro (RM_IHPSG13_1P_*) or an FPGA block RAM fits the same port,
// because both also read synchronously.
//
// The memory has no reset. The loader writes every word that a program
// uses before the core runs.

module v0_mem #(
    parameter AW = 6,
    parameter DW = 38
) (
    input  wire          clk,
    input  wire          we,
    input  wire [AW-1:0] waddr,
    input  wire [DW-1:0] wdata,
    input  wire [AW-1:0] raddr,
    output reg  [DW-1:0] rdata
);
  reg [DW-1:0] m [0:(1 << AW) - 1];
  always @(posedge clk) begin
    if (we) m[waddr] <= wdata;
    rdata <= m[raddr];
  end
endmodule
