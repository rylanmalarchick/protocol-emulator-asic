"""Tests for the ISA v0 proposal: machine rules, assembler, and the firmware.

The firmware tests use peers from peers.py and checks from spec.py. Both are
written from the protocol standards, not from the firmware.
"""

from pathlib import Path

import pytest

from protoemu import peers, spec, v0, v0asm

PROGS = Path(__file__).parent.parent / "programs" / "v0"
CLK = 50_000_000


def prog(name, **defines):
    return v0asm.assemble((PROGS / name).read_text(), defines)


def run(src_or_prog, peer_list=(), host_in=(), max_cycles=200_000, tail=10):
    p = v0asm.assemble(src_or_prog) if isinstance(src_or_prog, str) else src_or_prog
    sim = v0.Sim(p, peer_list, host_in)
    sim.run(max_cycles, tail)
    return sim


def min_slack(sim):
    return min(s.slack for s in sim.core.slacks)


# ---- machine rules ----

def test_set_acts_exactly_at_T():
    sim = run("cfg OUT0, PP\nsync\ndly 10\nset OUT0, 0\nhalt")
    lv = sim.levels("OUT0")
    # sync at cycle 1 puts T at 2. dly 10: T = 12.
    assert lv.index(0) == 12
    assert not sim.core.late and min_slack(sim) == 12 - 3


def test_late_action_acts_now_and_flags():
    sim = run("cfg OUT0, PP\nsync\nset OUT0, 0, +1\nset OUT0, 1\nhalt")
    # The first set acts at 2, T = 3. The core is free at 3: on time.
    assert not sim.core.late
    sim = run("cfg OUT0, PP\nsync\nset OUT0, 0\nset OUT0, 1\nhalt")
    # No delay: the second set is due at 2, the core gets there at 3.
    assert sim.core.late and min_slack(sim) == -1
    assert sim.levels("OUT0")[3] == 1


def test_fractional_delay_has_no_drift():
    sim = run("cfg OUT0, PP\nsync\nldi r0, 200\nl: set OUT0, 0, +10.25\ndjnz r0, l\nhalt",
              max_cycles=5000)
    due = [s.due for s in sim.core.slacks]
    assert due == [2 + int(k * 10.25) for k in range(200)]


def test_wait_puts_T_on_the_bus_edge():
    src = peers.UartSource("IN0", [0x00], bit=100, start=57)
    sim = run("wait IN0, 0\nhalt", [src])
    # The core sees the edge SYNC cycles late, but T is the bus cycle.
    assert sim.core.T >> v0.FRAC == 57
    assert sim.core.halted_at == 57 + v0.SYNC + 1


def test_get_reads_the_level_at_T_and_stalls_sync_cycles():
    src = peers.UartSource("IN0", [0xFE], bit=50, start=0)  # start bit 0..49, bit0=0 50..99
    sim = run("sync\ndly 120\ngeth r0, IN0\nhalt", [src])
    # Cycle 121 is in data bit 1 (100..149), which is 1 for 0xFE.
    assert sim.core.r[0] == 1
    assert sim.core.halted_at == 121 + v0.SYNC + 1


# ---- assembler ----

def test_assembler_expressions_and_fractions():
    p = v0asm.assemble(".equ BIT 50000000 / 115200\nset OUT0, 0, +BIT\ndly BIT / 2")
    assert p[0].d == round(50_000_000 / 115_200 * 256)
    assert p[1].a == round(50_000_000 / 115_200 / 2 * 256)


@pytest.mark.parametrize("src, msg", [
    ("frob", "unknown instruction"),
    ("ldi r9, 1", "not a register"),
    ("set OUT9, 1", "not a pin"),
    ("ldi r0, 1.5", "not an integer"),
    ("dly 40000", "outside"),
    ("set OUT0, 1, 5", "starts with +"),
    ("jmp nowhere", "unknown label"),
    ("ldi r0, 1 / 0", "cannot evaluate"),
])
def test_assembler_errors(src, msg):
    with pytest.raises(v0asm.AsmError, match=msg):
        v0asm.assemble(src)


def test_cfg_rejects_driving_an_input():
    with pytest.raises(v0.SimError, match="input only"):
        run("cfg IN0, PP\nhalt")


# ---- UART ----

DATA = [0x55, 0x00, 0xFF, 0xA5, 0x3C, 0x01, 0x80, 0x7E]


@pytest.mark.parametrize("baud", [9600, 115200, 1_000_000, 3_000_000])
def test_uart_tx(baud):
    bit = CLK / baud
    sim = run(prog("uart_tx.s", BAUD=baud), host_in=DATA, max_cycles=int(bit * 100) + 1000)
    lv = sim.levels("OUT0")
    assert spec.decode_uart(lv, bit) == DATA
    assert not sim.core.late
    # Back-to-back frames on one grid. Two error terms: T rounds down to a
    # cycle (< 1), and BIT keeps 8 fraction bits (<= 1/512 per bit).
    nbits = 10 * len(DATA)
    assert spec.uart_edge_error(lv, bit) < 1 + nbits / 512


def test_uart_tx_fraction_beats_whole_cycles():
    # 9600 baud is 5208.33 cycles per bit. A whole-cycle period (5208) drifts
    # 1/3 cycle per bit; the fractional T does not.
    bit = CLK / 9600
    frac = run(prog("uart_tx.s", BAUD=9600), host_in=DATA, max_cycles=500_000)
    whole = run(prog("uart_tx.s", BIT=5208), host_in=DATA, max_cycles=500_000)
    assert spec.uart_edge_error(frac.levels("OUT0"), bit) < 1.2
    assert spec.uart_edge_error(whole.levels("OUT0"), bit) > 25


def test_uart_tx_minimum_bit_is_8_cycles():
    ok = run(prog("uart_tx.s", BIT=8), host_in=DATA)
    assert not ok.core.late and min_slack(ok) == 0
    bad = run(prog("uart_tx.s", BIT=7), host_in=DATA)
    assert bad.core.late


@pytest.mark.parametrize("skew", [-0.02, 0.0, 0.02])
def test_uart_rx_follows_the_sender_clock(skew):
    # The sender runs 2% fast or slow. The receiver times from each start edge.
    bit = CLK / 115200 * (1 + skew)
    data = [0x55, 0xC3, 0x00, 0xFF]
    src = peers.UartSource("IN0", data, bit=bit, start=300, gap=0.5)
    sim = run(prog("uart_rx.s", COUNT=4), [src], max_cycles=30_000)
    assert sim.core.host_out == data
    assert not sim.core.late


def test_uart_rx_reports_a_framing_error():
    src = peers.UartSource("IN0", [0x41], bit=CLK / 115200, start=100)
    src.edges[-1] = (src.edges[-1][0], 0)  # stop bit low
    sim = run(prog("uart_rx.s", COUNT=1), [src], max_cycles=10_000)
    assert sim.core.host_out == [512]


# ---- SPI ----

@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_spi_all_modes(mode):
    tx, rx = [0x9F, 0x00, 0xA5], [0x3C, 0xEF, 0x01]
    tgt = peers.SpiTarget(mode, "OUT1", "OUT2", "OUT3", "IN1", rx)
    sim = run(prog("spi_ctrl.s", CPOL=mode >> 1, CPHA=mode & 1), [tgt], host_in=tx)
    assert tgt.rx == tx
    assert sim.core.host_out == rx
    assert not sim.core.late
    sck = sim.levels("OUT1")
    assert sck[-1] == mode >> 1  # SCK back at idle
    assert sim.levels("OUT3")[-1] == 1  # CS high


def test_spi_minimum_half_period_is_14_cycles():
    tx = [0x12, 0x34, 0x56]

    def go(half):
        tgt = peers.SpiTarget(0, "OUT1", "OUT2", "OUT3", "IN1", [0xAA] * 3)
        sim = run(prog("spi_ctrl.s", HALF=half), [tgt], host_in=tx)
        return sim, tgt

    sim, tgt = go(14)
    assert not sim.core.late and min_slack(sim) == 0 and tgt.rx == tx
    sim, _ = go(13)
    assert sim.core.late and min_slack(sim) == -1


# ---- I2C ----

def i2c(data, addr=0x50, target_addr=0x50, stretch=0, fscl=100_000):
    tgt = peers.I2cTarget(target_addr, "IO0", "IO1", stretch)
    sim = run(prog("i2c_write.s", FSCL=fscl), [tgt], host_in=[addr << 1] + data,
              max_cycles=100_000)
    got, bad = spec.check_i2c(sim.levels("IO0"), sim.levels("IO1"), CLK,
                              "sm" if fscl <= 100_000 else "fm")
    return sim, tgt, got, bad


def test_i2c_write():
    sim, tgt, got, bad = i2c([0x12, 0x34])
    assert bad == []
    assert got == [(0xA0, True), (0x12, True), (0x34, True)]
    assert tgt.received == [0x12, 0x34]
    assert sim.core.host_out == [] and not sim.core.late


def test_i2c_write_400k():
    sim, tgt, got, bad = i2c([0x5A], fscl=400_000)
    assert bad == [] and tgt.received == [0x5A] and not sim.core.late


@pytest.mark.parametrize("stretch", [100, 600, 3000])
def test_i2c_clock_stretching(stretch):
    sim, tgt, got, bad = i2c([0x12, 0x34], stretch=stretch)
    assert bad == []
    assert tgt.received == [0x12, 0x34]
    assert not sim.core.late


def test_i2c_nack_on_wrong_address():
    sim, tgt, got, bad = i2c([0x12], addr=0x51, target_addr=0x50)
    assert bad == []
    assert got[0] == (0xA2, False)
    assert tgt.received == []
    assert sim.core.host_out == [256]
