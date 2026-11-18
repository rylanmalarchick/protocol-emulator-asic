"""Deadline checker for the Probe A timeline machine.

The machine has no data-dependent timing: every instruction takes a fixed
number of cycles, and the only branch (djnz) counts a register that the
program loads with a constant. So one run of the reference model visits every
timed action with its exact arrival cycle. The checker runs the program once
per input byte and reports the slack of each timed action. Slack is T minus the
arrival cycle. A negative slack is a missed deadline.

When the ISA gains data-dependent branches, this exact-run method stops being
complete. The checker must then bound every path. That is the open design work.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from . import asm, model


@dataclass(frozen=True)
class Report:
    halted: bool
    late: bool
    min_slack: int | None
    worst: model.Slack | None
    final: model.St


def check(prog: list[model.Instr], bytes_in: range | list[int], t0: int, n: int,
          max_steps: int) -> Report:
    worst: model.Slack | None = None
    halted = True
    late = False
    final = None
    for b in bytes_in:
        final = model.run(prog, model.init(b, t0, n), max_steps)
        halted = halted and final.halted
        late = late or final.late
        for sl in final.slacks:
            if worst is None or sl.slack < worst.slack:
                worst = sl
    if final is None:
        raise ValueError("no input bytes to check")
    return Report(halted, late, None if worst is None else worst.slack, worst, final)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assemble a program and check its deadlines.")
    ap.add_argument("source", type=Path)
    ap.add_argument("-D", dest="defines", action="append", default=[],
                    metavar="NAME=VALUE", help="define a constant")
    ap.add_argument("--t0", type=int, default=16, help="frame start cycle (default 16)")
    ap.add_argument("--start", type=int, default=0, help="core start cycle (default 0)")
    ap.add_argument("--max-steps", type=int, default=100_000)
    args = ap.parse_args(argv)

    defines = {}
    for d in args.defines:
        name, sep, val = d.partition("=")
        if not sep:
            ap.error(f"bad -D {d!r}, use NAME=VALUE")
        defines[name] = int(val, 0)

    try:
        prog = asm.assemble(args.source.read_text(), defines)
    except asm.AsmError as e:
        print(f"{args.source}: {e}", file=sys.stderr)
        return 2

    rep = check(prog, range(256), args.t0, args.start, args.max_steps)
    print(f"{len(prog)} instructions, 256 input bytes checked")
    if not rep.halted:
        print(f"FAIL: no halt within {args.max_steps} steps")
        return 1
    if rep.worst is None:
        print("PASS: no timed actions")
        return 0
    w = rep.worst
    print(f"worst slack {w.slack} cycles at pc {w.pc} (due {w.due}, arrived {w.arrived})")
    if rep.late:
        print("FAIL: a timed action is late")
        return 1
    print("PASS: every timed action is on time")
    return 0


if __name__ == "__main__":
    sys.exit(main())
