`default_nettype none

// v0core: the timeline core. It runs programs in the ISA v0 format with the
// timing of the Python model (sw/protoemu/v0.py), cycle for cycle. The
// cocotb test (test/test.py) checks that.
//
// One instruction issues per cycle unless the core stalls. Costs:
//   most ops 1 cycle; djnz/bz/bnz taken and jmp 2 cycles (1 bubble);
//   a timed action waits until now == floor(T), then takes 1 cycle;
//   get/geth take 1 + IN_LAT cycles after the sample; wait takes the edge
//   time + IN_LAT + 1.
//
// Time: `now` counts cycles. T is the timeline cursor, 24.8 fixed point.
// floor(T) is compared with now modulo 2^24, so deadlines must be less than
// 2^23 cycles ahead (the encoding limits a delay to 2^15).
//
// Pins come from registers. A pin decision in cycle c shows on the pin in
// cycle c + 1. So the core's pins are the model's bus, 1 cycle later.
// Inputs pass 2 synchronizer flip-flops. A bus level reaches the core
// IN_LAT = 3 cycles after the model cycle it belongs to.
//
// Program memory reads synchronously. The core gives the address of the
// next instruction (mem_raddr = pc_next) one cycle ahead, so the read costs
// no cycle. In reset, mem_raddr is 0.

module v0core #(
    parameter PW = 6  // program address width
) (
    input  wire          clk,
    input  wire          rst_n,
    // Program memory read port: mem_rdata is the word at last cycle's mem_raddr.
    output wire [PW-1:0] mem_raddr,
    input  wire [37:0]   mem_rdata,
    // Host FIFOs. hin_pop and hout_push are high in the issue cycle.
    input  wire          hin_valid,
    input  wire [7:0]    hin_data,
    output wire          hin_pop,
    output wire          hout_push,
    output wire [15:0]   hout_data,
    // Pins 0-5 OUT, 8-15 IO, 16-19 IN. pin_in is the bus level, not synced.
    input  wire [19:0]   pin_in,
    output reg  [19:0]   pin_out,  // level, or 0 to pull low (open drain)
    output reg  [19:0]   pin_pp,   // 1: the core drives pin_out
    output reg  [19:0]   pin_od,   // 1: the core pulls low when pin_out is 0
    output reg  [23:0]   now,
    output reg           late,
    output reg           halted
);

  localparam IN_LAT = 3;

  // Opcodes: the same order as sw/protoemu/v0enc.py OPCODES.
  localparam OP_HALT = 5'd0,  OP_LDI = 5'd1,   OP_MOV = 5'd2,   OP_ADDI = 5'd3,
             OP_ANDI = 5'd4,  OP_XORI = 5'd5,  OP_SHLI = 5'd6,  OP_SHRI = 5'd7,
             OP_DJNZ = 5'd8,  OP_BZ = 5'd9,    OP_BNZ = 5'd10,  OP_JMP = 5'd11,
             OP_DLY = 5'd12,  OP_SYNC = 5'd13, OP_WAITT = 5'd14, OP_WAIT = 5'd15,
             OP_CFG = 5'd16,  OP_SET = 5'd17,  OP_PUT = 5'd18,  OP_PUTH = 5'd19,
             OP_GET = 5'd20,  OP_GETH = 5'd21, OP_PULL = 5'd22, OP_PUSH = 5'd23;

  localparam S_RUN = 3'd0, S_BUBBLE = 3'd1, S_SAMPLE = 3'd2, S_WAIT = 3'd3,
             S_HALT = 3'd4;

  // ---- decode ----
  wire [37:0] ins = mem_rdata;
  wire [4:0]  op  = ins[37:33];
  wire [4:0]  fa  = ins[32:28];
  wire [22:0] fd  = ins[22:0];
  wire timed = (op == OP_SET) || (op == OP_PUT) || (op == OP_PUTH) ||
               (op == OP_GET) || (op == OP_GETH);
  wire [15:0] fb  = timed ? {11'd0, ins[27:23]} : ins[15:0];

  // ---- state ----
  reg [PW-1:0] pc;
  reg [2:0]  state;
  reg [31:0] T;
  reg [15:0] r [0:7];
  reg [19:0] sync1, sync2;
  reg [1:0]  cnt;
  reg [2:0]  s_reg;  // get/geth: destination, pin, and bit order
  reg [4:0]  s_pin;
  reg        s_msb;

  wire [2:0]  ra  = fa[2:0];
  wire [15:0] rva = r[ra];
  wire [15:0] rvb = r[fb[2:0]];
  wire [15:0] dec = rva - 16'd1;
  wire [PW-1:0] target = fb[PW-1:0];
  wire [PW-1:0] pc_inc = pc + 1'b1;

  // Wrap-safe compare of floor(T) with now.
  wire [23:0] diff    = T[31:8] - now;
  wire        not_yet = !diff[23] && diff != 24'd0;  // floor(T) > now
  wire        is_late = diff[23];                    // floor(T) < now

  // An instruction issues in this cycle.
  wire issue = rst_n && (state == S_RUN) && !((timed || op == OP_WAITT) && not_yet);
  wire edge_seen = sync2[fa] == fb[0];

  assign hin_pop   = issue && op == OP_PULL && hin_valid;
  assign hout_push = issue && op == OP_PUSH;
  assign hout_data = rva;

  // ---- next pc (also the memory read address) ----
  reg [PW-1:0] pc_next;
  always @(*) begin
    pc_next = pc;
    case (state)
      S_SAMPLE: if (cnt == 2'd0) pc_next = pc_inc;
      S_WAIT:   if (edge_seen) pc_next = pc_inc;
      S_RUN: if (issue) begin
        case (op)
          OP_HALT, OP_WAIT, OP_GET, OP_GETH: pc_next = pc;
          OP_DJNZ: pc_next = (dec != 16'd0) ? target : pc_inc;
          OP_BZ:   pc_next = (rva == 16'd0) ? target : pc_inc;
          OP_BNZ:  pc_next = (rva != 16'd0) ? target : pc_inc;
          OP_JMP:  pc_next = target;
          default: pc_next = pc_inc;
        endcase
      end
      default: ;
    endcase
  end
  assign mem_raddr = rst_n ? pc_next : {PW{1'b0}};

  wire taken = (op == OP_JMP) || (op == OP_DJNZ && dec != 16'd0) ||
               (op == OP_BZ && rva == 16'd0) || (op == OP_BNZ && rva != 16'd0);

  integer i;

  always @(posedge clk) begin
    if (!rst_n) begin
      state   <= S_RUN;
      pc      <= {PW{1'b0}};
      now     <= 24'd0;
      T       <= 32'd0;
      late    <= 1'b0;
      halted  <= 1'b0;
      pin_out <= {20{1'b1}};
      pin_pp  <= 20'd0;
      pin_od  <= 20'd0;
      sync1   <= {20{1'b1}};
      sync2   <= {20{1'b1}};
      cnt     <= 2'd0;
      s_reg   <= 3'd0;
      s_pin   <= 5'd0;
      s_msb   <= 1'b0;
      for (i = 0; i < 8; i = i + 1) r[i] <= 16'd0;
    end else begin
      now   <= now + 24'd1;
      sync1 <= pin_in;
      sync2 <= sync1;
      pc    <= pc_next;

      case (state)
        S_BUBBLE: state <= S_RUN;

        S_SAMPLE: begin
          if (cnt == 2'd0) begin
            if (s_msb) r[s_reg] <= {r[s_reg][14:0], sync2[s_pin]};
            else       r[s_reg] <= {8'd0, sync2[s_pin], r[s_reg][7:1]};
            state <= S_RUN;
          end else begin
            cnt <= cnt - 2'd1;
          end
        end

        S_WAIT: if (edge_seen) begin
          T     <= {now - IN_LAT[23:0], 8'd0};
          state <= S_RUN;
        end

        S_HALT: ;

        default: if (issue) begin  // S_RUN
          if (timed) begin
            if (is_late) late <= 1'b1;
            T <= T + {9'd0, fd};
          end
          if (taken) state <= S_BUBBLE;
          case (op)
            OP_HALT: begin halted <= 1'b1; state <= S_HALT; end
            OP_LDI:  r[ra] <= fb;
            OP_MOV:  r[ra] <= rvb;
            OP_ADDI: r[ra] <= rva + fb;
            OP_ANDI: r[ra] <= rva & fb;
            OP_XORI: r[ra] <= rva ^ fb;
            OP_SHLI: r[ra] <= rva << fb[3:0];
            OP_SHRI: r[ra] <= rva >> fb[3:0];
            OP_DJNZ: r[ra] <= dec;
            OP_DLY:  T <= T + {9'd0, fd};
            OP_SYNC: T <= {now + 24'd1, 8'd0};
            OP_WAIT: state <= S_WAIT;
            OP_CFG: begin
              pin_pp[fa]  <= fb[1:0] == 2'd1 || fb[1:0] == 2'd3;
              pin_od[fa]  <= fb[1:0] == 2'd2;
              pin_out[fa] <= fb[1:0] != 2'd3;
            end
            OP_SET:  pin_out[fa] <= fb[0];
            OP_PUT: begin
              pin_out[fa] <= rvb[0];
              r[fb[2:0]]  <= rvb >> 1;
            end
            OP_PUTH: begin
              pin_out[fa] <= rvb[7];
              r[fb[2:0]]  <= {8'd0, rvb[6:0], 1'b0};
            end
            OP_GET, OP_GETH: begin
              s_reg <= ra;
              s_pin <= fb[4:0];
              s_msb <= op == OP_GETH;
              cnt   <= IN_LAT[1:0] - 2'd1;
              state <= S_SAMPLE;
            end
            OP_PULL: r[ra] <= hin_valid ? {8'd0, hin_data} : 16'h0100;
            default: ;
          endcase
        end
      endcase
    end
  end

`ifdef FORMAL
  // Check only after a reset: the registers have no power-on value.
  reg f_rst = 1'b0;
  always @(posedge clk) if (!rst_n) f_rst <= 1'b1;
  // The state register holds one of the 5 states.
  always @(*) if (f_rst) a_state: assert (state <= S_HALT);
  // A sample counts down from IN_LAT - 1.
  always @(*) if (f_rst && state == S_SAMPLE) a_cnt: assert (cnt <= IN_LAT - 1);
  // The halted flag and the halt state agree.
  always @(*) if (f_rst) a_halt: assert (halted == (state == S_HALT));
  // The core does not touch the host FIFOs unless it issues.
  always @(*) a_fifo: assert (!(hin_pop || hout_push) || issue);
`endif

endmodule
