# ISA v0 proposal (program side)

A proposal for discussion. It is not the contract: `docs/isa.md` is the
contract, and both people approve it. This page records what the UART, SPI,
and I2C firmware needed, and what the model measured.

The model is `protoemu/v0.py`. The firmware is in `programs/v0/`. The tests
in `tests/test_v0.py` run each program against a peer device written from the
protocol standard (`protoemu/peers.py`) and check the pin trace against the
standard (`protoemu/spec.py`).

## Base: the Probe A timeline

v0 keeps the Probe A rules from `lean/ProtoEmu/Probe/UartTx.lean`. T is the
timeline cursor. A timed action acts at `max(now, floor(T))`. If
`floor(T) < now`, the action is late. The checker reports the slack of every
timed action.

## Additions, and the firmware that needs them

| Addition | Why | Used by |
|---|---|---|
| T has 8 fraction bits | 115200 baud is 434.03 cycles. Whole cycles drift 1/3 cycle per bit at 9600 baud (26 cycles over 8 bytes). The fraction keeps the error under 1 cycle plus 1/512 cycle per bit. | UART TX, UART RX |
| Delay field on timed actions: `set OUT0, 1, +BIT` | An action plus a separate `dly` is 2 cycles. Two pin changes that must be 1 cycle apart need the fused form. It also makes loops shorter. | all |
| `wait pin, level`: stall, then T := cycle of the edge | Timing relative to an input edge. UART RX syncs on the start bit. I2C follows a target that stretches SCL. | UART RX, I2C |
| Open-drain pin mode (`cfg pin, OD`) | I2C needs wired-AND lines. `set pin, 1` releases the line. | I2C, 1-Wire |
| `cfg pin, PP0`: push-pull that starts low | `cfg` starts a pin at 1. WS2812 idles low, and a high start loses the first bit. | WS2812 |
| `get` (LSB first) and `geth` (MSB first) timed samples | UART is LSB first. SPI and I2C are MSB first. | UART RX, SPI, I2C |
| `put` (LSB first) and `puth` (MSB first) timed outputs | The same reason. | UART TX, SPI, I2C |
| Host FIFO: `pull`, `push` | The host streams bytes in and out while the program runs. `pull` returns 0x100 when the FIFO is empty. | all |
| Branches `bz`, `bnz`, `jmp` | I2C NACK, UART framing error, end of data. | I2C, UART RX |

An input reaches the core IN_LAT = 3 cycles after it is on the bus: 2
synchronizer stages, plus 1 cycle because the pins come from a register. The
model hides this in the timestamps (`get` at T reads the level at cycle T,
and `wait` reports the bus cycle of the edge) and charges it as stall cycles.
The RTL in `src/v0core.v` showed the third cycle. The first version of the
model charged only 2.

## Instruction costs

| Instruction | Cycles |
|---|---|
| `ldi mov addi andi xori shli shri dly sync cfg pull push` | 1 |
| `djnz bz bnz` | 1, or 2 if taken |
| `jmp` | 2 |
| `set put puth` | 1 after the action cycle |
| `get geth` | 1 + IN_LAT after the sample cycle |
| `wait` | until the edge, + IN_LAT + 1 |
| `waitt` | until T, + 1 |

## Measured results

All values come from tests that assert exact numbers.

| Protocol | Result |
|---|---|
| UART TX | 9600 to 3 Mbaud pass. Minimum bit period is 8 cycles (6.25 Mbaud at 50 MHz). The limit is the 8-cycle gap from stop bit to the next start bit. |
| UART RX | Decodes with the sender 2% fast or 2% slow. Reports a framing error. |
| SPI controller | Modes 0 to 3 pass against an independent target. Minimum half period is 15 cycles for more than one byte (1.67 MHz SCK). Inside a byte the loop needs only 7 (3.57 MHz). The byte loop overhead (pull, test, push) sets the limit. |
| I2C controller write | 100 kHz and 400 kHz pass every timing check in the spec checker: tLOW, tHIGH, tSU;DAT, tHD;STA, tSU;STO, and no SDA change while SCL is high. NACK detection works. Clock stretching of 100 to 3000 cycles works. |

### Protocols the v0 set was not designed for

These programs use only the instructions above. The only addition is the
`PP0` mode.

| Protocol | Result |
|---|---|
| WS2812 LED chain | High times are exactly 20 and 40 cycles (0.4 and 0.8 us). The 62.5-cycle bit alternates 62 and 63 cycles, so it does not drift. A decoder from the data sheet reads the colors back. No branch on the data: the pin takes the data bit at 0.4 us. |
| 1-Wire READ ROM | Reset, presence detect, command 0x33, and 8 ROM bytes from a device model built from the DS18B20 data sheet. The CRC-8 of the ROM checks. No device gives NODEV. Write slots use the same trick as WS2812: the pin takes the data bit 6 us into the slot. |

The spec checker found one firmware bug: a 50% SCL duty cycle gives
tLOW = 1.25 us at 400 kHz, below the 1.3 us minimum. The firmware now uses
55% low.

## Open questions for the chip side

1. **Byte overhead.** SPI loses 8 cycles per byte to `pull`, the empty test,
   and `push`. A FIFO that refills the shift register on its own (like RP2040
   PIO autopull) would raise SPI to about 4 MHz. Is it worth the area?
2. **Two pins at once.** SPI changes SCK and MOSI 1 cycle apart. A multi-pin
   `set` would make the change atomic. JTAG and SWD need the same.
3. **`wait` must start before the edge.** If the edge comes before `wait`
   issues, T lands late. A capture unit that latches every edge time would
   remove this limit.
4. **Width of T and of the fraction.** The model uses unbounded T. The RTL
   timer in the probe is 16 bits, so every deadline must be less than 2^15
   cycles ahead. 8 fraction bits drift 1/512 cycle per bit. 16 would be
   near zero.
5. **Clock.** 10 Mbit Ethernet needs edges every 50 ns: 2.5 cycles at 50 MHz,
   3 cycles at 60 MHz. Low-speed USB is 33.3 cycles per bit at 50 MHz and 40
   at 60 MHz.
6. **CRC.** USB, CAN, 1-Wire, and Ethernet each use a CRC. A unit with a
   programmable polynomial would keep the chip protocol-neutral.

## Static deadline proof

`protoemu/v0check.py` proves without running the program that every timed
action is on time on every path and for any input timing. It tracks the
interval of `now - T` at each program point. It follows both sides of each
branch and iterates loops to a fixed point. `wait` sets the interval to one
exact value, because T moves to the edge. So clock stretching or a fast or
slow UART sender cannot break a proof.

```sh
python -m protoemu.v0check programs/v0/spi_ctrl.s -D HALF=13
```

The tests check two properties against the simulator:

- Sound: the static worst slack is never above a simulated slack.
- Tight: for whole-cycle programs the two are equal. SPI half period 15
  passes with slack 0, and 14 is late by 1, in both.

All six programs pass the proof. The I2C proof covers the NACK path, which
a normal run does not take.

Assumptions: the edge that `wait` waits for comes after `wait` issues, and
the proof covers timing, not whether a `wait` ends.
