"""Assembler for the Probe A timeline machine.

Syntax, one statement per line:

    ; comment
    .equ NAME value      define a constant
    label:               name the next instruction
    op [arg]             arg is a number, a constant, or a label

Constants can also come from the command line: -D NAME=value.
"""

from __future__ import annotations

import re

from . import model

_LABEL = re.compile(r"^([A-Za-z_]\w*):$")
_NAME = re.compile(r"^[A-Za-z_]\w*$")


class AsmError(Exception):
    def __init__(self, line_no: int, msg: str):
        super().__init__(f"line {line_no}: {msg}")
        self.line_no = line_no


def _value(tok: str, names: dict[str, int], line_no: int) -> int:
    if tok in names:
        return names[tok]
    try:
        return int(tok, 0)
    except ValueError:
        raise AsmError(line_no, f"unknown name or bad number {tok!r}") from None


def assemble(src: str, defines: dict[str, int] | None = None) -> list[model.Instr]:
    consts: dict[str, int] = dict(defines or {})
    labels: dict[str, int] = {}
    stmts: list[tuple[int, str, str | None]] = []

    # Pass 1: constants, labels, and the statement list.
    for line_no, raw in enumerate(src.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = _LABEL.match(line)
        if m:
            name = m.group(1)
            if name in labels or name in consts:
                raise AsmError(line_no, f"{name!r} is already defined")
            labels[name] = len(stmts)
            continue
        toks = line.split()
        if toks[0] == ".equ":
            if len(toks) != 3 or not _NAME.match(toks[1]):
                raise AsmError(line_no, "use: .equ NAME value")
            if toks[1] not in consts:  # a -D define wins over the source
                consts[toks[1]] = _value(toks[2], consts, line_no)
            continue
        op = toks[0].lower()
        if op not in model.OPCODES:
            raise AsmError(line_no, f"unknown instruction {toks[0]!r}")
        want = 2 if model.OPCODES[op] else 1
        if len(toks) != want:
            raise AsmError(line_no, f"{op} takes {want - 1} operand(s)")
        stmts.append((line_no, op, toks[1] if want == 2 else None))

    # Pass 2: resolve operands.
    names = {**consts, **labels}
    prog = []
    for line_no, op, arg in stmts:
        val = _value(arg, names, line_no) if arg is not None else 0
        if val < 0:
            raise AsmError(line_no, f"operand {val} is negative")
        prog.append(model.Instr(op, val))
    return prog
