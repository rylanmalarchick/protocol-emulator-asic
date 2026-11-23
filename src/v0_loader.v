`default_nettype none

// The load port: an SPI target (mode 0, MSB first) on the system clock.
// It samples CS, SCK, and MOSI through 2 flip-flops each, so SCK must be
// at most clk/8 (6.25 MHz at 50 MHz).
//
// A frame starts when CS goes low. The chip returns the status byte as the
// first byte of every frame. The first byte from the host is the command:
//
//   0x00 NOP
//   0x01 PROG_WRITE  addr, then 5 bytes per word. RUN must be low.
//   0x02 HOST_WRITE  bytes for the host-in FIFO (the core reads them with pull)
//   0x03 HOST_READ   3 bytes per entry of the host-out FIFO: valid, high, low
//   0x04 PROG_READ   addr, then 5 bytes per word. RUN must be low.
//   0x05 CLEAR       empty both FIFOs and clear the overflow flag
//
// Status byte: [7:6] = 2'b10, [5] overflow, [4] host-in full,
// [3] host-out has data, [2] late, [1] halted, [0] run.

module v0_loader #(
    parameter PW = 6
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          cs_n_in,  // asynchronous pins
    input  wire          sck_in,
    input  wire          mosi_in,
    output wire          miso,
    input  wire          run,      // synchronized RUN
    input  wire          halted,
    input  wire          late,
    // program memory
    output wire          prog_we,
    output reg  [PW-1:0] prog_addr,
    output wire [37:0]   prog_wdata,
    input  wire [37:0]   prog_rdata,
    // host FIFOs, core side
    output wire          hin_valid,
    output wire [7:0]    hin_data,
    input  wire          hin_pop,
    input  wire          hout_push,
    input  wire [15:0]   hout_data,
    output wire          hout_ready  // the host-out FIFO has data
);
  localparam CMD_PROG_WRITE = 8'h01, CMD_HOST_WRITE = 8'h02,
             CMD_HOST_READ = 8'h03, CMD_PROG_READ = 8'h04, CMD_CLEAR = 8'h05;

  // ---- synchronizers ----
  reg [1:0] cs_q, sck_q, mosi_q;
  reg       sck_d;
  wire cs_n = cs_q[1];
  wire sck  = sck_q[1];
  wire mosi = mosi_q[1];
  wire rise = sck && !sck_d;
  wire fall = !sck && sck_d;

  // ---- frame state ----
  reg [2:0]  bitcnt;
  reg [6:0]  rx;
  reg [7:0]  tx;
  reg [7:0]  cmd;
  reg [1:0]  bidx;   // byte index in the frame, stops at 2
  reg [2:0]  wsub;   // byte in the word being written
  reg [2:0]  rsub;   // byte in the word or entry being read
  reg [39:0] word;
  reg        we_q;    // a word is complete
  reg [16:0] hold;   // host-out entry being read: valid, data
  reg        tx_lo;  // tx holds the low byte of a valid entry
  reg        overflow;
  reg        clear;

  wire [7:0] b = {rx, mosi};
  wire byte_done = !cs_n && rise && bitcnt == 3'd7;

  assign miso = !cs_n && tx[7];
  assign prog_wdata = word[37:0];
  assign prog_we = we_q && !run;

  // ---- FIFOs ----
  wire hin_push = byte_done && bidx != 2'd0 && cmd == CMD_HOST_WRITE;
  wire hout_pop = byte_done && tx_lo;
  wire hin_empty, hin_full, hin_drop, hout_empty, hout_full, hout_drop;
  wire [15:0] hout_dout;

  v0_fifo #(.W(8), .LD(4)) hin (
      .clk(clk), .rst_n(rst_n), .clear(clear),
      .push(hin_push), .din(b), .pop(hin_pop), .dout(hin_data),
      .empty(hin_empty), .full(hin_full), .drop(hin_drop));

  v0_fifo #(.W(16), .LD(4)) hout (
      .clk(clk), .rst_n(rst_n), .clear(clear),
      .push(hout_push), .din(hout_data), .pop(hout_pop), .dout(hout_dout),
      .empty(hout_empty), .full(hout_full), .drop(hout_drop));

  assign hin_valid  = !hin_empty;
  assign hout_ready = !hout_empty;

  wire [7:0] status = {2'b10, overflow, hin_full, !hout_empty, late, halted, run};
  wire [39:0] rd40 = {2'b00, prog_rdata};

  // The next byte to send, at a byte boundary.
  reg [7:0] tx_next;
  always @(*) begin
    tx_next = 8'd0;
    if (cmd == CMD_HOST_READ) begin
      case (rsub)
        3'd0:    tx_next = {7'd0, !hout_empty};
        3'd1:    tx_next = hold[15:8];
        default: tx_next = hold[7:0];
      endcase
    end else if (cmd == CMD_PROG_READ && bidx == 2'd2) begin
      case (rsub)
        3'd0:    tx_next = rd40[39:32];
        3'd1:    tx_next = rd40[31:24];
        3'd2:    tx_next = rd40[23:16];
        3'd3:    tx_next = rd40[15:8];
        default: tx_next = rd40[7:0];
      endcase
    end
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      cs_q     <= 2'b11;
      sck_q    <= 2'b00;
      mosi_q   <= 2'b00;
      sck_d    <= 1'b0;
      bitcnt   <= 3'd0;
      rx       <= 7'd0;
      tx       <= 8'd0;
      cmd      <= 8'd0;
      bidx     <= 2'd0;
      wsub     <= 3'd0;
      rsub     <= 3'd0;
      word     <= 40'd0;
      hold     <= 17'd0;
      tx_lo    <= 1'b0;
      overflow <= 1'b0;
      clear    <= 1'b0;
      we_q     <= 1'b0;
      prog_addr <= {PW{1'b0}};
    end else begin
      cs_q   <= {cs_q[0], cs_n_in};
      sck_q  <= {sck_q[0], sck_in};
      mosi_q <= {mosi_q[0], mosi_in};
      sck_d  <= sck;
      clear  <= 1'b0;
      we_q    <= 1'b0;
      if (hin_drop || hout_drop) overflow <= 1'b1;
      if (we_q) prog_addr <= prog_addr + 1'b1;  // after the write

      if (cs_n) begin
        bitcnt <= 3'd0;
        cmd    <= 8'd0;
        bidx   <= 2'd0;
        wsub   <= 3'd0;
        rsub   <= 3'd0;
        tx_lo  <= 1'b0;
        tx     <= status;
      end else begin
        if (rise) begin
          bitcnt <= bitcnt + 3'd1;
          rx     <= b[6:0];
        end
        if (byte_done) begin
          if (bidx != 2'd2) bidx <= bidx + 2'd1;
          if (tx_lo) tx_lo <= 1'b0;
          if (bidx == 2'd0) begin
            cmd <= b;
            if (b == CMD_CLEAR) begin
              clear    <= 1'b1;
              overflow <= 1'b0;
            end
          end else if (bidx == 2'd1 &&
                       (cmd == CMD_PROG_WRITE || cmd == CMD_PROG_READ)) begin
            prog_addr <= b[PW-1:0];
          end else if (cmd == CMD_PROG_WRITE) begin
            word <= {word[31:0], b};
            if (wsub == 3'd4) begin
              wsub    <= 3'd0;
              we_q    <= 1'b1;
            end else begin
              wsub <= wsub + 3'd1;
            end
          end
        end
        if (fall) begin
          if (bitcnt == 3'd0) begin
            tx <= tx_next;
            if (cmd == CMD_HOST_READ) begin
              case (rsub)
                3'd0: begin
                  hold <= {!hout_empty, hout_dout};
                  rsub <= 3'd1;
                end
                3'd1: rsub <= 3'd2;
                default: begin
                  tx_lo <= hold[16];
                  rsub  <= 3'd0;
                end
              endcase
            end else if (cmd == CMD_PROG_READ && bidx == 2'd2) begin
              if (rsub == 3'd4) begin
                rsub      <= 3'd0;
                prog_addr <= prog_addr + 1'b1;
              end else begin
                rsub <= rsub + 3'd1;
              end
            end
          end else begin
            tx <= {tx[6:0], 1'b0};
          end
        end
      end
    end
  end

`ifdef FORMAL
  // The loader never writes the program while the core runs.
  always @(*) a_we_run: assert (!(prog_we && run));
`endif
endmodule
