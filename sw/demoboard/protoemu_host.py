"""Load and run programs on the chip from the Tiny Tapeout demo board.

MicroPython, for the RP2040 on the demo board. It bit-bangs the load port
(an SPI target, mode 0) on ui_in[2:0] and uo_out[0]. The chip oversamples
SCK, so any slow SCK works.

Untested on hardware. The SPI frames are the same as in test/test.py
(Chip.xfer), which the cocotb tests check on the RTL. The DemoBoard calls
follow the tt-micropython-firmware SDK; check them against the SDK version
on your board.

Use: assemble on a PC, then copy the frame bytes to the board.

    # PC
    from protoemu import host, v0asm, v0enc
    prog = v0asm.assemble(open("programs/v0/uart_tx.s").read(), {"BAUD": 115200})
    print(list(host.prog_write(v0enc.encode(prog))))

    # board
    import protoemu_host as ph
    chip = ph.Chip(ph.demoboard())
    chip.frame(bytes(PROG_FRAME))       # PROG_WRITE
    chip.frame(bytes([2]) + b"Hello")   # HOST_WRITE
    chip.run(True)
    print(hex(chip.status()))
"""

CS, SCK, MOSI, RUN = 0, 1, 2, 3


def demoboard(clock_hz=50_000_000):
    from ttboard.demoboard import DemoBoard  # noqa: PLC0415 (board only)

    tt = DemoBoard.get()
    tt.shuttle.tt_um_rylanmalarchick_protoemu.enable()
    tt.clock_project_PWM(clock_hz)
    return tt


class Chip:
    def __init__(self, tt):
        self.tt = tt
        self.ui = 1 << CS  # CS high, SCK low, RUN low
        self._put()

    def _put(self):
        self.tt.ui_in.value = self.ui

    def _bit(self, n, v):
        self.ui = (self.ui | (1 << n)) if v else (self.ui & ~(1 << n))
        self._put()

    def frame(self, data):
        """One SPI frame. Returns the bytes the chip sent."""
        reply = bytearray()
        self._bit(CS, 0)
        for byte in data:
            got = 0
            for k in range(7, -1, -1):
                self._bit(MOSI, (byte >> k) & 1)
                got = (got << 1) | (int(self.tt.uo_out.value) & 1)
                self._bit(SCK, 1)
                self._bit(SCK, 0)
            reply.append(got)
        self._bit(CS, 1)
        return bytes(reply)

    def status(self):
        return self.frame(b"\x00")[0]

    def run(self, on):
        self._bit(RUN, on)

    def read_host(self, n):
        r = self.frame(bytes([3]) + bytes(3 * n))
        return [r[k + 1] << 8 | r[k + 2] for k in range(1, len(r) - 2, 3) if r[k] & 1]
