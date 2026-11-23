"""Host side of the chip's load port (an SPI target, mode 0, MSB first).

Each function returns the bytes of one frame (CS low to CS high). The first
byte the chip returns in every frame is the status byte. See docs/info.md.
"""

from __future__ import annotations

from . import v0enc

CMD_NOP = 0x00
CMD_PROG_WRITE = 0x01
CMD_HOST_WRITE = 0x02
CMD_HOST_READ = 0x03
CMD_PROG_READ = 0x04
CMD_CLEAR = 0x05

# Status byte bits.
ST_RUN = 1 << 0
ST_HALTED = 1 << 1
ST_LATE = 1 << 2
ST_HOUT = 1 << 3  # the host-out FIFO has data
ST_HIN_FULL = 1 << 4
ST_OVERFLOW = 1 << 5  # a FIFO dropped data
ST_ID_MASK, ST_ID = 0xC0, 0x80


def prog_write(words: list[int], addr: int = 0) -> bytes:
    return bytes([CMD_PROG_WRITE, addr]) + v0enc.to_bytes(words)


def prog_read(n: int, addr: int = 0) -> bytes:
    return bytes([CMD_PROG_READ, addr]) + bytes(n * v0enc.NBYTES)


def host_write(data: bytes) -> bytes:
    return bytes([CMD_HOST_WRITE]) + bytes(data)


def host_read(n: int) -> bytes:
    """Read up to n entries. Each entry is 3 bytes: valid flag, high, low."""
    return bytes([CMD_HOST_READ]) + bytes(3 * n)


def parse_host_read(reply: bytes) -> list[int]:
    out = []
    for k in range(1, len(reply) - 2, 3):
        if reply[k] & 1:
            out.append(reply[k + 1] << 8 | reply[k + 2])
    return out


def parse_prog_read(reply: bytes) -> list[int]:
    body = reply[2:]
    n = v0enc.NBYTES
    return [int.from_bytes(body[k:k + n], "big") for k in range(0, len(body) - n + 1, n)]
