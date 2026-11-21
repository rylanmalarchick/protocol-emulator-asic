# ISA v0

This document is the contract between the chip side (RTL) and the program
side (assembler, timing checker, firmware). A change to this document needs a
PR that both people approve. See `AGENTS.md`, "ISA contract".

Until the Lean model of v0 exists, this document is the specification. After
it exists, the Lean `exec` function is the specification, and this document
describes it.

## Design rules

| Rule | Statement |
|---|---|
| P1 | Total semantics. Every 16-bit word has a defined meaning. An undefined encoding, a set reserved bit, or a bad pin index halts the engine and sets `ILL`. |
| P2 | Fixed cycle counts. The only variable waits are the stalls listed in [Cycle counts](#cycle-counts). Each one is a function of the program and the input pins only. |
| P3 | No hidden shared state. The two engines share only `NOW`, the input pin levels, and the host port. Each engine owns its output pins and its capture units. The host sets the ownership before `RUN`. |
| P4 | One source of truth. The RTL is proved against the specification. The assembler encodes from the same table. |
| P5 | Timed actions. A timed action fires at `max(c + L, floor(T))`, where `c` is the cycle the engine loads the compare unit. If `floor(T) < c + L`, the action fires late and sets `LATE`. The timing checker shows that an accepted program never sets `LATE`. |

## Constants

| Name | Value | Meaning |
|---|---|---|
| `S` | 2 | Input synchronizer depth in cycles. |
| `L` | 1 | Cycles from loading a compare unit to the earliest pin change. |
| Clock | 60 MHz | One cycle is 16.67 ns. |

The cocotb tests assert `S` and `L` exactly. A change to either value is a
change to this document.

## Machine state

Global:

| Name | Width | Meaning |
|---|---|---|
| `NOW` | 16 | Cycle counter. Increments every cycle and wraps. |

Per engine (two engines, `E0` and `E1`, both run every cycle):

| Name | Width | Meaning |
|---|---|---|
| `pc` | 9 | Program counter. |
| `r0` | 16 | Reads 0. Writes are discarded. |
| `r1` to `r7` | 16 | General registers. |
| `T` | 16.8 | Timeline cursor: 16 integer bits, 8 fraction bits. Timed actions use `floor(T)`. |
| `P0` to `P3` | 16.8 | Period registers. Same format as `T`. |
| `CAP` | 16 | Timestamp of the last captured edge. |
| Memory | 512 x 16 | Program and data. One memory per engine. |
| Flags | 1 each | `E` edge seen, `A` abort pin fired, `LATE`, `OVF` FIFO overflow, `M` missed edge, `ILL` illegal instruction. |
| `FE` | 1 | Status, not a flag: the FIFO from the host is empty. |

Per output pin: one compare unit. Per input pin: one capture unit. See
[Compare units](#compare-units) and [Capture units](#capture-units).

### Time arithmetic

`NOW` and `floor(T)` are 16-bit values. Every comparison between them uses
the signed 16-bit difference `d(a, b) = (a - b) mod 2^16`, read as a signed
number. "`a` is before `b`" means `d(a, b) < 0`. The assembler checks that
every timed action and every wait targets a time less than 2^15 cycles from
the cycle it issues. This makes the wrap safe.

## Pins

Pin index field `pppp`:

| Index | Output pin | Input pin |
|---|---|---|
| 0 to 3 | `OUT0` to `OUT3` (`uo[2..5]`) | `IN0` to `IN3` (`ui[4..7]`) |
| 4, 5 | `OUT4`, `OUT5` (`uo[6..7]`) | none |
| 6, 7 | none | none |
| 8 to 15 | `IO0` to `IO7` (`uio[0..7]`) | `IO0` to `IO7` (`uio[0..7]`) |

An instruction that names "none" halts with `ILL`.

After reset, every `OUT` pin is low and every `IO` pin is released.

An `IO` pin drives `uio_out` and enables `uio_oe` when the engine drives it
low or high. The `release` action disables `uio_oe`. A pin that is only
driven low or released acts as an open-drain line.

Both engines read the level of every input pin. Each output pin and each
capture unit has one owner engine. The host sets a 14-bit output owner mask
and a 12-bit capture owner mask before `RUN`. An action on a pin that the
engine does not own halts with `ILL`.

## Compare units

Each output pin has one compare unit. A compare unit holds at most one
pending action: a fire cycle and a level (low, high, release, or toggle).

1. A timed action (`@` = 1) loads the compare unit with fire cycle
   `max(c + L, floor(T))`. `c` is the cycle of the load.
2. An immediate action (`@` = 0) loads the compare unit with fire cycle
   `c + L`.
3. The pin has the new level from the fire cycle on. `toggle` drives the
   inverse of the last level the compare unit drove (low or high). Before
   the first drive, that level is low.
4. If the compare unit has a pending action with a fire cycle after `c`, the
   engine stalls until the fire cycle. Then it loads the unit. So two
   changes on one pin are at least 1 cycle apart.
5. Two compare units with the same fire cycle change their pins in the same
   cycle. This gives an atomic change on more than one pin.

After the load, the engine continues with the next instruction. It does not
wait for the fire cycle.

## Capture units

Each input pin has one capture unit. It holds an edge mode (rise, fall, or
any), an enable bit, a `seen` bit, and a 16-bit timestamp.

1. `ARM rX` sets the mode and the enable bit of one capture unit and clears
   its `seen` bit.
2. When the unit is enabled, `seen` is 0, and a matching edge reaches the
   synchronizer output, the unit sets `seen` and stores the timestamp. The
   timestamp is the bus cycle of the edge: the synchronizer output cycle
   minus `S`.
3. When `seen` is 1 and another matching edge arrives, the unit keeps the
   first timestamp and sets the owner engine's `M` flag.
4. `WAITE` on the pin reads the timestamp and clears `seen`. The unit stays
   enabled with the same mode.

An edge that arrives before `WAITE` issues is not lost. `WAITE` finds `seen`
set and completes without a stall.

## Abort pin

Each engine has one abort setting: an input pin index, an edge (rise, fall,
or any), and an enable bit. `ABRT rX` loads it. While it is enabled, `WAITE`
also ends when the abort pin sees its edge. The abort pin has its own edge
detector. It does not use a capture unit. Timed actions do not check the
abort pin.

## Host port

When `RUN` is low, the host uses the SPI program-load port to:

1. write both program memories,
2. write the output owner mask and the capture owner mask,
3. read the flags of both engines.

When `RUN` is high, each engine has a 4-word FIFO from the host and a 4-word
FIFO to the host. Each word is 16 bits.

`STATUS` (`uo[1]`) is high while at least one engine runs.

The bit-level protocol of the program-load port is not part of v0. It goes
into this document with the program loader RTL.

## Instruction encoding

Bit 15 is on the left. `xxx`, `yyy`: register index. `pppp`: pin index.
`qq`: period register index. `-`: reserved, must be 0.

| Op | Mnemonic | Encoding | Operation |
|---|---|---|---|
| 0 | `SYS` | `0000 ssss -xxx yyy-` | See [SYS sub-operations](#sys-sub-operations). |
| 1 | `DLY imm12` | `0001 iiii iiii iiii` | `T <- T + imm12` (integer part, unsigned). |
| 2 | `DLYR rX` | `0010 xxx- ---- ----` | `T <- T + rX` (integer part, unsigned). |
| 3 | `PIN` | `0011 @aa- -dqq pppp` | Action `aa` on pin `p`: 00 low, 01 high, 10 release, 11 toggle. |
| 4 | `PUT` | `0100 @xxx mdqq pppp` | Drive one bit of `rX` on pin `p`, then shift `rX`. |
| 5 | `GET` | `0101 @xxx mdqq pppp` | Sample pin `p`, then shift the bit into `rX`. |
| 6 | `WAITE` | `0110 txxx ---- pppp` | Wait for the capture unit of pin `p`, the abort pin, or `floor(T)`. |
| 7 | `LDI` | `0111 xxxh iiii iiii` | Load one byte of `rX`. `h` = 1: bits 15..8. `h` = 0: bits 7..0. The other byte is kept. |
| 8 | `ALU` | `1000 xxxy yyff f---` | `rX <- rX op rY`. `fff`: add, sub, and, or, xor, shl, shr, mov. `shl` and `shr` shift by `rY[3:0]`. |
| 9 | `ADDI` | `1001 xxxi iiii iiii` | `rX <- rX + simm9`. |
| A | `BZ` / `BNZ` | `1010 nxxx oooo oooo` | Branch if `rX == 0` (`n` = 0) or `rX != 0` (`n` = 1). |
| B | `BF` | `1011 ccc- oooo oooo` | Branch on `ccc`: 000 `E`, 001 not `E`, 010 `A`, 011 not `A`, 100 `LATE`, 101 `OVF`, 110 `FE`, 111 not `FE`. |
| C | `DJNZ` | `1100 -xxx oooo oooo` | `rX <- rX - 1`. Branch if the result is not 0. |
| D | `JMP` | `1101 ---a aaaa aaaa` | `pc <- a` (9 bits, absolute). |
| E | `MEM` | `1110 sxxx yyyi iiii` | `s` = 0: `LDM rX, [rY + imm5]`. `s` = 1: `STM rX, [rY + imm5]`. The address wraps at 512. |
| F | `FIFO` | `1111 dxxx ---- ----` | `d` = 0: `PULL rX`. `d` = 1: `PUSH rX`. |

Branch targets for `BZ`, `BNZ`, `BF`, and `DJNZ`: `pc + 1 + sext(oooo oooo)`.

### Timed action fields

`PIN`, `PUT`, and `GET` share these fields:

| Field | Meaning |
|---|---|
| `@` | 1: timed, at `floor(T)`. 0: immediate. |
| `d` | 1: after the action, `T <- T + Pq`. 0: `T` is unchanged. |
| `qq` | The period register for `d`. Must be 00 when `d` = 0. |
| `m` | `PUT` and `GET` only. 0: LSB first. 1: MSB first. |

`PUT`, `m` = 0: drive `rX[0]`, then `rX <- rX >> 1`.
`PUT`, `m` = 1: drive `rX[15]`, then `rX <- rX << 1`.
`GET`, `m` = 0: `rX <- (rX >> 1) | (b << 15)`.
`GET`, `m` = 1: `rX <- (rX << 1) | b`.

A timed `GET` samples the bus level at cycle `floor(T)`. If `floor(T)` is
before `c - S`, the sample is the bus level at `c - S`, and the instruction
sets `LATE`.

### WAITE

`WAITE` ends at the first of these events. If two happen in the same cycle,
the first in this list wins.

1. Abort: the abort pin sees its edge. `A <- 1`, `E <- 0`. `CAP` and `rX` do
   not change.
2. Edge: the capture unit of pin `p` has `seen` = 1. `E <- 1`,
   `CAP <- timestamp`, `rX <- timestamp`. If `t` = 1, also
   `T <- timestamp` with fraction 0.
3. Timeout: `floor(T)` is not after `NOW`. `E <- 0`.

`WAITE` on a pin whose capture unit is not enabled, or not owned by the
engine, halts with `ILL`.

### SYS sub-operations

| `ssss` | Mnemonic | Operation |
|---|---|---|
| 0000 | `NOP` | No operation. |
| 0001 | `HALT` | Stall until every compare unit the engine owns has no pending action. Then halt. |
| 0010 | `TNOW` | `T <- NOW`, fraction 0. |
| 0011 | `TCAP` | `T <- CAP`, fraction 0. |
| 0100 | `CLRF` | Clear `E`, `A`, `LATE`, `OVF`, `M`. |
| 0101 | `ABRT rX` | Abort setting from `rX[6:0]`: bits 3..0 pin, 5..4 edge, 6 enable. |
| 0110 | `ARM rX` | Capture unit setting from `rX[6:0]`: bits 3..0 pin, 5..4 edge, 6 enable. |
| 0111 | `WAITT` | Stall until `floor(T)` is not after `NOW`. |
| 10qq | `LDP Pq, rX, rY` | `Pq` integer part `<- rX`, fraction `<- rY[7:0]`. |
| 11qq | `DLYP Pq` | `T <- T + Pq`. |

Edge field: 00 rise, 01 fall, 10 any, 11 halts with `ILL`.

`SYS` fields that a sub-operation does not use must be 0. `xxx` is used by
`ABRT`, `ARM`, and `LDP`. `yyy` is used by `LDP` only.

### FIFO

`PULL rX` stalls while the FIFO from the host is empty. Then it moves one
word into `rX`. Use `BF` with `FE` to test for an empty FIFO before `PULL`.

`PUSH rX` never stalls. If the FIFO to the host is full, the word is dropped
and `OVF <- 1`.

## Cycle counts

`c` is the cycle in which the instruction issues. "Next" is the cycle in
which the next instruction issues.

| Instruction | Next |
|---|---|
| `NOP`, `TNOW`, `TCAP`, `CLRF`, `ABRT`, `ARM`, `LDP`, `DLYP` | `c + 1` |
| `DLY`, `DLYR`, `LDI`, `ALU`, `ADDI` | `c + 1` |
| `BZ`, `BNZ`, `BF`, `DJNZ` | `c + 1` if not taken, `c + 2` if taken |
| `JMP`, `LDM`, `STM` | `c + 2` |
| `PUSH` | `c + 1` |
| `PULL` | `c + 1` if the FIFO has a word, else 1 cycle after a word arrives |
| `PIN`, `PUT` | `c' + 1`. `c'` is the load cycle: `c`, or the fire cycle of the pending action on that pin if it is after `c`. |
| `GET` (timed) | `max(c, floor(T) + S) + 1` |
| `GET` (immediate) | `c + 1`. The sample is the bus level at `c - S`. |
| `WAITE`, edge exit | `max(c, e + S) + 1`. `e` is the bus cycle of the edge. If `seen` was already 1 at `c`: `c + 1`. |
| `WAITE`, abort exit | `max(c, a + S) + 1`. `a` is the bus cycle of the abort edge. |
| `WAITE`, timeout exit | `max(c, floor(T)) + 1` |
| `WAITT` | `max(c, floor(T)) + 1` |
| `HALT` | No next instruction. |

## Proof targets

| Target | Statement | Tool |
|---|---|---|
| G1 | An accepted program never sets `LATE`. | Lean, ISA level |
| G2 | Each library firmware's pin trace meets its protocol specification for all inputs. | Lean |
| G3 | The RTL implements each instruction. | sby per instruction, later netlist to Lean |
| G4 | The timing of one engine does not depend on the other engine or on the host. | sby |

Not proved: pad electrical timing.

`WAITE` has three exits. A proof about a firmware that uses `WAITE` covers
every exit.

Target firmware with a G2 proof: UART TX, UART RX, SPI controller, SPI
target, I2C controller, I2C target with clock stretching, auto-baud.

## Status of each instruction

Every instruction needs an encoding, a cycle count, and a cocotb test
(`AGENTS.md`, "ISA contract"). This document gives the encoding and the cycle
count. No v0 RTL exists yet, so no instruction has a cocotb test. Each test
lands with the RTL for its instruction.

## Not in v0

| Item | Status |
|---|---|
| Event queue for output timing | Not used. Each output pin has a compare unit. |
| Multi-pin set instruction | Not needed. Two compare units with the same fire cycle change together. |
| Autopull FIFO | Not in v0. UART, SPI, and I2C work without it. |
| CRC unit | Not in v0. CAN and 1-Wire CRCs run in firmware. |
| Program-load port protocol | Added with the program loader RTL. |
