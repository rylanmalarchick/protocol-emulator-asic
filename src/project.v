/*
 * Copyright (c) 2026 Rylan Malarchick, Lucca DiMario
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Protocol emulator top. See docs/info.md for the pins and the load port.
//
//   ui[0] LOAD_CS_N  ui[1] LOAD_SCK  ui[2] LOAD_MOSI  ui[3] RUN  ui[7:4] IN3..IN0
//   uo[0] LOAD_MISO  uo[1] STATUS    uo[7:2] OUT5..OUT0
//   uio[7:0] IO7..IO0
//
// RUN low holds the core in reset: the IO pins are inputs, the OUT pins are
// high, and the host can load a program. RUN high starts the program at
// address 0. The host FIFOs keep their data across RUN, so the host can
// queue bytes before it starts the core.

module tt_um_rylanmalarchick_protoemu (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);
  localparam PW = 6;  // 64 program words

  // RUN: 2 synchronizer flip-flops, then 1 more stage. The core leaves reset
  // 1 cycle after the memory read address switches to the core, so the
  // first instruction is ready in the core's cycle 0.
  reg [2:0] run_q;
  always @(posedge clk) begin
    if (!rst_n) run_q <= 3'b000;
    else        run_q <= {run_q[1:0], ui_in[3]};
  end
  wire run_s   = run_q[1];
  wire core_rn = rst_n && run_q[2];

  // ---- core ----
  wire [19:0] pin_out, pin_pp, pin_od;
  wire [PW-1:0] core_raddr;
  wire [37:0] mem_rdata;
  wire hin_valid, hin_pop, hout_push, hout_ready, late, halted;
  wire [7:0] hin_data;
  wire [15:0] hout_data;
  wire [23:0] now;

  // OUT pins are output only. A pin that the core does not drive is high.
  wire [5:0] out_lvl = pin_out[5:0] | ~(pin_pp[5:0] | pin_od[5:0]);

  v0core #(.PW(PW)) core (
      .clk(clk), .rst_n(core_rn),
      .mem_raddr(core_raddr), .mem_rdata(mem_rdata),
      .hin_valid(hin_valid), .hin_data(hin_data), .hin_pop(hin_pop),
      .hout_push(hout_push), .hout_data(hout_data),
      .pin_in({ui_in[7:4], uio_in, 2'b11, out_lvl}),
      .pin_out(pin_out), .pin_pp(pin_pp), .pin_od(pin_od),
      .now(now), .late(late), .halted(halted));

  // ---- load port and host FIFOs ----
  wire prog_we, miso;
  wire [PW-1:0] prog_addr;
  wire [37:0] prog_wdata;

  v0_loader #(.PW(PW)) loader (
      .clk(clk), .rst_n(rst_n),
      .cs_n_in(ui_in[0]), .sck_in(ui_in[1]), .mosi_in(ui_in[2]), .miso(miso),
      .run(run_s), .halted(halted), .late(late),
      .prog_we(prog_we), .prog_addr(prog_addr), .prog_wdata(prog_wdata),
      .prog_rdata(mem_rdata),
      .hin_valid(hin_valid), .hin_data(hin_data), .hin_pop(hin_pop),
      .hout_push(hout_push), .hout_data(hout_data), .hout_ready(hout_ready));

  // ---- program memory ----
  v0_mem #(.AW(PW), .DW(38)) mem (
      .clk(clk), .we(prog_we), .waddr(prog_addr), .wdata(prog_wdata),
      .raddr(run_s ? core_raddr : prog_addr), .rdata(mem_rdata));

  // ---- pins ----
  wire [7:0] io_pp  = pin_pp[15:8];
  wire [7:0] io_od  = pin_od[15:8];
  wire [7:0] io_out = pin_out[15:8];

  assign uo_out  = {out_lvl, hout_ready, miso};
  assign uio_out = io_out & io_pp;
  assign uio_oe  = io_pp | (io_od & ~io_out);

  wire _unused = &{ena, now, pin_out[19:16], pin_pp[19:16], pin_od[19:16],
                   pin_out[7:6], pin_pp[7:6], pin_od[7:6], 1'b0};

`ifdef FORMAL
  reg f_past = 1'b0;
  always @(posedge clk) f_past <= 1'b1;
  // Start in reset.
  always @(*) if (!f_past) assume (!rst_n);

  always @(posedge clk) if (f_past) begin
    // After a cycle with the core in reset, every IO pin is an input and
    // every OUT pin is high.
    if (!$past(core_rn)) begin
      a_io_off:  assert (uio_oe == 8'h00);
      a_out_hi:  assert (uo_out[7:2] == 6'h3f);
    end
    // A pin that is not push-pull enables its driver only to pull low.
    a_od_low: assert ((uio_oe & ~io_pp & (io_out | uio_out)) == 8'h00);
  end
`endif

endmodule
