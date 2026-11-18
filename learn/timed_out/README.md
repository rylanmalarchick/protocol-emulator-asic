# timed_out: a learning block

A 16-bit timer and one timed pin action. It is the hardware for "drive the pin
at cycle T" in the Probe A model. It is not chip RTL. Read `timed_out.v` first:
the comments give the timing contract.

## Run

```sh
make -B          # cocotb tests, one per line of the timing contract
make formal      # SymbiYosys: proves the properties for all cycles (k-induction)
```

Synthesis to IHP cells, with `LIB` set to the `sg13cmos5l_stdcell_typ_1p20V_25C.lib`
file in the PDK:

```sh
yosys -p "read_verilog timed_out.v; synth -top timed_out; dfflegalize -cell \$_DFF_P_ 01; \
  dfflibmap -liberty $LIB; abc -liberty $LIB; opt_clean; stat -liberty $LIB"
```

## Results

| Measure | Value |
|---|---|
| Cells | 212 |
| Area | 3404 um^2 (one tile is about 167 x 108 = 18036 um^2) |
| Flip-flops | 36 (`now` 16, `due` 16, `pin`, `v`, `armed`, `late`), about half the area |

Mutation check: change `lead` to `due - now` (the action fires 1 cycle late).
4 of 5 cocotb tests fail, and formal fails at `a_on_time`.

## Lessons for the chip

1. The minimum lead is 2 cycles: 1 cycle to store the request, 1 cycle for the
   output flip-flop. The assembler must know this number.
2. Wrap-safe compare is one subtract and one sign bit. It holds while every
   deadline is less than 2^15 cycles ahead. The checker must enforce that bound.
3. Each due-time register costs about 16 flip-flops. One compare unit per pin,
   for 22 pins, is about 4600 cells. A shared event queue with one comparator
   costs less logic but limits how many edges can happen in the same cycle.
   That trade-off is an ISA decision.
4. In cocotb, read registers in `ReadOnly`. Right after `RisingEdge`, a read
   returns the value from before the edge.
