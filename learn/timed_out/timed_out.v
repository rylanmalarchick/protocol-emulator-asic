`default_nettype none

// timed_out: one timed pin action. A learning block, not chip RTL.
//
// This is the hardware for "pinLow at T" / "pinHigh at T" in the Probe A
// model (lean/ProtoEmu/Probe/UartTx.lean). Two parts:
//
//   1. A 16-bit free-running timer `now`. It counts clock cycles and wraps.
//   2. An output-compare unit. Pulse `arm` for one cycle with (t_due, val).
//      The unit drives `pin` to `val` from cycle t_due on.
//
// Timing contract (the cocotb test checks each line):
//   - `now` reads c in cycle c. It counts up by 1 each cycle.
//   - `arm` in cycle c with t_due >= c + 2 is on time: pin == val from
//     cycle t_due on. The unit needs 1 cycle to store the request and 1
//     cycle to drive the output flip-flop.
//   - `arm` with t_due < c + 2 is late: pin == val from cycle c + 2, and the
//     sticky `late` flag goes high. This matches the Lean rule "act at
//     max(now, T) and set late".
//
// Time compare with wrap: "is t_due in the past?" is the sign bit of
// (t_due - now) mod 2^16. This is correct while every deadline is less than
// 2^15 cycles ahead (655 us at 50 MHz). The assembler must check that bound.

module timed_out (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        arm,
    input  wire [15:0] t_due,
    input  wire        val,
    output reg  [15:0] now,
    output reg         pin,
    output reg         armed,
    output reg         late
);

  reg [15:0] due;
  reg        v;

  // Cycles left until the pin must show the new value, minus the 1 cycle the
  // output flip-flop needs. Zero means "fire now". Negative means "late".
  wire [15:0] lead = due - now - 16'd1;
  wire        fire = armed && (lead == 16'd0 || lead[15]);

  always @(posedge clk) begin
    if (!rst_n) begin
      now   <= 16'd0;
      pin   <= 1'b1;  // idle high, like a UART line
      armed <= 1'b0;
      late  <= 1'b0;
      due   <= 16'd0;
      v     <= 1'b0;
    end else begin
      now <= now + 16'd1;
      if (fire) begin
        pin   <= v;
        armed <= 1'b0;
        if (lead != 16'd0) late <= 1'b1;
      end
      // A new request in the same cycle as a fire wins: the old action still
      // drives the pin, and the new one is armed.
      if (arm) begin
        due   <= t_due;
        v     <= val;
        armed <= 1'b1;
      end
    end
  end

`ifdef FORMAL
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

  initial assume (!rst_n);

  always @(posedge clk) begin
    if (f_past_valid && $past(rst_n)) begin
      // The timer counts every cycle.
      a_count: assert (now == $past(now) + 16'd1);
      // The pin changes only when an armed action fires.
      a_pin_only_on_fire: assert (pin == $past(pin) || $past(fire));
      // An on-time fire lands exactly at the due cycle.
      if ($past(fire) && $past(lead) == 16'd0) begin
        a_on_time: assert (pin == $past(v) && now == $past(due));
      end
      // `late` is sticky.
      if ($past(late)) a_late_sticky: assert (late);
    end
  end
`endif

endmodule
