"""Binary encoding for the v0 core (src/v0core.v).

One 38-bit word per instruction. The loader sends it as 5 bytes, MSB first;
the top 2 bits are 0.

    [37:33] op   [32:28] A   [27:23] Bs   [22:0] D     timed actions
    [37:33] op   [32:28] A   [27:16] 0    [15:0] B     all other ops

A is a register or a pin. A timed action (set, put, puth, get, geth) has a
short B (a level, a register, or a pin) and a delay D in cycles with v0.FRAC
fraction bits. Other ops have a 16-bit B: an immediate, a label, a register,
a pin mode, or a level. `jmp` puts its target in B. `dly` puts its delay in D.
"""

from __future__ import annotations

from . import v0

OPCODES = ["halt", "ldi", "mov", "addi", "andi", "xori", "shli", "shri",
           "djnz", "bz", "bnz", "jmp", "dly", "sync", "waitt", "wait",
           "cfg", "set", "put", "puth", "get", "geth", "pull", "push"]
OP = {name: i for i, name in enumerate(OPCODES)}
WIDTH = 38
NBYTES = 5
DEPTH = 64  # program memory words in the chip


class EncodeError(ValueError):
    pass


def _check(cond: bool, ins: v0.Instr, msg: str) -> None:
    if not cond:
        raise EncodeError(f"line {ins.line}: {ins.op}: {msg}")


def encode_one(ins: v0.Instr) -> int:
    a, b, d = ins.a, ins.b, ins.d
    if ins.op == "jmp":
        a, b = 0, ins.a
    elif ins.op == "dly":
        a, d = 0, ins.a
    _check(0 <= a < 32, ins, f"A field {a} does not fit in 5 bits")
    _check(0 <= d < 1 << 23, ins, f"delay {d / v0.ONE} does not fit in 23 bits")
    word = OP[ins.op] << 33 | a << 28
    if ins.op in v0.TIMED:
        _check(0 <= b < 32, ins, f"B field {b} does not fit in 5 bits")
        return word | b << 23 | d
    _check(0 <= b < 1 << 16, ins, f"B field {b} does not fit in 16 bits")
    if ins.op == "dly":
        return word | d
    _check(d == 0, ins, "only timed actions and dly take a delay")
    return word | b


def encode(prog: list[v0.Instr], depth: int = DEPTH) -> list[int]:
    if len(prog) > depth:
        raise EncodeError(f"program has {len(prog)} words; the chip holds {depth}")
    return [encode_one(i) for i in prog]


def decode_one(w: int) -> v0.Instr:
    op = OPCODES[w >> 33 & 0x1F]
    a = w >> 28 & 0x1F
    if op in v0.TIMED:
        return v0.Instr(op, a, w >> 23 & 0x1F, w & 0x7FFFFF)
    if op == "jmp":
        return v0.Instr(op, w & 0xFFFF, 0, 0)
    if op == "dly":
        return v0.Instr(op, w & 0x7FFFFF, 0, 0)
    return v0.Instr(op, a, w & 0xFFFF, 0)


def to_bytes(words: list[int]) -> bytes:
    return b"".join(w.to_bytes(NBYTES, "big") for w in words)
