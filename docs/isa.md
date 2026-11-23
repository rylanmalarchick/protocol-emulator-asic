# ISA v0

The contract between the chip (`src/v0core.v`) and the program tools
(`sw/protoemu`). The Python model `sw/protoemu/v0.py` is the reference: the
cocotb tests check the chip against it, cycle for cycle. The rationale and
the measured results are in `sw/ISA-v0-proposal.md`.

## State

| State | Width | Reset | Use |
|---|---|---|---|
| `r0`-`r7` | 16 bits each | 0 | registers |
| `pc` | 6 bits | 0 | program counter, 64 words |
| `now` | 24 bits | 0 | cycle counter. Cycle 0 is the first cycle after RUN goes high. |
| `T` | 24.8 fixed point | 0 | timeline cursor, in cycles |
| `late` | 1 bit | 0 | set when a timed action is late. It stays set. |
| pin mode, pin level | per pin | IN, 1 | see Pins |

## Pins

| Pin numbers | Names | Modes allowed |
|---|---|---|
| 0-5 | `OUT0`-`OUT5` | `PP`, `OD`, `PP0` |
| 8-15 | `IO0`-`IO7` | `IN`, `PP`, `OD`, `PP0` |
| 16-19 | `IN0`-`IN3` | `IN` |

Modes (`cfg pin, MODE`):

| Mode | Code | Pin |
|---|---|---|
| `IN` | 0 | not driven. A pin that no device drives reads 1. |
| `PP` | 1 | push-pull. The level starts at 1. |
| `OD` | 2 | open drain. 0 pulls low. 1 releases the line. The level starts at 1 (released). |
| `PP0` | 3 | push-pull. The level starts at 0. |

An OUT pin that is not driven is high. A program reads any pin with `get`,
`geth`, or `wait`. A pin decision takes effect on the pin 1 cycle after the
action cycle. The model hides this offset: its bus is the chip pins 1 cycle
earlier.

## Timeline rules

1. A timed action (`set`, `put`, `puth`, `get`, `geth`) acts in cycle
   `max(now, floor(T))`.
2. If `floor(T) < now` when the action issues, the action is late. The core
   acts at once and sets `late`.
3. After the action, `T := T + d`, where `d` is the delay operand (0 if
   there is none).
4. `get pin` at T reads the level that the pin had in cycle T.
5. `wait pin, level` stalls until the pin has the level, then sets T to the
   cycle in which the pin first had it.
6. An input reaches the core IN_LAT = 3 cycles after it is on the pin. The
   cost shows as stall cycles (see Costs), not as a shift in timestamps.
7. `floor(T)` and `now` compare modulo 2^24. Keep every deadline less than
   2^23 cycles ahead.

## Instructions

| Instruction | Operation |
|---|---|
| `halt` | stop. The status byte shows halted. |
| `ldi ra, imm` | `ra := imm` |
| `mov ra, rb` | `ra := rb` |
| `addi ra, imm` | `ra := ra + imm` (mod 2^16) |
| `andi ra, imm` | `ra := ra & imm` |
| `xori ra, imm` | `ra := ra ^ imm` |
| `shli ra, n` | `ra := ra << n` (n < 16) |
| `shri ra, n` | `ra := ra >> n` (n < 16) |
| `djnz ra, label` | `ra := ra - 1`; jump if `ra != 0` |
| `bz ra, label` | jump if `ra == 0` |
| `bnz ra, label` | jump if `ra != 0` |
| `jmp label` | jump |
| `dly d` | `T := T + d` |
| `sync` | `T := now + 1` |
| `waitt` | stall until `now >= floor(T)` |
| `wait pin, level` | rule 5 |
| `cfg pin, MODE` | set the pin mode and its start level |
| `set pin, level [, +d]` | timed: the pin takes `level` |
| `put pin, rb [, +d]` | timed: the pin takes `rb[0]`; `rb := rb >> 1` |
| `puth pin, rb [, +d]` | timed: the pin takes `rb[7]`; `rb := (rb << 1) & 0xFF` |
| `get ra, pin [, +d]` | timed: `ra := (ra >> 1) \| (level << 7)` (LSB first, 8 bits) |
| `geth ra, pin [, +d]` | timed: `ra := (ra << 1) \| level` (MSB first) |
| `pull ra` | `ra :=` next host-in byte, or `0x100` if the FIFO is empty |
| `push ra` | append `ra` to the host-out FIFO |

## Costs

| Instruction | Cycles |
|---|---|
| `ldi mov addi andi xori shli shri dly sync cfg pull push` | 1 |
| `djnz bz bnz` | 1, or 2 if taken |
| `jmp` | 2 |
| `set put puth` | until the action cycle, + 1 |
| `get geth` | until the sample cycle, + 1 + IN_LAT |
| `wait` | until the edge cycle, + 1 + IN_LAT |
| `waitt` | until `floor(T)`, + 1 |

## Encoding

One 38-bit word per instruction. The load port sends it as 5 bytes, MSB
first, with 2 zero bits on top.

| Bits | Timed actions | `dly` | Other ops |
|---|---|---|---|
| 37:33 | opcode | opcode | opcode |
| 32:28 | A: pin (`set put puth`) or register (`get geth`) | 0 | A: register or pin |
| 27:23 | B: level, register, or pin | 0 | 0 |
| 22:0 | D: delay, 15.8 fixed point | D | bits 22:16 are 0; bits 15:0 are B: immediate, target, register, mode, or level |

`jmp` puts its target in B. Opcodes:

| Code | Op | Code | Op | Code | Op |
|---|---|---|---|---|---|
| 0 | `halt` | 8 | `djnz` | 16 | `cfg` |
| 1 | `ldi` | 9 | `bz` | 17 | `set` |
| 2 | `mov` | 10 | `bnz` | 18 | `put` |
| 3 | `addi` | 11 | `jmp` | 19 | `puth` |
| 4 | `andi` | 12 | `dly` | 20 | `get` |
| 5 | `xori` | 13 | `sync` | 21 | `geth` |
| 6 | `shli` | 14 | `waitt` | 22 | `pull` |
| 7 | `shri` | 15 | `wait` | 23 | `push` |

Codes 24-31 are reserved. The core does nothing for them for 1 cycle.

## Tests

`test/test.py` runs UART TX and RX, SPI modes 0 and 3, I2C with clock
stretching and NACK, WS2812, 1-Wire, and an ALU self-test on the chip. Each
instruction runs in at least one of them, and each run checks every pin and
every instruction issue against the model. `sw/protoemu/v0check.py` proves
the deadlines of a program without running it.
