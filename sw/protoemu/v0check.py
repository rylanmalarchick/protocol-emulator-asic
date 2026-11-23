"""Static deadline checker for the ISA v0 proposal.

It proves, for every path through the program and for any input timing, that
each timed action is on time. It does not run the program.

The analysis tracks one number per program point:

    L = now * ONE - T          (both in 1/ONE cycles)

L <= 0 means the core is at or ahead of the timeline cursor. A timed action is
late when floor(T) < now, which for an integer `now` is the same as L > 0.

For each program point the checker keeps an interval [lo, hi] that holds L on
every path, plus a flag: True when T has no fraction on every path. Branches
follow both sides. Loops repeat until the intervals stop changing. After
WIDEN_AFTER updates at one point, a bound that still moves goes to infinity.

`wait` sets T to the cycle of the input edge, and the core resumes
IN_LAT + 1 cycles after the edge. So after `wait`, L is exact no matter when the
edge comes. This is why input timing (clock stretching, a fast or slow
UART sender) cannot break a proof.

Assumptions:
- An edge that `wait` waits for comes after `wait` issues (see the proposal).
- The checker proves timing only. It does not prove that a `wait` ends.

The checker also enforces the 16-bit timer bound: T must never be more than
2^15 cycles ahead of `now`.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from . import v0, v0asm

C = v0.ONE
INF = math.inf
WIDEN_AFTER = 64
MAX_UPDATES = 100_000
MAX_LEAD = (1 << 15) * C


@dataclass(frozen=True)
class St:
    lo: float
    hi: float
    int_t: bool  # T has no fraction on every path

    def join(self, o: "St") -> "St":
        return St(min(self.lo, o.lo), max(self.hi, o.hi), self.int_t and o.int_t)

    def add(self, k: float) -> "St":
        return St(self.lo + k, self.hi + k, self.int_t)


def _act(s: St) -> St:
    """L after the core reaches max(now, floor(T)) and spends 1 cycle there."""
    parts = []
    if s.lo <= 0:  # on time on some path: now becomes floor(T) + 1
        parts.append(St(C, C, True) if s.int_t else St(1, C, False))
    if s.hi > 0:  # late on some path: the action acts now
        parts.append(St(max(s.lo, 1) + C, s.hi + C, s.int_t))
    out = parts[0]
    for p in parts[1:]:
        out = out.join(p)
    return St(out.lo, out.hi, s.int_t and out.int_t)


def transfer(ins: v0.Instr, pc: int, s: St) -> list[tuple[int, St]]:
    op = ins.op
    if op == "halt":
        return []
    if op in ("djnz", "bz", "bnz"):
        return [(ins.b, s.add(2 * C)), (pc + 1, s.add(C))]
    if op == "jmp":
        return [(ins.a, s.add(2 * C))]
    if op == "dly":
        return [(pc + 1, St(s.lo + C - ins.a, s.hi + C - ins.a, s.int_t and ins.a % C == 0))]
    if op == "sync":
        return [(pc + 1, St(0, 0, True))]
    if op == "wait":
        return [(pc + 1, St((v0.IN_LAT + 1) * C, (v0.IN_LAT + 1) * C, True))]
    if op == "waitt":
        return [(pc + 1, _act(s))]
    if op in v0.TIMED:
        a = _act(s)
        extra = v0.IN_LAT * C if op in ("get", "geth") else 0
        return [(pc + 1, St(a.lo + extra - ins.d, a.hi + extra - ins.d,
                            a.int_t and ins.d % C == 0))]
    return [(pc + 1, s.add(C))]  # every other op: 1 cycle


@dataclass(frozen=True)
class Finding:
    pc: int
    line: int
    op: str
    worst_slack: float  # cycles; negative is late; -inf is unbounded


@dataclass
class Result:
    findings: list[Finding]
    states: dict[int, St]
    too_far: list[int]  # lines where T can run more than 2^15 cycles ahead

    @property
    def ok(self) -> bool:
        return not self.too_far and all(f.worst_slack >= 0 for f in self.findings)

    @property
    def worst(self) -> Finding | None:
        return min(self.findings, key=lambda f: f.worst_slack, default=None)


def analyze(prog: list[v0.Instr]) -> Result:
    states: dict[int, St] = {0: St(0, 0, True)}
    updates: dict[int, int] = {}
    work = [0]
    for _ in range(MAX_UPDATES):
        if not work:
            break
        pc = work.pop()
        if not 0 <= pc < len(prog):
            raise v0.SimError(f"a path leaves the program at pc {pc}")
        for nxt, s in transfer(prog[pc], pc, states[pc]):
            old = states.get(nxt)
            new = s if old is None else old.join(s)
            if new == old:
                continue
            updates[nxt] = updates.get(nxt, 0) + 1
            if old is not None and updates[nxt] > WIDEN_AFTER:
                new = St(-INF if new.lo < old.lo else new.lo,
                         INF if new.hi > old.hi else new.hi, new.int_t)
            states[nxt] = new
            if nxt not in work:
                work.append(nxt)
    else:
        raise v0.SimError("the analysis did not converge")

    findings, too_far = [], []
    for pc, ins in enumerate(prog):
        s = states.get(pc)
        if s is None:
            continue
        if s.lo < -MAX_LEAD:
            too_far.append(ins.line)
        if ins.op in v0.TIMED:
            slack = -INF if s.hi == INF else math.floor(-s.hi / C)
            findings.append(Finding(pc, ins.line, ins.op, slack))
    return Result(findings, states, too_far)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prove the deadlines of a v0 program.")
    ap.add_argument("source", type=Path)
    ap.add_argument("-D", dest="defines", action="append", default=[], metavar="NAME=VALUE")
    args = ap.parse_args(argv)
    defines = {}
    for d in args.defines:
        name, sep, val = d.partition("=")
        if not sep:
            ap.error(f"bad -D {d!r}, use NAME=VALUE")
        defines[name] = float(val)
    try:
        prog = v0asm.assemble(args.source.read_text(), defines)
    except v0asm.AsmError as e:
        print(f"{args.source}: {e}", file=sys.stderr)
        return 2
    res = analyze(prog)
    src = args.source.read_text().splitlines()
    print(f"{'line':>5}  {'slack':>8}  instruction")
    for f in res.findings:
        mark = "" if f.worst_slack >= 0 else "  LATE"
        print(f"{f.line:>5}  {f.worst_slack:>8}  {src[f.line - 1].split(';')[0].strip()}{mark}")
    for line in res.too_far:
        print(f"line {line}: T can run more than 2^15 cycles ahead of the core")
    w = res.worst
    if res.ok:
        print(f"PASS: every timed action is on time on every path (worst slack {w.worst_slack if w else '-'})")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
