"""Peer devices for the v0 simulator, written from the protocol standards.

These models know nothing about the firmware. They play the other end of
the bus: a UART transmitter, an SPI target, an I2C target.
"""

from __future__ import annotations

from . import v0


class UartSource(v0.Peer):
    """Sends bytes as UART 8N1 frames on an input pin. Each bit is `bit`
    cycles long (a float). `gap` idle bits follow each stop bit."""

    def __init__(self, pin: str, data: list[int], bit: float, start: int, gap: float = 0):
        self.pin = v0.PINS[pin]
        self.edges: list[tuple[int, int]] = []  # (cycle, level), in order
        t = float(start)
        for b in data:
            bits = [0] + [(b >> k) & 1 for k in range(8)] + [1]
            for k, lvl in enumerate(bits):
                self.edges.append((round(t + k * bit), lvl))
            t += (10 + gap) * bit
        self.level = 1
        self.i = 0

    def drives(self):
        return {self.pin: self.level}

    def observe(self, t, levels):
        while self.i < len(self.edges) and self.edges[self.i][0] <= t + 1:
            self.level = self.edges[self.i][1]
            self.i += 1


class SpiTarget(v0.Peer):
    """SPI target in mode 0 to 3. Shifts MSB first. Receives on `mosi`,
    sends `tx` bytes on `miso` (an input pin of the chip)."""

    def __init__(self, mode: int, sck: str, mosi: str, cs: str, miso: str, tx: list[int]):
        self.cpol, self.cpha = mode >> 1, mode & 1
        self.sck, self.mosi, self.cs, self.miso = (v0.PINS[p] for p in (sck, mosi, cs, miso))
        self.tx = list(tx)
        self.rx: list[int] = []
        self.prev_sck = self.cpol
        self.prev_cs = 1
        self.shift_in = self.nin = 0
        self.out_byte = self.nout = 0
        self.level = 1

    def drives(self):
        return {self.miso: self.level}

    def _present(self):
        if self.nout == 0:
            self.out_byte = self.tx.pop(0) if self.tx else 0xFF
        self.level = (self.out_byte >> (7 - self.nout)) & 1
        self.nout = (self.nout + 1) % 8

    def _sample(self, levels):
        self.shift_in = (self.shift_in << 1) | levels[self.mosi]
        self.nin += 1
        if self.nin == 8:
            self.rx.append(self.shift_in)
            self.shift_in = self.nin = 0

    def observe(self, t, levels):
        cs, sck = levels[self.cs], levels[self.sck]
        if self.prev_cs == 1 and cs == 0:
            self.shift_in = self.nin = self.nout = 0
            if self.cpha == 0:
                self._present()
        elif cs == 0 and sck != self.prev_sck:
            leading = sck != self.cpol
            if leading == (self.cpha == 0):
                self._sample(levels)
            else:
                self._present()
        self.prev_cs, self.prev_sck = cs, sck


class I2cTarget(v0.Peer):
    """I2C target with a 7-bit address. Receives a write and ACKs each byte.
    After each ACK it holds SCL low for `stretch` cycles (clock stretching)."""

    def __init__(self, addr: int, sda: str, scl: str, stretch: int = 0):
        self.addr = addr
        self.sda, self.scl = v0.PINS[sda], v0.PINS[scl]
        self.stretch = stretch
        self.state = "idle"
        self.received: list[int] = []
        self.addressed = False
        self.prev = (1, 1)
        self.bits = self.shift = 0
        self.acking = False
        self.sda_out = self.scl_out = 1
        self.hold_until = -1

    def drives(self):
        return {self.sda: self.sda_out, self.scl: self.scl_out}

    def observe(self, t, levels):
        sda, scl = levels[self.sda], levels[self.scl]
        psda, pscl = self.prev
        if pscl and scl and psda and not sda:  # START
            self.state, self.bits, self.shift, self.acking = "addr", 0, 0, False
            self.sda_out = 1
        elif pscl and scl and not psda and sda:  # STOP
            self.state, self.sda_out = "idle", 1
        elif self.state in ("addr", "data"):
            if not pscl and scl and not self.acking:
                self.shift = (self.shift << 1) | sda
                self.bits += 1
            elif pscl and not scl:
                if self.acking:
                    self.sda_out, self.acking = 1, False
                    self.bits = self.shift = 0
                    if self.stretch:
                        self.scl_out, self.hold_until = 0, t + self.stretch
                elif self.bits == 8:
                    ack = True
                    if self.state == "addr":
                        if self.shift >> 1 == self.addr and self.shift & 1 == 0:
                            self.state, self.addressed = "data", True
                        else:
                            self.state, ack = "ignore", False
                    else:
                        self.received.append(self.shift)
                    if ack:
                        self.sda_out, self.acking = 0, True
        if self.scl_out == 0 and t + 1 >= self.hold_until:
            self.scl_out = 1
        self.prev = (sda, scl)


class OneWireDevice(v0.Peer):
    """1-Wire device, standard speed, from the DS18B20 data sheet. Answers a
    reset with a presence pulse. Takes an 8-bit command LSB first. On READ ROM
    (0x33) it sends its 8 ROM bytes, LSB first. It also records timing
    violations of the bus controller."""

    def __init__(self, pin: str, rom: list[int], clk_hz: float = 50e6):
        self.pin = v0.PINS[pin]
        self.us = clk_hz / 1e6
        self.rom_bits = [(b >> k) & 1 for b in rom for k in range(8)]
        self.state = "idle"
        self.prev = 1
        self.fall = -1
        self.presence_end = -1
        self.cmd = self.nbits = 0
        self.sample_at = -1
        self.pull: list[tuple[int, int]] = []  # [from, until) cycles the device pulls low
        self.out = 1
        self.commands: list[int] = []
        self.violations: list[str] = []

    def drives(self):
        return {self.pin: self.out}

    def _low_for(self, start: float, length: float):
        self.pull.append((round(start), round(start + length)))

    def observe(self, t, levels):
        lv = levels[self.pin]
        us = self.us
        if self.prev == 1 and lv == 0:  # falling edge: a slot or a reset starts
            self.fall = t
            if self.state == "cmd":
                self.sample_at = round(t + 30 * us)  # samples 15 to 60 us in
            elif self.state == "send":
                if self.nbits < len(self.rom_bits) and self.rom_bits[self.nbits] == 0:
                    self._low_for(t + 1, 30 * us)
                self.nbits += 1
        elif self.prev == 0 and lv == 1 and self.fall >= 0:  # rising edge
            low = (t - self.fall) / us
            if low >= 480:  # reset: presence pulse 30 us later, 120 us long
                self.state, self.cmd, self.nbits = "presence", 0, 0
                self._low_for(t + 30 * us, 120 * us)
                self.presence_end = round(t + 150 * us)
            elif self.state == "cmd" and not (1 <= low <= 15 or 60 <= low <= 120):
                self.violations.append(f"write slot low {low:.1f} us at cycle {self.fall}")
        if self.state == "presence" and t >= self.presence_end:
            self.state = "cmd"  # its own presence pulse is not a slot
        if t == self.sample_at and self.state == "cmd":
            self.cmd |= lv << self.nbits
            self.nbits += 1
            if self.nbits == 8:
                self.commands.append(self.cmd)
                self.state = "send" if self.cmd == 0x33 else "idle"
                self.nbits = 0
        self.out = 0 if any(a <= t + 1 < b for a, b in self.pull) else 1
        self.prev = lv
