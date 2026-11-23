"""Binary encoding for the v0 learning core (learn/v0core).

One 49-bit word per instruction. A wide word keeps the decoder simple; a
compact encoding is an open ISA question.

    [48:44] op   [43:39] A   [38:23] B   [22:0] D

A is a register or a pin. B is an immediate, a label, a register, a pin, a
pin mode, or a level. D is a delay in cycles with v0.FRAC fraction bits.
"""

from __future__ import annotations

from . import v0

OPCODES = ["halt", "ldi", "mov", "addi", "andi", "xori", "shli", "shri",
           "djnz", "bz", "bnz", "jmp", "dly", "sync", "waitt", "wait",
           "cfg", "set", "put", "puth", "get", "geth", "pull", "push"]
OP = {name: i for i, name in enumerate(OPCODES)}
WIDTH = 49


def encode_one(ins: v0.Instr) -> int:
    a, b, d = ins.a, ins.b, ins.d
    if ins.op == "jmp":  # the target goes in B, like the other branches
        a, b = 0, ins.a
    elif ins.op == "dly":  # the delay goes in D, like the timed actions
        a, d = 0, ins.a
    if not 0 <= a < 32:
        raise ValueError(f"line {ins.line}: A field {a} does not fit in 5 bits")
    if not 0 <= b < 1 << 16:
        raise ValueError(f"line {ins.line}: B field {b} does not fit in 16 bits")
    if not 0 <= d < 1 << 23:
        raise ValueError(f"line {ins.line}: D field {d} does not fit in 23 bits")
    return OP[ins.op] << 44 | a << 39 | b << 23 | d


def encode(prog: list[v0.Instr]) -> list[int]:
    return [encode_one(i) for i in prog]


def decode_one(w: int) -> v0.Instr:
    op = OPCODES[w >> 44 & 0x1F]
    a, b, d = w >> 39 & 0x1F, w >> 23 & 0xFFFF, w & 0x7FFFFF
    if op == "jmp":
        return v0.Instr(op, b, 0, 0)
    if op == "dly":
        return v0.Instr(op, d, 0, 0)
    return v0.Instr(op, a, b, d)
