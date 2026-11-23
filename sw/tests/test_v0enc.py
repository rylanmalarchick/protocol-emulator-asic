"""The chip encoding: every program fits, and decode inverts encode."""

from pathlib import Path

import pytest

from protoemu import host, v0, v0asm, v0enc

PROGS = sorted((Path(__file__).resolve().parents[1] / "programs" / "v0").glob("*.s"))


@pytest.mark.parametrize("path", PROGS, ids=lambda p: p.name)
def test_round_trip(path):
    prog = v0asm.assemble(path.read_text())
    words = v0enc.encode(prog)
    assert all(0 <= w < 1 << v0enc.WIDTH for w in words)
    for ins, w in zip(prog, words):
        back = v0enc.decode_one(w)
        assert (back.op, back.a, back.b, back.d) == (ins.op, ins.a, ins.b, ins.d)


def test_program_too_long():
    with pytest.raises(v0enc.EncodeError):
        v0enc.encode([v0.Instr("halt")] * (v0enc.DEPTH + 1))


def test_timed_b_field_limit():
    with pytest.raises(v0enc.EncodeError):
        v0enc.encode_one(v0.Instr("set", 0, 32, 0))


def test_delay_only_on_timed_ops():
    with pytest.raises(v0enc.EncodeError):
        v0enc.encode_one(v0.Instr("ldi", 0, 5, 256))


def test_host_frames():
    words = [0x3F_FFFF_FFFF, 1]
    frame = host.prog_write(words, addr=7)
    assert frame == bytes([1, 7, 0x3F, 0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0, 1])
    assert host.parse_host_read(bytes([0x80, 1, 0x01, 0x00, 0, 0, 0])) == [0x100]
