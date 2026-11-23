"""ISA v0 proposal: machine model and cycle simulator.

A proposal for discussion, not the contract. docs/isa.md is the contract, and
it does not exist yet. See sw/ISA-v0-proposal.md for the rationale.

The timeline rules extend the Probe A machine (lean/ProtoEmu/Probe/UartTx.lean):

- T is the timeline cursor. A timed action acts at cycle max(now, floor(T)).
  If floor(T) < now, the action is late.
- New here: T has FRAC fraction bits, so a loop can step a non-integer bit
  period (434.03 cycles for 115200 baud at 50 MHz) without drift.
- New here: a timed action can carry a delay, `set OUT0, 1, +BIT`. It acts,
  then adds the delay to T, in one instruction.
- New here: `wait pin, level` stalls until the pin reaches the level, then
  sets T to the cycle of that edge. Later actions are relative to the edge.

Inputs pass through a SYNC-stage synchronizer. The model hides the stages in
the timestamps: `get` at T reads the pin level of cycle T, and `wait` reports
the bus cycle of the edge. The cost shows up as stall cycles: the core gets a
sampled value SYNC cycles after the sample, and sees an edge SYNC cycles late.

The simulator steps one clock cycle at a time, so peer devices on the bus can
react to the core: an I2C target can stretch the clock or drive ACK.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

FRAC = 8  # fraction bits of T
ONE = 1 << FRAC
SYNC = 2  # input synchronizer stages
NREG = 8
MASK16 = 0xFFFF
EMPTY = 0x100  # `pull` result when the host FIFO is empty

# Pin numbers. OUTx are outputs, IOx are bidirectional, INx are inputs.
PINS = ({f"OUT{i}": i for i in range(6)}
        | {f"IO{i}": 8 + i for i in range(8)}
        | {f"IN{i}": 16 + i for i in range(4)})
NPIN = 20
OUT_PINS = set(range(6))
IO_PINS = set(range(8, 16))
IN_PINS = set(range(16, 20))

# Pin modes for `cfg`. PP and OD start the pin at 1 (high, or released).
# PP0 is push-pull that starts low, for lines that idle low (WS2812).
MODE_IN, MODE_PP, MODE_OD, MODE_PP0 = 0, 1, 2, 3
MODES = {"IN": MODE_IN, "PP": MODE_PP, "OD": MODE_OD, "PP0": MODE_PP0}

# name: operand kinds. r = register, i = integer, p = pin, l = label,
# d = delay in cycles (stored with FRAC fraction bits).
# Timed ops take an optional trailing delay operand.
OPS = {
    "ldi": "ri", "mov": "rr", "addi": "ri", "andi": "ri", "xori": "ri",
    "shli": "ri", "shri": "ri",
    "djnz": "rl", "bz": "rl", "bnz": "rl", "jmp": "l",
    "dly": "d", "sync": "", "waitt": "", "wait": "pi", "cfg": "pi",
    "set": "pi", "put": "pr", "puth": "pr", "get": "rp", "geth": "rp",
    "pull": "r", "push": "r", "halt": "",
}
TIMED = {"set", "put", "puth", "get", "geth"}


class SimError(Exception):
    pass


@dataclass(frozen=True)
class Instr:
    op: str
    a: int = 0
    b: int = 0
    d: int = 0  # delay after a timed action, FRAC fraction bits
    line: int = 0


@dataclass(frozen=True)
class Slack:
    pc: int
    line: int
    due: int
    arrived: int

    @property
    def slack(self) -> int:
        return self.due - self.arrived


class Core:
    def __init__(self, prog: list[Instr], host_in=()):
        self.prog = prog
        self.r = [0] * NREG
        self.pc = 0
        self.T = 0
        self.ready = 0  # first cycle at which the next instruction can issue
        self.late = False
        self.halted = False
        self.halted_at: int | None = None
        self.slacks: list[Slack] = []
        self.mode = [MODE_IN] * NPIN
        self.out = [1] * NPIN  # output registers reset to 1: idle high, or released
        self.writes: list[tuple[int, int, int]] = []  # (cycle, pin, level)
        self.samples: list[tuple[int, int, int, str]] = []  # (cycle, reg, pin, op)
        self.waiting: tuple[int, int] | None = None
        self.host_in = deque(host_in)
        self.host_out: list[int] = []

    # One timed action: when it acts, and its slack record.
    def _timed(self, t: int, ins: Instr) -> int:
        due = self.T >> FRAC
        at = max(t, due)
        self.late = self.late or due < t
        self.slacks.append(Slack(self.pc, ins.line, due, t))
        self.T += ins.d
        return at

    def _drive(self, pin: int, ins: Instr) -> None:
        if self.mode[pin] not in (MODE_PP, MODE_OD):
            raise SimError(f"line {ins.line}: pin {pin} is not an output (use cfg)")

    def issue(self, t: int, bus: list[list[int]]) -> None:
        if self.halted or t < self.ready:
            return
        if self.waiting is not None:
            pin, lvl = self.waiting
            seen = t - SYNC
            if seen >= 0 and bus[seen][pin] == lvl:
                self.T = seen << FRAC
                self.waiting = None
                self.pc += 1
                self.ready = t + 1
            return
        if not 0 <= self.pc < len(self.prog):
            raise SimError(f"pc {self.pc} is outside the program")
        ins = self.prog[self.pc]
        op, a, b = ins.op, ins.a, ins.b
        r = self.r
        nxt, cost = self.pc + 1, 1
        if op == "ldi":
            r[a] = b & MASK16
        elif op == "mov":
            r[a] = r[b]
        elif op == "addi":
            r[a] = (r[a] + b) & MASK16
        elif op == "andi":
            r[a] &= b
        elif op == "xori":
            r[a] = (r[a] ^ b) & MASK16
        elif op == "shli":
            r[a] = (r[a] << b) & MASK16
        elif op == "shri":
            r[a] >>= b
        elif op == "djnz":
            r[a] = (r[a] - 1) & MASK16
            if r[a] != 0:
                nxt, cost = b, 2
        elif op in ("bz", "bnz"):
            if (r[a] == 0) == (op == "bz"):
                nxt, cost = b, 2
        elif op == "jmp":
            nxt, cost = a, 2
        elif op == "dly":
            self.T += a
        elif op == "sync":
            self.T = (t + 1) << FRAC  # the cycle of the next instruction
        elif op == "waitt":
            cost = max(t, self.T >> FRAC) + 1 - t
        elif op == "wait":
            self.waiting = (a, b)
            self.ready = t + 1
            return  # pc moves on when the edge arrives
        elif op == "cfg":
            if a in IN_PINS and b != MODE_IN:
                raise SimError(f"line {ins.line}: pin {a} is input only")
            if a in OUT_PINS and b == MODE_IN:
                raise SimError(f"line {ins.line}: pin {a} is output only")
            self.mode[a] = MODE_PP if b == MODE_PP0 else b
            self.out[a] = 0 if b == MODE_PP0 else 1
        elif op in ("set", "put", "puth"):
            self._drive(a, ins)
            if op == "set":
                lvl = b & 1
            elif op == "put":
                lvl = r[b] & 1
                r[b] >>= 1
            else:
                lvl = (r[b] >> 7) & 1
                r[b] = (r[b] << 1) & 0xFF
            at = self._timed(t, ins)
            self.writes.append((at, a, lvl))
            cost = at + 1 - t
        elif op in ("get", "geth"):
            at = self._timed(t, ins)
            self.samples.append((at, a, b, op))
            cost = at + SYNC + 1 - t
        elif op == "pull":
            r[a] = self.host_in.popleft() if self.host_in else EMPTY
        elif op == "push":
            self.host_out.append(r[a])
        elif op == "halt":
            self.halted, self.halted_at = True, t
            return
        else:
            raise SimError(f"unknown op {op!r}")
        self.pc = nxt
        self.ready = t + cost

    def apply_writes(self, t: int) -> None:
        keep = []
        for at, pin, lvl in self.writes:
            if at == t:
                self.out[pin] = lvl
            else:
                keep.append((at, pin, lvl))
        self.writes = keep

    def apply_samples(self, t: int, levels: list[int]) -> None:
        keep = []
        for at, reg, pin, op in self.samples:
            if at != t:
                keep.append((at, reg, pin, op))
            elif op == "get":  # LSB first, byte
                self.r[reg] = (self.r[reg] >> 1) | (levels[pin] << 7)
            else:  # geth: MSB first
                self.r[reg] = ((self.r[reg] << 1) | levels[pin]) & MASK16
        self.samples = keep


class Peer:
    """A device on the bus. drives() gives its levels for the coming cycle:
    for an input pin, the level; for an open-drain pin, 0 pulls low and 1 releases."""

    def drives(self) -> dict[int, int]:
        return {}

    def observe(self, t: int, levels: list[int]) -> None:
        pass


class Sim:
    def __init__(self, prog: list[Instr], peers=(), host_in=()):
        self.core = Core(prog, host_in)
        self.peers = list(peers)
        self.bus: list[list[int]] = []

    def _resolve(self) -> list[int]:
        c = self.core
        peer = [p.drives() for p in self.peers]
        levels = [1] * NPIN
        for pin in range(NPIN):
            low = any(d.get(pin, 1) == 0 for d in peer)
            mode = c.mode[pin]
            if mode == MODE_PP:
                levels[pin] = c.out[pin]
            elif mode == MODE_OD:
                levels[pin] = 0 if (c.out[pin] == 0 or low) else 1
            else:  # input, or an IO pin set to input: peers drive it, idle high
                levels[pin] = 0 if low else 1
        return levels

    def run(self, max_cycles: int, tail: int = 0) -> None:
        """Run to halt, plus `tail` cycles so peers see the end. Bounded."""
        c = self.core
        for t in range(max_cycles):
            c.issue(t, self.bus)
            c.apply_writes(t)
            levels = self._resolve()
            self.bus.append(levels)
            c.apply_samples(t, levels)
            for p in self.peers:
                p.observe(t, levels)
            if c.halted and not c.writes and not c.samples and t >= c.halted_at + tail:
                return
        raise SimError(f"no halt within {max_cycles} cycles")

    def levels(self, pin: str) -> list[int]:
        n = PINS[pin]
        return [lv[n] for lv in self.bus]
