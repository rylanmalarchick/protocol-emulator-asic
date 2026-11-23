# v0core: a learning core for the ISA v0 proposal

A Verilog core that runs the programs in `sw/programs/v0`. It is not chip
RTL. It shows that the v0 timing model can be built, and it measures the
cost.

## Run

```sh
make -B     # cocotb: 9 program runs, RTL against the Python model
```

The test runs each program on the RTL and on `protoemu.v0.Sim` with the same
peer devices. It checks three things:

1. Every pin in every cycle. The RTL is 1 cycle behind the model, because
   the pins come from a register.
2. Each instruction issues in the same cycle with the same T. Pins alone
   miss timing errors that a stall hides.
3. The host output, the late flag, and the halt cycle.

## Results

| Run | Result |
|---|---|
| UART TX at 1 Mbaud, and at BIT = 7 (late) | match |
| UART RX, sender 2% slow | match |
| SPI modes 0 and 3 | match |
| I2C 400 kHz with 200-cycle clock stretching, and NACK | match |
| WS2812, 2 LEDs | match |
| 1-Wire READ ROM (slots 10x faster) | match |

Mutations the test catches:

| Change in the RTL | Fails |
|---|---|
| Input latency 2, not 3 | 5 of 9 |
| A taken `djnz` without its bubble cycle | 9 of 9 |
| `puth` shifts the wrong way | 5 of 9 |
| `dly` adds 1/256 cycle too much | 5 of 9 |

The pin check alone missed the first two. The issue check catches them.

## What the RTL taught the model

The first model charged 2 cycles of input latency (the 2 synchronizer
flip-flops). A core with registered pins puts the whole bus 1 cycle behind
its decisions, so an input reaches the core 3 cycles after it is on the
bus. The model now uses IN_LAT = 3. The SPI minimum half period moved from
14 to 15 cycles.

## Size (Yosys, IHP sg13cmos5l typical library, no place and route)

| Part | Cells | Area |
|---|---|---|
| Core without program memory | 2511 (331 flip-flops) | 38418 um^2 |
| Program memory as flip-flops, 256 x 49 bits | 12544 flip-flops | 1019516 um^2 |

The core fits: Jane Street budgets about 1000 cells per tile. The program
memory does not fit as flip-flops. It needs an SRAM macro. Macros in the
PDK (`sg13cmos5l_sram/lef`):

| Macro | Size |
|---|---|
| RM_IHPSG13_1P_256x48 | 596.48 x 118.78 um (0.071 mm^2) |
| RM_IHPSG13_1P_256x64 | 784.48 x 118.78 um (0.093 mm^2) |
| RM_IHPSG13_1P_512x32 | 416.64 x 191.34 um (0.080 mm^2) |

The 49-bit word is 1 bit too wide for the 256 x 48 macro. A 48-bit
encoding would use the smaller macro. The macros read synchronously, so the
core would need a fetch stage. That changes branch costs, and the model must
follow.

## Limits

- Program memory reads asynchronously here (behavioral model).
- The host FIFO is a simple valid/pop port, not the SPI load port in
  `info.yaml`.
- No formal properties yet.
