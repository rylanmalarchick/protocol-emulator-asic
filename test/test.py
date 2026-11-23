# SPDX-License-Identifier: Apache-2.0
"""cocotb tests for the protocol emulator top (tt_um_rylanmalarchick_protoemu).

Every test talks to the chip only through its pins, so the same tests run on
the RTL and on the gate-level netlist. The host loads the program and the
host-in bytes over the load port (an SPI target), sets RUN, and reads the
results back over the load port.

The protocol tests run each program on the chip and on the Python model
(protoemu.v0.Sim) with the same peer devices, and check every pin in every
cycle. The chip pins are the model bus 1 cycle later, because the pins come
from registers. In the RTL run, the tests also check that each instruction
issues in the same cycle with the same T as in the model.
"""

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, with_timeout
from cocotbext.uart import UartSink

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sw"))

from protoemu import host, peers, spec, v0, v0asm, v0enc  # noqa: E402

PROGS = ROOT / "sw" / "programs" / "v0"
CLK = 50_000_000
GL = os.environ.get("GATES") == "yes"
HALF = 4  # SCK half period in clocks: SCK = clk/8, the fastest the port takes
RUN = 1 << 3
CYCLE0 = 3  # falling edges from setting RUN to the falling edge of core cycle 0


def asm(name, **defines):
    return v0asm.assemble((PROGS / name).read_text(), defines)


def bits(v, n=8):
    return [(v >> k) & 1 for k in range(n)]


class Chip:
    """Drives the chip pins. ui_in bits 0-2 are the load port, bit 3 is RUN,
    bits 4-7 are IN0-IN3."""

    def __init__(self, dut):
        self.dut = dut
        self.ui = 0b001  # CS high, SCK low, MOSI low

    def put_ui(self):
        self.dut.ui_in.value = self.ui

    async def reset(self):
        dut = self.dut
        cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
        dut.ena.value = 1
        self.ui = 0b001 | (0xF << 4)  # IN pins idle high
        self.put_ui()
        dut.uio_in.value = 0xFF
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 5)

    async def xfer(self, data: bytes) -> bytes:
        """One SPI frame, mode 0. The host samples MISO at each SCK rise."""
        dut = self.dut
        reply = []
        self.ui &= ~0b111  # CS low, SCK low
        self.put_ui()
        await ClockCycles(dut.clk, HALF)
        for byte in data:
            got = 0
            for k in range(7, -1, -1):
                self.ui = (self.ui & ~0b100) | (((byte >> k) & 1) << 2)
                self.put_ui()
                await ClockCycles(dut.clk, HALF)
                got = got << 1 | (int(dut.uo_out.value) & 1)
                self.ui |= 0b010
                self.put_ui()
                await ClockCycles(dut.clk, HALF)
                self.ui &= ~0b010
                self.put_ui()
            reply.append(got)
        await ClockCycles(dut.clk, HALF)
        self.ui |= 0b001
        self.put_ui()
        await ClockCycles(dut.clk, 2 * HALF)
        return bytes(reply)

    async def status(self) -> int:
        return (await self.xfer(bytes([host.CMD_NOP])))[0]

    async def load(self, prog, host_in=()):
        words = v0enc.encode(prog)
        await self.xfer(host.prog_write(words))
        back = host.parse_prog_read(await self.xfer(host.prog_read(len(words))))
        assert back == words, "program read-back differs"
        if host_in:
            await self.xfer(host.host_write(bytes(host_in)))

    async def read_host(self, n: int) -> list[int]:
        return host.parse_host_read(await self.xfer(host.host_read(n)))

    def set_run(self, on: bool):
        self.ui = (self.ui | RUN) if on else (self.ui & ~RUN)
        self.put_ui()


def resolve(dut, peer_list):
    """The bus level of the 20 pins, from the chip outputs and the peers."""
    uo, oe, uout = int(dut.uo_out.value), int(dut.uio_oe.value), int(dut.uio_out.value)
    drv = [p.drives() for p in peer_list]
    levels = []
    for pin in range(20):
        low = any(d.get(pin, 1) == 0 for d in drv)
        if pin < 6:
            levels.append((uo >> (2 + pin)) & 1)
        elif 8 <= pin < 16 and (oe >> (pin - 8)) & 1:
            levels.append((uout >> (pin - 8)) & 1)
        else:
            levels.append(0 if low else 1)
    return levels


async def run_chip(chip, peer_list, ncycles):
    """Set RUN and run ncycles core cycles. Returns the bus and the issues."""
    dut = chip.dut
    await FallingEdge(dut.clk)
    chip.set_run(True)
    for _ in range(CYCLE0):
        await FallingEdge(dut.clk)
    core = None if GL else dut.user_project.core
    bus, issues, prev = [], [], None
    for t in range(ncycles):  # at the falling edge of core cycle t
        if core is not None:
            assert int(core.now.value) == t
            cur = (int(core.state.value), int(core.pc.value))
            if cur[0] == 0 and cur != prev:
                issues.append((t, cur[1], int(core.T.value)))
            prev = cur
        levels = resolve(dut, peer_list)
        dut.uio_in.value = sum(levels[8 + k] << k for k in range(8))
        chip.ui = (chip.ui & 0x0F) | sum(levels[16 + k] << (4 + k) for k in range(4))
        chip.put_ui()
        for p in peer_list:
            p.observe(t, levels)
        bus.append(levels)
        await FallingEdge(dut.clk)
    return bus, issues


async def compare(dut, prog, make_peers, host_in=(), max_cycles=60_000, tail=10):
    """make_peers(shift) builds fresh peers. shift is 1 for the chip run:
    peers with absolute times (a UART sender) start 1 cycle later there."""
    sim = v0.Sim(prog, make_peers(0), host_in)
    sim.run(max_cycles, tail=tail)
    chip = Chip(dut)
    await chip.reset()
    await chip.load(prog, host_in)
    st = await chip.status()
    assert st & host.ST_ID_MASK == host.ST_ID
    assert not st & (host.ST_RUN | host.ST_HALTED | host.ST_OVERFLOW)
    chip_peers = make_peers(1)
    bus, issues = await run_chip(chip, chip_peers, len(sim.bus) + 1)

    if not GL:
        assert len(issues) == len(sim.core.issues)
        for k, (m, r) in enumerate(zip(sim.core.issues, issues)):
            m = (m[0], m[1], m[2] % (1 << 32))
            assert m == r, f"issue {k}: model (cycle, pc, T) {m}, chip {r}"
        assert int(dut.user_project.core.halted.value)
    for t, model_levels in enumerate(sim.bus):
        assert bus[t + 1] == model_levels, (
            f"cycle {t}: pins differ: "
            f"{[p for p in range(20) if bus[t + 1][p] != model_levels[p]]}")

    st = await chip.status()
    assert st & host.ST_RUN and st & host.ST_HALTED
    assert bool(st & host.ST_LATE) == sim.core.late
    assert not st & host.ST_OVERFLOW
    out = await chip.read_host(len(sim.core.host_out) + 1)
    assert out == sim.core.host_out
    return sim, chip_peers


# ---- load port ----

@cocotb.test()
async def test_load_port(dut):
    """Program write and read-back, host FIFO round trip, status, CLEAR."""
    chip = Chip(dut)
    await chip.reset()
    st = await chip.status()
    assert st == host.ST_ID  # idle: no flags

    words = [(0x2A5A5A5A5A + 977 * k) & ((1 << 38) - 1) for k in range(64)]
    await chip.xfer(host.prog_write(words))
    back = host.parse_prog_read(await chip.xfer(host.prog_read(64)))
    assert back == words
    back = host.parse_prog_read(await chip.xfer(host.prog_read(3, addr=61)))
    assert back == words[61:64]

    # The host-in FIFO holds 16 bytes. The 17th sets the overflow flag.
    await chip.xfer(host.host_write(bytes(range(16))))
    assert await chip.status() == host.ST_ID | host.ST_HIN_FULL
    await chip.xfer(host.host_write(b"\x99"))
    assert await chip.status() == host.ST_ID | host.ST_HIN_FULL | host.ST_OVERFLOW
    await chip.xfer(bytes([host.CMD_CLEAR]))
    assert await chip.status() == host.ST_ID

    # An empty host-out FIFO reads as entries with valid = 0.
    reply = await chip.xfer(host.host_read(2))
    assert reply[1:] == bytes(6)


@cocotb.test()
async def test_no_write_while_running(dut):
    """PROG_WRITE does nothing while RUN is high."""
    chip = Chip(dut)
    await chip.reset()
    prog = asm("uart_tx.s", BAUD=1_000_000)
    words = v0enc.encode(prog)
    await chip.xfer(host.prog_write(words))
    chip.set_run(True)
    await ClockCycles(dut.clk, 10)
    await chip.xfer(host.prog_write([0] * len(words)))
    chip.set_run(False)
    await ClockCycles(dut.clk, 10)
    back = host.parse_prog_read(await chip.xfer(host.prog_read(len(words))))
    assert back == words


@cocotb.test()
async def test_pins_idle_in_reset(dut):
    """With RUN low, every IO pin is an input and every OUT pin is high."""
    chip = Chip(dut)
    await chip.reset()
    for _ in range(20):
        await FallingEdge(dut.clk)
        assert int(dut.uio_oe.value) == 0
        assert int(dut.uo_out.value) >> 2 == 0x3F


# ---- protocols against the model, every pin, every cycle ----

@cocotb.test()
async def test_uart_tx(dut):
    await compare(dut, asm("uart_tx.s", BAUD=1_000_000), lambda s: [],
                  host_in=[0x55, 0xA3, 0x00, 0xFF])


@cocotb.test()
async def test_uart_tx_late(dut):
    # BIT = 7 is late in the model. The chip must be late in the same cycles.
    sim, _ = await compare(dut, asm("uart_tx.s", BIT=7), lambda s: [],
                           host_in=[0x55, 0x0F])
    assert sim.core.late


def shifted_source(pin, data, bit, start, gap, shift):
    """A UART sender whose edges are exactly `shift` cycles later. Building it
    with start + shift is not the same: Python rounds .5 to even."""
    src = peers.UartSource(pin, data, bit=bit, start=start, gap=gap)
    src.edges = [(t + shift, lvl) for t, lvl in src.edges]
    return src


@cocotb.test()
async def test_uart_rx(dut):
    bit = CLK / 1_000_000 * 1.02  # the sender is 2% slow
    data = [0x55, 0xC3, 0x00]
    sim, _ = await compare(dut, asm("uart_rx.s", BAUD=1_000_000, COUNT=3),
                           lambda s: [shifted_source("IN0", data, bit, 40, 0.5, s)])
    assert sim.core.host_out == data


@cocotb.test()
async def test_spi_mode0(dut):
    _, (tgt,) = await compare(
        dut, asm("spi_ctrl.s", CPOL=0, CPHA=0),
        lambda s: [peers.SpiTarget(0, "OUT1", "OUT2", "OUT3", "IN1", [0x3C, 0xEF])],
        host_in=[0x9F, 0xA5])
    assert tgt.rx == [0x9F, 0xA5]


@cocotb.test()
async def test_spi_mode3(dut):
    _, (tgt,) = await compare(
        dut, asm("spi_ctrl.s", CPOL=1, CPHA=1),
        lambda s: [peers.SpiTarget(3, "OUT1", "OUT2", "OUT3", "IN1", [0x81, 0x7E])],
        host_in=[0x12, 0x34])
    assert tgt.rx == [0x12, 0x34]


@cocotb.test()
async def test_i2c_stretch(dut):
    sim, (tgt,) = await compare(
        dut, asm("i2c_write.s", FSCL=400_000),
        lambda s: [peers.I2cTarget(0x50, "IO0", "IO1", stretch=200)],
        host_in=[0xA0, 0x12, 0x34])
    assert tgt.received == [0x12, 0x34]
    assert spec.check_i2c(sim.levels("IO0"), sim.levels("IO1"), CLK, "fm")[1] == []


@cocotb.test()
async def test_i2c_nack(dut):
    sim, _ = await compare(dut, asm("i2c_write.s", FSCL=400_000),
                           lambda s: [peers.I2cTarget(0x50, "IO0", "IO1")],
                           host_in=[0xA2, 0x12])
    assert sim.core.host_out == [256]


@cocotb.test()
async def test_ws2812(dut):
    sim, _ = await compare(dut, asm("ws2812.s"), lambda s: [],
                           host_in=[0xFF, 0x00, 0x81, 0x12, 0x34, 0x56])
    frames, bad = spec.decode_ws2812(sim.levels("OUT4"), CLK)
    assert bad == [] and frames == [[0xFF0081, 0x123456]]


@cocotb.test()
async def test_onewire(dut):
    # 10x faster slots (US = 5 cycles) keep the run short. The device model
    # uses the same scale.
    rom = [0x28, 0xFF, 0x4C, 0x60, 0x91, 0x16, 0x05, 0x8A]
    sim, _ = await compare(dut, asm("onewire_read_rom.s", US=5),
                           lambda s: [peers.OneWireDevice("IO2", rom, clk_hz=5e6)])
    assert sim.core.host_out == rom


# ---- an independent bus model ----

@cocotb.test()
async def test_uart_tx_cocotbext(dut):
    """UART TX at 115200 baud, decoded by cocotbext-uart, not by our model."""
    chip = Chip(dut)
    await chip.reset()
    data = b"Jane St\n"
    await chip.load(asm("uart_tx.s", BAUD=115200), data)
    sink = UartSink(dut.out0, baud=115200, bits=8)
    chip.set_run(True)
    got = bytearray()
    for _ in range(len(data)):  # read() takes only the bytes already queued
        got += await with_timeout(sink.read(1), 200, "us")
    assert bytes(got) == data
    await ClockCycles(dut.clk, 1000)  # the last stop bit, then halt
    st = await chip.status()
    assert st & host.ST_HALTED and not st & host.ST_LATE
