"""Reference model of the Probe A timeline machine.

This model copies the semantics of lean/ProtoEmu/Probe/UartTx.lean, one rule
per instruction. It is a probe, not the ISA: docs/isa.md does not exist yet.
When the ISA spec lands, this file follows the spec.

Time is in clock cycles. `now` is the cycle at which the core is. `T` is the
timeline cursor: the cycle at which the next timed action must happen. A timed
action acts at max(now, T). If the core arrives after T, the action is late.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# A pin event: from cycle `t` on, the pin has level `v`.
Event = tuple[int, bool]


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int = 0


# Opcodes. The argument meaning matches the Lean constructors.
LDI1 = "ldi1"  # r1 <- arg
PIN_LOW = "pinlow"  # timed: pin low at T
PIN_HIGH = "pinhigh"  # timed: pin high at T
PUT = "put"  # timed: pin <- bit 0 of r0 at T, then r0 <- r0 / 2
DLY = "dly"  # T <- T + arg
DJNZ = "djnz"  # r1 <- r1 - 1, jump to arg if not 0 (2 cycles if taken)
WAIT_T = "waitt"  # stall until T
HALT = "halt"

OPCODES = {LDI1: True, PIN_LOW: False, PIN_HIGH: False, PUT: False,
           DLY: True, DJNZ: True, WAIT_T: False, HALT: False}
TIMED = {PIN_LOW, PIN_HIGH, PUT}


@dataclass(frozen=True)
class Slack:
    """One timed action: where it is, when it was due, and when the core got there."""
    pc: int
    due: int
    arrived: int

    @property
    def slack(self) -> int:
        return self.due - self.arrived


@dataclass(frozen=True)
class St:
    pc: int
    now: int
    T: int
    r0: int
    r1: int
    late: bool = False
    halted: bool = False
    evs: tuple[Event, ...] = ()
    slacks: tuple[Slack, ...] = field(default=(), compare=False)


def init(b: int, t0: int, n: int) -> St:
    """Byte b in r0, timeline cursor at frame start t0, core at cycle n."""
    return St(pc=0, now=n, T=t0, r0=b, r1=0)


def _pin_act(s: St, v: bool) -> St:
    at = max(s.now, s.T)
    return replace(s, now=at + 1, pc=s.pc + 1,
                   late=s.late or s.T < s.now,
                   evs=s.evs + ((at, v),),
                   slacks=s.slacks + (Slack(s.pc, s.T, s.now),))


def execute(i: Instr, s: St) -> St:
    if i.op == LDI1:
        return replace(s, r1=i.arg, now=s.now + 1, pc=s.pc + 1)
    if i.op == PIN_LOW:
        return _pin_act(s, False)
    if i.op == PIN_HIGH:
        return _pin_act(s, True)
    if i.op == PUT:
        return replace(_pin_act(s, s.r0 % 2 == 1), r0=s.r0 // 2)
    if i.op == DLY:
        return replace(s, T=s.T + i.arg, now=s.now + 1, pc=s.pc + 1)
    if i.op == DJNZ:
        # Lean Nat subtraction saturates at 0.
        if max(s.r1 - 1, 0) == 0:
            return replace(s, r1=0, now=s.now + 1, pc=s.pc + 1)
        return replace(s, r1=s.r1 - 1, now=s.now + 2, pc=i.arg)
    if i.op == WAIT_T:
        return replace(s, now=max(s.now, s.T) + 1, pc=s.pc + 1)
    if i.op == HALT:
        return replace(s, halted=True)
    raise ValueError(f"unknown opcode {i.op!r}")


def step(prog: list[Instr], s: St) -> St:
    if s.halted:
        return s
    if not 0 <= s.pc < len(prog):
        return replace(s, halted=True)
    return execute(prog[s.pc], s)


def run(prog: list[Instr], s: St, max_steps: int) -> St:
    """Run until halt, or for max_steps steps. The caller checks `halted`."""
    for _ in range(max_steps):
        if s.halted:
            break
        s = step(prog, s)
    return s


def level(idle: bool, evs: tuple[Event, ...], t: int) -> bool:
    """The pin level at cycle t: the last event at or before t, else idle."""
    acc = idle
    for et, ev in evs:
        if et <= t:
            acc = ev
    return acc
