"""Protocol checks on pin traces, written from the standards.

A trace is a list of pin levels, one per clock cycle.
"""

from __future__ import annotations

import math


def edges(levels: list[int]) -> list[tuple[int, int]]:
    """(cycle, new level) for each change."""
    return [(t, levels[t]) for t in range(1, len(levels)) if levels[t] != levels[t - 1]]


def decode_uart(levels: list[int], bit: float) -> list[int | None]:
    """UART 8N1 decode: sample at the middle of each bit. None marks a frame
    with a bad stop bit."""
    out: list[int | None] = []
    t, n = 1, len(levels)
    for _ in range(n):  # bound: each pass moves t forward
        while t < n and not (levels[t - 1] == 1 and levels[t] == 0):
            t += 1
        stop = t + round(9.5 * bit)
        if stop >= n:
            break
        b = sum(levels[t + round((k + 1.5) * bit)] << k for k in range(8))
        out.append(b if levels[stop] == 1 else None)
        t = stop
    return out


def uart_edge_error(levels: list[int], bit: float) -> float:
    """Largest distance, in cycles, from an edge to the ideal bit grid that
    starts at the first edge. Back-to-back frames share one grid."""
    es = edges(levels)
    if not es:
        return 0.0
    t0 = es[0][0]
    return max(abs(t - t0 - round((t - t0) / bit) * bit) for t, _ in es)


# I2C timing limits in seconds: standard mode (100 kHz) and fast mode (400 kHz).
I2C_LIMITS = {
    "sm": {"tLOW": 4.7e-6, "tHIGH": 4.0e-6, "tSU_DAT": 250e-9, "tHD_STA": 4.0e-6, "tSU_STO": 4.0e-6},
    "fm": {"tLOW": 1.3e-6, "tHIGH": 0.6e-6, "tSU_DAT": 100e-9, "tHD_STA": 0.6e-6, "tSU_STO": 0.6e-6},
}


def check_i2c(sda: list[int], scl: list[int], clk_hz: float, mode: str = "sm"):
    """Check one transaction (START to STOP). Returns (bytes, violations).
    bytes is a list of (byte, ack) where ack is True for a 0 (ACK) bit."""
    lim = {k: math.ceil(v * clk_hz) for k, v in I2C_LIMITS[mode].items()}
    n = len(sda)
    starts = [t for t in range(1, n) if scl[t] and scl[t - 1] and sda[t - 1] and not sda[t]]
    stops = [t for t in range(1, n) if scl[t] and scl[t - 1] and not sda[t - 1] and sda[t]]
    if not starts or not stops:
        return [], ["no START or no STOP"]
    start, stop = starts[0], stops[-1]
    bad = []
    rises = [t for t in range(start + 1, stop) if scl[t] and not scl[t - 1]]
    falls = [t for t in range(start + 1, stop) if not scl[t] and scl[t - 1]]
    sda_ch = [t for t in range(start + 1, stop) if sda[t] != sda[t - 1]]

    for t in sda_ch:
        if scl[t] or scl[t - 1]:
            bad.append(f"SDA changed while SCL high at cycle {t}")
    if falls and falls[0] - start < lim["tHD_STA"]:
        bad.append(f"tHD;STA {falls[0] - start} < {lim['tHD_STA']}")
    for r in rises:
        f = next((f for f in falls if f > r), None)
        if f is not None and f - r < lim["tHIGH"]:
            bad.append(f"tHIGH {f - r} < {lim['tHIGH']} at cycle {r}")
        pf = max((f for f in falls if f < r), default=None)
        if pf is not None and r - pf < lim["tLOW"]:
            bad.append(f"tLOW {r - pf} < {lim['tLOW']} at cycle {pf}")
        last = max((s for s in sda_ch if s < r), default=None)
        if last is not None and (pf is None or last > pf) and r - last < lim["tSU_DAT"]:
            bad.append(f"tSU;DAT {r - last} < {lim['tSU_DAT']} at cycle {r}")
    if rises and stop - rises[-1] < lim["tSU_STO"]:
        bad.append(f"tSU;STO {stop - rises[-1]} < {lim['tSU_STO']}")

    # Data bits: SCL rising edges that have a falling edge before STOP.
    bits = [sda[r] for r in rises if any(f > r for f in falls)]
    data = [(sum(b << (7 - k) for k, b in enumerate(bits[i:i + 8])), bits[i + 8] == 0)
            for i in range(0, len(bits) - 8, 9)]
    return data, bad


# WS2812B data sheet: high times 0.4 us and 0.8 us, each +-150 ns. A bit is
# 1.25 us +-600 ns. Low for more than 280 us latches the colors.
WS2812 = {"t0h": (0.25e-6, 0.55e-6), "t1h": (0.65e-6, 0.95e-6),
          "bit": (0.65e-6, 1.85e-6), "reset": 280e-6}


def decode_ws2812(levels: list[int], clk_hz: float):
    """Returns (frames, violations). A frame is the list of 24-bit words sent
    before one latch. Each word is G << 16 | R << 8 | B."""
    def cyc(s):
        return s * clk_hz
    rises = [t for t in range(1, len(levels)) if levels[t] and not levels[t - 1]]
    frames, bits, bad = [], [], []
    for i, r in enumerate(rises):
        f = next((t for t in range(r, len(levels)) if not levels[t]), len(levels))
        high = f - r
        if cyc(WS2812["t0h"][0]) <= high <= cyc(WS2812["t0h"][1]):
            bits.append(0)
        elif cyc(WS2812["t1h"][0]) <= high <= cyc(WS2812["t1h"][1]):
            bits.append(1)
        else:
            bad.append(f"high {high} cycles at {r}")
        nxt = rises[i + 1] if i + 1 < len(rises) else None
        low_end = nxt if nxt is not None else len(levels)
        if low_end - f > cyc(WS2812["reset"]) or nxt is None:
            if nxt is None and low_end - f <= cyc(WS2812["reset"]):
                bad.append("no latch after the last bit")
            if len(bits) % 24:
                bad.append(f"{len(bits)} bits is not a whole number of LEDs")
            frames.append([sum(b << (23 - k) for k, b in enumerate(bits[j:j + 24]))
                           for j in range(0, len(bits) - 23, 24)])
            bits = []
        elif not cyc(WS2812["bit"][0]) <= nxt - r <= cyc(WS2812["bit"][1]):
            bad.append(f"bit period {nxt - r} cycles at {r}")
    return frames, bad
