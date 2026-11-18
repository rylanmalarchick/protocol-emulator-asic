"""Assembler for the ISA v0 proposal.

Syntax, one statement per line:

    ; comment
    .equ NAME expr          define a constant (a -D define wins)
    label:                  name the next instruction
    op a, b [, +delay]      operands are separated by commas

Operands: registers r0 to r7, pin names (OUT0, IO3, IN1), pin modes (IN, PP,
OD), labels, and expressions with + - * / // % ^ & | << >> and parentheses.
A delay is in clock cycles and can have a fraction: `+CLK / BAUD`.
"""

from __future__ import annotations

import ast
import operator
import re

from . import v0

_LABEL = re.compile(r"^([A-Za-z_]\w*):\s*(.*)$")
_NAME = re.compile(r"^[A-Za-z_]\w*$")
_REG = re.compile(r"^r([0-7])$")
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.BitXor: operator.xor, ast.BitAnd: operator.and_,
        ast.BitOr: operator.or_, ast.LShift: operator.lshift, ast.RShift: operator.rshift}
MAX_DELAY = 1 << 15  # cycles; the RTL wrap-safe compare needs deadlines below 2^15


class AsmError(Exception):
    def __init__(self, line_no: int, msg: str):
        super().__init__(f"line {line_no}: {msg}")
        self.line_no = line_no


def evaluate(text: str, names: dict[str, float], line_no: int) -> float:
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError:
        raise AsmError(line_no, f"bad expression {text!r}") from None

    def ev(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise AsmError(line_no, f"unknown name {n.id!r}")
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise AsmError(line_no, f"unsupported expression {text!r}")

    try:
        return ev(tree.body)
    except (TypeError, ZeroDivisionError) as e:
        raise AsmError(line_no, f"cannot evaluate {text!r}: {e}") from None


def _int(text, names, line_no) -> int:
    v = evaluate(text, names, line_no)
    if v != int(v):
        raise AsmError(line_no, f"{text!r} is not an integer ({v})")
    return int(v)


def _delay(text, names, line_no) -> int:
    v = evaluate(text, names, line_no)
    if not 0 <= v < MAX_DELAY:
        raise AsmError(line_no, f"delay {v} is outside 0 to {MAX_DELAY} cycles")
    return round(v * v0.ONE)


def assemble(src: str, defines: dict[str, float] | None = None) -> list[v0.Instr]:
    consts: dict[str, float] = {**v0.MODES, **(defines or {})}
    labels: dict[str, int] = {}
    stmts: list[tuple[int, str, list[str]]] = []

    for line_no, raw in enumerate(src.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        m = _LABEL.match(line)
        if m:
            name, line = m.group(1), m.group(2).strip()
            if name in labels or name in consts or name in v0.PINS:
                raise AsmError(line_no, f"{name!r} is already defined")
            labels[name] = len(stmts)
        if not line:
            continue
        op, _, rest = line.partition(" ")
        args = [a.strip() for a in rest.split(",")] if rest.strip() else []
        if op == ".equ":
            parts = rest.split(None, 1)
            if len(parts) != 2 or not _NAME.match(parts[0]):
                raise AsmError(line_no, "use: .equ NAME expr")
            if parts[0] not in consts:
                consts[parts[0]] = evaluate(parts[1], consts, line_no)
            continue
        op = op.lower()
        if op not in v0.OPS:
            raise AsmError(line_no, f"unknown instruction {op!r}")
        kinds = v0.OPS[op]
        if op in v0.TIMED and len(args) == len(kinds) + 1:
            if not args[-1].startswith("+"):
                raise AsmError(line_no, "a delay operand starts with +")
        elif len(args) != len(kinds):
            raise AsmError(line_no, f"{op} takes {len(kinds)} operand(s)")
        stmts.append((line_no, op, args))

    prog = []
    for line_no, op, args in stmts:
        kinds = v0.OPS[op]
        vals = []
        for kind, arg in zip(kinds, args):
            if kind == "r":
                m = _REG.match(arg)
                if not m:
                    raise AsmError(line_no, f"{arg!r} is not a register")
                vals.append(int(m.group(1)))
            elif kind == "p":
                if arg not in v0.PINS:
                    raise AsmError(line_no, f"{arg!r} is not a pin")
                vals.append(v0.PINS[arg])
            elif kind == "l":
                if arg not in labels:
                    raise AsmError(line_no, f"unknown label {arg!r}")
                vals.append(labels[arg])
            elif kind == "i":
                vals.append(_int(arg, consts, line_no))
            else:  # d
                vals.append(_delay(arg, consts, line_no))
        d = _delay(args[-1][1:], consts, line_no) if len(args) > len(kinds) else 0
        vals += [0] * (2 - len(vals))
        prog.append(v0.Instr(op, vals[0], vals[1], d, line_no))
    return prog
