"""Tests for the static deadline checker.

Two properties:
- Sound: for every timed action, the static worst slack is at most the slack
  that any simulation run sees there.
- Tight: for whole-cycle programs, the static worst slack equals the worst
  slack of a simulation run that takes the worst path.
"""

from pathlib import Path

import pytest

from protoemu import peers, v0, v0asm, v0check

PROGS = Path(__file__).parent.parent / "programs" / "v0"
CLK = 50_000_000


def prog(name, **defines):
    return v0asm.assemble((PROGS / name).read_text(), defines)


def sim_slacks(p, peer_list=(), host_in=(), max_cycles=300_000):
    sim = v0.Sim(p, peer_list, host_in)
    sim.run(max_cycles, tail=10)
    by_pc: dict[int, int] = {}
    for s in sim.core.slacks:
        by_pc[s.pc] = min(by_pc.get(s.pc, s.slack), s.slack)
    return by_pc


def assert_sound(p, by_pc):
    res = v0check.analyze(p)
    static = {f.pc: f.worst_slack for f in res.findings}
    for pc, seen in by_pc.items():
        assert static[pc] <= seen, f"pc {pc}: static {static[pc]} > simulated {seen}"
    return res


# ---- small programs ----

def test_straight_line_is_exact():
    p = v0asm.assemble("cfg OUT0, PP\nsync\ndly 10\nset OUT0, 0, +5\nset OUT0, 1\nhalt")
    res = v0check.analyze(p)
    # sync: L = 0. dly 10: L = 1 - 10 = -9 cycles. set: slack 9, then the
    # core is 1 cycle past floor(T) and T moves 5: L = 1 - 5 = -4.
    assert [f.worst_slack for f in res.findings] == [9, 4]
    assert res.ok


# L counts cycles the core is past T. After sync, L = 0 at the next
# instruction. Each 1-cycle instruction adds 1, `dly n` adds 1 - n.
LOOP = "cfg OUT0, PP\nsync\nldi r0, 5\ndly 2\nl: set OUT0, 0, +{d}\ndjnz r0, l\nhalt"


def test_loop_that_loses_a_cycle_per_pass_is_unbounded():
    # ldi, dly 2: L = 0 at the first set (on time). Then set (1) + djnz taken
    # (2) = 3 cycles per pass, but T moves 2: L grows by 1 each pass.
    res = v0check.analyze(v0asm.assemble(LOOP.format(d=2)))
    assert not res.ok
    assert res.worst.worst_slack == float("-inf")


def test_loop_that_keeps_up_is_proved():
    res = v0check.analyze(v0asm.assemble(LOOP.format(d=3)))
    assert res.ok and res.worst.worst_slack == 0


BRANCH = ("cfg OUT0, PP\nsync\ndly {x}\npull r0\nbnz r0, a\nldi r1, 0\nldi r1, 0\n"
          "a: set OUT0, 0\nhalt")


def test_both_branch_sides_count():
    # At the set: taken path L = (1 - x) + 1 + 2 = 4 - x.
    # Not taken: (1 - x) + 1 + 1 + 1 + 1 = 5 - x, one cycle slower.
    # x = 4: the taken path is on time, the other is 1 late.
    res = v0check.analyze(v0asm.assemble(BRANCH.format(x=4)))
    assert not res.ok and res.worst.worst_slack == -1
    res = v0check.analyze(v0asm.assemble(BRANCH.format(x=5)))
    assert res.ok and res.worst.worst_slack == 0


def test_wait_resets_L_exactly():
    p = v0asm.assemble("cfg OUT0, PP\nwait IN0, 0\nset OUT0, 0\nhalt")
    res = v0check.analyze(p)
    # After wait the core is IN_LAT + 1 cycles past the edge, and T is the edge.
    assert res.findings[0].worst_slack == -(v0.IN_LAT + 1)
    p = v0asm.assemble(f"cfg OUT0, PP\nwait IN0, 0\ndly {v0.IN_LAT + 2}\nset OUT0, 0\nhalt")
    assert v0check.analyze(p).findings[0].worst_slack == 0


def test_deadline_too_far_ahead():
    p = v0asm.assemble("cfg OUT0, PP\nsync\ndly 20000\ndly 20000\nset OUT0, 0\nhalt")
    res = v0check.analyze(p)
    assert res.too_far and not res.ok


# ---- the firmware: sound and tight ----

DATA = [0x55, 0x00, 0xFF, 0xA5]


@pytest.mark.parametrize("bit, ok", [(8, True), (7, False), (CLK / 115200, True)])
def test_uart_tx(bit, ok):
    p = prog("uart_tx.s", BIT=bit)
    by_pc = sim_slacks(p, host_in=DATA)
    res = assert_sound(p, by_pc)
    assert res.ok is ok
    if bit == int(bit):  # whole cycles: tight
        assert res.worst.worst_slack == min(by_pc.values())


@pytest.mark.parametrize("half, ok", [(15, True), (14, False), (25, True)])
def test_spi(half, ok):
    p = prog("spi_ctrl.s", HALF=half)
    tgt = peers.SpiTarget(0, "OUT1", "OUT2", "OUT3", "IN1", [0xAA] * 3)
    by_pc = sim_slacks(p, [tgt], host_in=[1, 2, 3])
    res = assert_sound(p, by_pc)
    assert res.ok is ok
    assert res.worst.worst_slack == min(by_pc.values())


@pytest.mark.parametrize("skew", [-0.02, 0.0, 0.02])
def test_uart_rx_proof_holds_for_any_sender(skew):
    p = prog("uart_rx.s", COUNT=3)
    src = peers.UartSource("IN0", [0x55, 0xC3, 0x00], bit=CLK / 115200 * (1 + skew),
                           start=300, gap=0.5)
    res = assert_sound(p, sim_slacks(p, [src]))
    assert res.ok


@pytest.mark.parametrize("stretch", [0, 600, 3000])
def test_i2c_proof_holds_for_any_stretch(stretch):
    p = prog("i2c_write.s")
    tgt = peers.I2cTarget(0x50, "IO0", "IO1", stretch)
    res = assert_sound(p, sim_slacks(p, [tgt], host_in=[0xA0, 0x12, 0x34]))
    assert res.ok


def test_i2c_nack_path_is_checked_too():
    # The NACK path is not taken in a normal run. The static proof covers it.
    p = prog("i2c_write.s")
    tgt = peers.I2cTarget(0x50, "IO0", "IO1")
    res = assert_sound(p, sim_slacks(p, [tgt], host_in=[0xA2, 0x12]))
    assert res.ok


def test_cli(capsys):
    assert v0check.main([str(PROGS / "spi_ctrl.s"), "-D", "HALF=15"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert v0check.main([str(PROGS / "spi_ctrl.s"), "-D", "HALF=14"]) == 1
    assert "LATE" in capsys.readouterr().out
