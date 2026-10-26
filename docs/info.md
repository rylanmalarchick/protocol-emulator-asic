<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

**Status:** this page describes the planned design and pin plan v0. The RTL in
`src/` is still the Tiny Tapeout template. The pin plan can change until the
RTL lands.

## How it works

The chip is a programmable protocol emulator. A small engine runs a program
that drives and samples the protocol pins. UART, SPI, and I2C run as programs,
not as fixed hardware, so a new program adds a new protocol after fabrication.

Time is an operand in the instruction set. An output instruction names the
clock cycle at which a pin edge happens. A capture instruction records the
clock cycle at which an input edge arrives. A branch can test a captured value,
for example an I2C ACK bit, and pick the next part of the program.

An off-chip assembler turns a protocol description into a program. Before it
emits the program, it checks every timing requirement of the protocol, such as
setup time, hold time, and bit period, against the cycle counts of the
instructions.

Pin groups:

| Group | Pins | Use |
|---|---|---|
| Program load | `LOAD_CS_N`, `LOAD_SCK`, `LOAD_MOSI`, `LOAD_MISO` | SPI target port. The host writes the program and reads status. |
| Control | `RUN`, `STATUS` | `RUN` high starts the engine. `STATUS` reports the engine state. |
| Inputs | `IN0` to `IN3` | Sampled and timestamped protocol inputs, for example UART RX or SPI MISO. |
| Outputs | `OUT0` to `OUT5` | Driven protocol outputs, for example UART TX, SPI SCK, MOSI, and CS. |
| Bidirectional | `IO0` to `IO7` | Pins with program-controlled direction, for example I2C SDA and SCL as open-drain lines. |

The design runs from a 50 MHz clock.

## How to test

1. Hold `RUN` low.
2. Write a program into the chip through the program-load SPI port. The RP2040
   on the Tiny Tapeout demo board can act as the SPI host.
3. Connect the protocol pins to the target device, for example a USB-UART
   adapter on `OUT0` and `IN0`.
4. Set `RUN` high. The engine runs the program.
5. Check the traffic on the target device or with a logic analyzer.

The host tools, the program format, and example programs for UART, SPI, and
I2C are not written yet. This section changes when they land.

## External hardware

None is required. For protocol tests, use any of these:

- A USB-UART adapter for UART.
- An SPI flash or SPI sensor PMOD for SPI.
- An I2C sensor PMOD, with pull-up resistors on `IO0` and `IO1`, for I2C.
