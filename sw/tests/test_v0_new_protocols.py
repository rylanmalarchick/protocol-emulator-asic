"""Protocols the v0 proposal was not designed for: WS2812 and 1-Wire.

Both use only the instructions that UART, SPI, and I2C needed, plus the PP0
pin mode. The device models and checks come from the data sheets.
"""

from pathlib import Path

import pytest

from protoemu import peers, spec, v0, v0asm, v0check

PROGS = Path(__file__).parent.parent / "programs" / "v0"
CLK = 50_000_000


def src(name):
    return (PROGS / name).read_text()


def run(p, peer_list=(), host_in=(), max_cycles=400_000):
    sim = v0.Sim(p, peer_list, host_in)
    sim.run(max_cycles, tail=10)
    return sim


# ---- WS2812 ----

LEDS = [(0xFF, 0x00, 0x00), (0x00, 0x80, 0x01), (0x12, 0x34, 0x56)]  # (G, R, B)


def test_ws2812_chain():
    data = [c for led in LEDS for c in led]
    sim = run(v0asm.assemble(src("ws2812.s")), host_in=data)
    frames, bad = spec.decode_ws2812(sim.levels("OUT4"), CLK)
    assert bad == []
    assert frames == [[g << 16 | r << 8 | b for g, r, b in LEDS]]
    assert not sim.core.late


def test_ws2812_exact_pulse_widths():
    sim = run(v0asm.assemble(src("ws2812.s")), host_in=[0b10000000])
    lv = sim.levels("OUT4")
    rises = [t for t in range(1, len(lv)) if lv[t] and not lv[t - 1]]
    highs = [next(t for t in range(r, len(lv)) if not lv[t]) - r for r in rises]
    assert highs == [40] + [20] * 7  # a 1 is 0.8 us, a 0 is 0.4 us
    # The 62.5-cycle period alternates 62 and 63 cycles: no drift.
    assert [b - a for a, b in zip(rises, rises[1:])] == [62, 63, 62, 63, 62, 63, 62]


def test_ws2812_needs_a_line_that_starts_low():
    # With PP the line starts high, so the first rising edge is lost.
    p = v0asm.assemble(src("ws2812.s").replace("cfg OUT4, PP0", "cfg OUT4, PP"))
    sim = run(p, host_in=[0xFF, 0x00, 0x00])
    frames, bad = spec.decode_ws2812(sim.levels("OUT4"), CLK)
    assert bad != []


def test_ws2812_static_proof():
    assert v0check.analyze(v0asm.assemble(src("ws2812.s"))).ok


# ---- 1-Wire ----

def crc8_maxim(data):
    """Dallas/Maxim CRC-8, polynomial x^8 + x^5 + x^4 + 1, LSB first."""
    crc = 0
    for byte in data:
        for k in range(8):
            mix = (crc ^ (byte >> k)) & 1
            crc >>= 1
            if mix:
                crc ^= 0x8C
    return crc


ROM7 = [0x28, 0xFF, 0x4C, 0x60, 0x91, 0x16, 0x05]  # family 0x28 (DS18B20) + serial
ROM = ROM7 + [crc8_maxim(ROM7)]


def test_onewire_read_rom():
    dev = peers.OneWireDevice("IO2", ROM)
    sim = run(v0asm.assemble(src("onewire_read_rom.s")), [dev])
    assert dev.commands == [0x33]
    assert dev.violations == []
    assert sim.core.host_out == ROM
    assert crc8_maxim(sim.core.host_out[:7]) == sim.core.host_out[7]
    assert not sim.core.late


def test_onewire_no_device():
    sim = run(v0asm.assemble(src("onewire_read_rom.s")))
    assert sim.core.host_out == [512]


def test_onewire_static_proof():
    assert v0check.analyze(v0asm.assemble(src("onewire_read_rom.s"))).ok


@pytest.mark.parametrize("name", ["uart_tx.s", "uart_rx.s", "spi_ctrl.s", "i2c_write.s",
                                  "ws2812.s", "onewire_read_rom.s"])
def test_every_program_is_proved(name):
    res = v0check.analyze(v0asm.assemble(src(name)))
    assert res.ok, [f for f in res.findings if f.worst_slack < 0]
