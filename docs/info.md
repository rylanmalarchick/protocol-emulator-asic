<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

The chip is a programmable protocol emulator. A small core runs a program
that drives and samples the protocol pins. UART, SPI, I2C, WS2812, and
1-Wire run as programs, not as fixed hardware. A new program adds a new
protocol after fabrication.

Time is an operand in the instruction set. The core keeps a timeline cursor
T, in cycles with 8 fraction bits. An output instruction such as
`set OUT0, 1, +BIT` changes the pin in cycle floor(T), then moves T on by
BIT. `get` samples a pin in cycle floor(T). `wait` stops until an input edge
and moves T to the cycle of that edge, so later actions are relative to the
edge. If the core reaches an action after its cycle, the action is late, and
the core sets the `late` flag. The off-chip tool `sw/protoemu/v0check.py`
proves that no action of a program can be late, before the program runs.

The ISA is in `docs/isa.md`: 8 registers of 16 bits, 24 instructions, and
64 program words of 38 bits. Two FIFOs connect the program to the host: the
program reads host bytes with `pull` and sends results with `push`.

Blocks:

| Block | File | Function |
|---|---|---|
| Core | `src/v0core.v` | Runs the program. One instruction per cycle, unless it waits for T. |
| Load port | `src/v0_loader.v` | SPI target. Writes and reads the program. Moves bytes through the host FIFOs. |
| Host FIFOs | `src/v0_fifo.v` | Host to core: 16 bytes. Core to host: 16 entries of 16 bits. |
| Program memory | `src/v0_mem.v` | 64 x 38 bits, synchronous read. |

Pins:

| Pin | Name | Function |
|---|---|---|
| `ui[0]` | `LOAD_CS_N` | load port chip select, active low |
| `ui[1]` | `LOAD_SCK` | load port clock. At most clk/8 (6.25 MHz at 50 MHz). |
| `ui[2]` | `LOAD_MOSI` | load port data in |
| `ui[3]` | `RUN` | low: the core is in reset and the host can load a program. High: the program runs from address 0. |
| `ui[7:4]` | `IN3`-`IN0` | protocol inputs (pins 16-19 in the ISA) |
| `uo[0]` | `LOAD_MISO` | load port data out |
| `uo[1]` | `STATUS` | high when the host-out FIFO has data |
| `uo[7:2]` | `OUT5`-`OUT0` | protocol outputs (pins 0-5 in the ISA). High when not driven. |
| `uio[7:0]` | `IO7`-`IO0` | protocol pins with program-controlled direction (pins 8-15 in the ISA). Push-pull or open drain. |

With `RUN` low, every IO pin is an input and every OUT pin is high.

### Load port

The load port is an SPI target, mode 0 (CPOL = 0, CPHA = 0), MSB first. A
frame starts when `LOAD_CS_N` goes low and ends when it goes high. In every
frame, the first byte that the chip sends is the status byte. The first
byte that the host sends is the command.

| Command | Bytes after the command | Function |
|---|---|---|
| `0x00` NOP | none | read the status byte |
| `0x01` PROG_WRITE | address, then 5 bytes per word | write program words from the address. `RUN` must be low. |
| `0x02` HOST_WRITE | data bytes | put bytes in the host-in FIFO |
| `0x03` HOST_READ | 3 bytes per entry | the chip sends valid flag, high byte, low byte per entry of the host-out FIFO. Valid 0 means the FIFO was empty. |
| `0x04` PROG_READ | address, then 5 bytes per word | read program words from the address. `RUN` must be low. |
| `0x05` CLEAR | none | empty both FIFOs and clear the overflow flag |

Status byte:

| Bit | Meaning |
|---|---|
| 7:6 | always `10` |
| 5 | overflow: a FIFO was full and dropped data |
| 4 | the host-in FIFO is full |
| 3 | the host-out FIFO has data |
| 2 | late: an action happened after its cycle |
| 1 | halted |
| 0 | `RUN` is high |

`sw/protoemu/host.py` builds these frames.

## How to test

1. Hold `RUN` low.
2. Assemble a program and send it with PROG_WRITE. Example with the Python
   tools in `sw/`:

   ```python
   from protoemu import host, v0asm, v0enc
   prog = v0asm.assemble(open("programs/v0/uart_tx.s").read(), {"BAUD": 115200})
   frame = host.prog_write(v0enc.encode(prog))   # send this as one SPI frame
   ```

3. Read the program back with PROG_READ and compare.
4. Send the input data with HOST_WRITE. For `uart_tx.s`, these are the bytes
   to send.
5. Set `RUN` high. The program runs.
6. Read results with HOST_READ, and the halted and late flags with NOP.

The RP2040 on the Tiny Tapeout demo board can be the SPI host. Use a bit-bang
SPI on the pins of `ui[2:0]` and `uo[0]`.

Example programs in `sw/programs/v0`:

| Program | Pins | Function |
|---|---|---|
| `uart_tx.s` | `OUT0` TX | sends the host bytes, 8N1. Set `BAUD`. |
| `uart_rx.s` | `IN0` RX | receives `COUNT` bytes and sends them to the host. 512 marks a framing error. |
| `spi_ctrl.s` | `OUT1` SCK, `OUT2` MOSI, `OUT3` CS, `IN1` MISO | SPI controller, modes 0-3. Sends the host bytes, returns the bytes read. |
| `i2c_write.s` | `IO0` SDA, `IO1` SCL | I2C write: address byte, then data, from the host bytes. 256 marks a NACK. Needs pull-ups. |
| `ws2812.s` | `OUT4` | WS2812 LED chain, GRB bytes from the host |
| `onewire_read_rom.s` | `IO2` | 1-Wire READ ROM. Returns the 8 ROM bytes. Needs a pull-up. |
| `alu_selftest.s` | `OUT5` | runs the ALU ops and pushes known results |

## External hardware

None is required. For protocol tests, use any of these:

- A USB-UART adapter for UART.
- An SPI flash or SPI sensor PMOD for SPI.
- An I2C sensor PMOD, with pull-up resistors on `IO0` and `IO1`, for I2C.
- A WS2812 LED strip on `OUT4` (with a level shifter to 5 V if the strip needs it).
- A DS18B20 or other 1-Wire device on `IO2`, with a 4.7 kOhm pull-up.
