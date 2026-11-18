"""cocotb tests for timed_out. Each test checks one line of the timing contract."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())  # 50 MHz
    dut.arm.value = 0
    dut.t_due.value = 0
    dut.val.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    # The last edge applied the reset: this is cycle 0. rst_n goes high
    # before the next edge, so the timer counts from here.
    dut.rst_n.value = 1
    await ReadOnly()


async def next_cycle(dut):
    await RisingEdge(dut.clk)
    await ReadOnly()


def now(dut):
    return int(dut.now.value)


async def arm(dut, lead, val, due=None):
    """Pulse arm in the next cycle c, with t_due = c + lead (or `due`).

    Call it in the read-only phase of a cycle k. Then c = k + 1.
    Returns (c, t_due). On return the test is in cycle c + 1, read-only.

    Read registers only in ReadOnly: right after RisingEdge, cocotb still
    sees the values from before the edge.
    """
    c = (now(dut) + 1) & 0xFFFF
    await RisingEdge(dut.clk)
    t_due = (c + lead if due is None else due) & 0xFFFF
    dut.arm.value, dut.t_due.value, dut.val.value = 1, t_due, val
    await RisingEdge(dut.clk)
    dut.arm.value = 0
    await ReadOnly()
    assert now(dut) == (c + 1) & 0xFFFF
    return c, t_due


async def run_to(dut, cycle, max_cycles):
    """Step until now == cycle. Bounded by max_cycles."""
    for _ in range(max_cycles):
        if now(dut) == cycle & 0xFFFF:
            return
        await next_cycle(dut)
    raise AssertionError(f"now did not reach {cycle} in {max_cycles} cycles")


@cocotb.test()
async def test_reset_state(dut):
    await reset(dut)
    assert now(dut) == 0
    assert dut.pin.value == 1 and dut.armed.value == 0 and dut.late.value == 0


@cocotb.test()
async def test_on_time_lands_exactly(dut):
    await reset(dut)
    _, due = await arm(dut, lead=10, val=0)
    await run_to(dut, due - 1, 20)
    assert dut.pin.value == 1, "pin changed before the due cycle"
    await next_cycle(dut)
    assert now(dut) == due
    assert dut.pin.value == 0, "pin is not low at the due cycle"
    assert dut.late.value == 0 and dut.armed.value == 0


@cocotb.test()
async def test_minimum_lead_is_2(dut):
    await reset(dut)
    c, _ = await arm(dut, lead=2, val=0)
    assert dut.pin.value == 1
    await next_cycle(dut)
    assert now(dut) == c + 2 and dut.pin.value == 0
    assert dut.late.value == 0


@cocotb.test()
async def test_late_acts_at_c_plus_2_and_flags(dut):
    await reset(dut)
    c, _ = await arm(dut, lead=1, val=0)  # 1 cycle short of the minimum
    assert dut.pin.value == 1
    await next_cycle(dut)
    assert now(dut) == c + 2 and dut.pin.value == 0
    assert dut.late.value == 1
    await ClockCycles(dut.clk, 5)
    await ReadOnly()
    assert dut.late.value == 1, "late is not sticky"


@cocotb.test()
async def test_wrap(dut):
    await reset(dut)
    # Run the timer near the top, then arm a due time past the wrap.
    await run_to(dut, 0xFFF0, 0x10000)
    _, due = await arm(dut, lead=0, val=0, due=0x0005)
    await run_to(dut, 0x0004, 40)
    assert dut.pin.value == 1
    await next_cycle(dut)
    assert now(dut) == due and dut.pin.value == 0
    assert dut.late.value == 0
