"""Tests for the reference model, the assembler, and the deadline checker.

The exact values come from theorem final_state in
lean/ProtoEmu/Probe/UartTx.lean. The frame check is written from the UART 8N1
standard, not from the model.
"""

from pathlib import Path

import pytest

from protoemu import asm, check, model

PROG_SRC = (Path(__file__).parent.parent / "programs" / "uart_tx.s").read_text()
BYTES = [0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80, 0x3C, 0xC3]


def uart_tx(p: int) -> list[model.Instr]:
    return asm.assemble(PROG_SRC, {"P": p})


def assert_frame(evs, t0: int, p: int, b: int) -> None:
    """UART 8N1: start bit low, 8 data bits LSB first, stop bit high, p cycles each."""
    def w(t):
        return model.level(True, evs, t)
    for t in range(t0, t0 + p):
        assert w(t) is False, f"start bit at cycle {t}"
    for k in range(8):
        want = (b >> k) & 1 == 1
        for t in range(t0 + (k + 1) * p, t0 + (k + 2) * p):
            assert w(t) is want, f"data bit {k} at cycle {t}"
    for t in range(t0 + 9 * p, t0 + 10 * p):
        assert w(t) is True, f"stop bit at cycle {t}"


def test_assembler_matches_lean_program():
    # uartTx p in the Lean file.
    p = 7
    assert uart_tx(p) == [
        model.Instr("ldi1", 8), model.Instr("pinlow"), model.Instr("dly", p),
        model.Instr("put"), model.Instr("dly", p), model.Instr("djnz", 3),
        model.Instr("pinhigh"), model.Instr("dly", p), model.Instr("waitt"),
        model.Instr("halt"),
    ]


@pytest.mark.parametrize("p", [4, 5, 9, 434])
@pytest.mark.parametrize("b", BYTES)
def test_final_state_matches_lean(p, b):
    t0, n = 20, 3
    s = model.run(uart_tx(p), model.init(b, t0, n), max_steps=31)
    assert (s.pc, s.now, s.T, s.r0, s.r1, s.late, s.halted) == (
        9, t0 + 10 * p + 1, t0 + 10 * p, b >> 8, 0, False, True)
    assert s.evs == ((t0, False),) + tuple(
        (t0 + p + j * p, (b >> j) & 1 == 1) for j in range(8)) + ((t0 + 9 * p, True),)
    # 31 steps, as in the theorem: 30 steps do not reach halt.
    assert not model.run(uart_tx(p), model.init(b, t0, n), max_steps=30).halted


@pytest.mark.parametrize("p", [4, 5, 6, 434])
def test_frame_is_valid_for_every_byte(p):
    t0 = 10
    for b in range(256):
        s = model.run(uart_tx(p), model.init(b, t0, 0), max_steps=100)
        assert s.halted and not s.late
        assert_frame(s.evs, t0, p, b)


def test_checker_passes_at_p4_with_slack_0():
    # p = 4 is the bound in the Lean theorem. The bit loop is 4 cycles, so the
    # worst slack is exactly 0.
    rep = check.check(uart_tx(4), range(256), t0=10, n=0, max_steps=100)
    assert rep.halted and not rep.late
    assert rep.min_slack == 0


def test_checker_fails_at_p3():
    # Below the Lean bound: the 4-cycle bit loop cannot keep a 3-cycle period.
    # The second put is 1 cycle late, and each pass of the loop adds 1 more:
    # -7 at the eighth put and at the stop bit.
    rep = check.check(uart_tx(3), range(256), t0=10, n=0, max_steps=100)
    assert rep.late
    assert rep.min_slack == -7
    assert rep.worst.pc == 3
    s = model.run(uart_tx(3), model.init(0x55, 10, 0), max_steps=100)
    assert [sl.slack for sl in s.slacks] == [9, 1, -1, -2, -3, -4, -5, -6, -7, -7]


def test_checker_reports_late_start():
    # The core starts at cycle 9, after the frame start at 5. ldi1 takes it to
    # cycle 10, so the start bit (pc 1, due at 5) is 5 cycles late.
    rep = check.check(uart_tx(434), [0x41], t0=5, n=9, max_steps=100)
    assert rep.late
    assert rep.worst.pc == 1 and rep.min_slack == -5


def test_cli_pass_and_fail(capsys):
    src = str(Path(__file__).parent.parent / "programs" / "uart_tx.s")
    assert check.main([src]) == 0
    assert "PASS" in capsys.readouterr().out
    assert check.main([src, "-D", "P=3"]) == 1
    assert "FAIL" in capsys.readouterr().out


@pytest.mark.parametrize("src, msg", [
    ("frob", "unknown instruction"),
    ("dly", "takes 1 operand"),
    ("dly NOPE", "unknown name"),
    ("a:\na:\nhalt", "already defined"),
    ("dly -1", "negative"),
])
def test_assembler_errors(src, msg):
    with pytest.raises(asm.AsmError, match=msg):
        asm.assemble(src)
