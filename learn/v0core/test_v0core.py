"""cocotb: run v0 programs on the RTL core and compare with the Python model.

For each program the test runs the model (protoemu.v0.Sim) and the RTL with
the same peer devices. It then checks, for every cycle t and every pin, that
the RTL pin level at cycle t + 1 equals the model bus level at cycle t. The
1-cycle shift is the output register. It also checks that each instruction
issues in the same cycle with the same T in both, and the host output, the late flag, and
the halt cycle.
"""

from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

from protoemu import peers, v0, v0asm, v0enc

PROGS = Path(__file__).resolve().parents[2] / "sw" / "programs" / "v0"
CLK = 50_000_000


def bits(v, n=20):
    return [(v >> k) & 1 for k in range(n)]


async def run_rtl(dut, prog, peer_list, host_in, max_cycles, tail=10):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.rst_n.value = 0
    dut.prog_we.value = 0
    dut.pin_in.value = (1 << 20) - 1
    dut.hin_valid.value = 0
    dut.hin_data.value = 0
    await ClockCycles(dut.clk, 2)
    for addr, word in enumerate(v0enc.encode(prog)):
        dut.prog_we.value, dut.prog_waddr.value, dut.prog_wdata.value = 1, addr, word
        await RisingEdge(dut.clk)
    dut.prog_we.value = 0
    await RisingEdge(dut.clk)  # this edge applies the reset: cycle 0 starts
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    q, out, bus, issues = list(host_in), [], [], []
    halted_at = None
    prev = None  # (state, pc) in the cycle before
    for t in range(max_cycles):  # at the falling edge of cycle t
        assert int(dut.now.value) == t
        # An issue is the first RUN cycle at a pc: after a pc change, or after
        # a cycle in another state (a branch bubble, a sample, a wait).
        cur = (int(dut.state.value), int(dut.pc.value))
        if cur[0] == 0 and (prev is None or prev != cur):
            issues.append((t, cur[1], int(dut.T.value)))
        prev = cur
        if dut.hin_pop.value:
            q.pop(0)
        if dut.hout_valid.value:
            out.append(int(dut.hout_data.value))
        dut.hin_valid.value = 1 if q else 0
        dut.hin_data.value = q[0] if q else 0
        pp, od, po = (bits(int(s.value)) for s in (dut.pin_pp, dut.pin_od, dut.pin_out))
        drv = [p.drives() for p in peer_list]
        levels = []
        for pin in range(20):
            low = any(d.get(pin, 1) == 0 for d in drv)
            if pp[pin]:
                levels.append(po[pin])
            elif od[pin]:
                levels.append(0 if po[pin] == 0 or low else 1)
            else:
                levels.append(0 if low else 1)
        dut.pin_in.value = sum(b << k for k, b in enumerate(levels))
        for p in peer_list:
            p.observe(t, levels)
        bus.append(levels)
        if halted_at is None and dut.halted.value:
            halted_at = t
        if halted_at is not None and t >= halted_at + tail:
            return bus, out, bool(dut.late.value), halted_at, issues
        await FallingEdge(dut.clk)
    raise AssertionError(f"no halt within {max_cycles} cycles")


async def compare(dut, prog, make_peers, host_in=(), max_cycles=60_000):
    """make_peers(shift) builds fresh peers. shift is 1 for the RTL run:
    peers with absolute times (a UART sender) start 1 cycle later there."""
    sim = v0.Sim(prog, make_peers(0), host_in)
    sim.run(max_cycles, tail=10)
    rtl_bus, rtl_out, rtl_late, rtl_halt, rtl_issues = await run_rtl(
        dut, prog, make_peers(1), host_in, max_cycles + 20)
    # The same instruction issues in the same cycle. This catches timing
    # differences that a stall hides from the pins.
    # T is compared modulo 2^32, the width of the RTL register.
    for k, (m, r) in enumerate(zip(sim.core.issues, rtl_issues)):
        m = (m[0], m[1], m[2] % (1 << 32))
        assert m == r, f"issue {k}: model (cycle, pc, T) {m}, RTL {r}"
    assert len(rtl_issues) == len(sim.core.issues)
    for t, model_levels in enumerate(sim.bus):
        assert rtl_bus[t + 1] == model_levels, (
            f"cycle {t}: pins differ: "
            f"{[p for p in range(20) if rtl_bus[t + 1][p] != model_levels[p]]}")
    assert rtl_out == sim.core.host_out
    assert rtl_late == sim.core.late
    assert rtl_halt == sim.core.halted_at + 1  # halted is a register
    return sim


def asm(name, **defines):
    return v0asm.assemble((PROGS / name).read_text(), defines)


@cocotb.test()
async def test_uart_tx(dut):
    await compare(dut, asm("uart_tx.s", BAUD=1_000_000), lambda s: [],
                  host_in=[0x55, 0xA3, 0x00, 0xFF])


@cocotb.test()
async def test_uart_tx_late(dut):
    # BIT = 7 is late in the model. The RTL must be late in the same cycles.
    sim = await compare(dut, asm("uart_tx.s", BIT=7), lambda s: [], host_in=[0x55, 0x0F])
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
    sim = await compare(dut, asm("uart_rx.s", BAUD=1_000_000, COUNT=3),
                        lambda s: [shifted_source("IN0", data, bit, 40, 0.5, s)])
    assert sim.core.host_out == data


@cocotb.test()
async def test_spi_mode0(dut):
    await compare(dut, asm("spi_ctrl.s", CPOL=0, CPHA=0),
                  lambda s: [peers.SpiTarget(0, "OUT1", "OUT2", "OUT3", "IN1", [0x3C, 0xEF])],
                  host_in=[0x9F, 0xA5])


@cocotb.test()
async def test_spi_mode3(dut):
    await compare(dut, asm("spi_ctrl.s", CPOL=1, CPHA=1),
                  lambda s: [peers.SpiTarget(3, "OUT1", "OUT2", "OUT3", "IN1", [0x81, 0x7E])],
                  host_in=[0x12, 0x34])


@cocotb.test()
async def test_i2c_stretch(dut):
    await compare(dut, asm("i2c_write.s", FSCL=400_000),
                  lambda s: [peers.I2cTarget(0x50, "IO0", "IO1", stretch=200)],
                  host_in=[0xA0, 0x12, 0x34])


@cocotb.test()
async def test_i2c_nack(dut):
    sim = await compare(dut, asm("i2c_write.s", FSCL=400_000),
                        lambda s: [peers.I2cTarget(0x50, "IO0", "IO1")],
                        host_in=[0xA2, 0x12])
    assert sim.core.host_out == [256]


@cocotb.test()
async def test_ws2812(dut):
    await compare(dut, asm("ws2812.s", RESET=500), lambda s: [],
                  host_in=[0xFF, 0x00, 0x81, 0x12, 0x34, 0x56])


@cocotb.test()
async def test_onewire(dut):
    # 10x faster slots (US = 5 cycles) keep the run short. The device model
    # uses the same scale.
    rom = [0x28, 0xFF, 0x4C, 0x60, 0x91, 0x16, 0x05, 0x8A]
    sim = await compare(dut, asm("onewire_read_rom.s", US=5),
                        lambda s: [peers.OneWireDevice("IO2", rom, clk_hz=5e6)],
                        max_cycles=60_000)
    assert sim.core.host_out == rom
