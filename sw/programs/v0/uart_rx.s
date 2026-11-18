; UART 8N1 receive of COUNT bytes. Pushes each byte to the host FIFO.
; Pins: IN0 = RX.
; `wait` puts T on the start edge. Every sample after it is relative to that
; edge, so the receiver follows the sender's clock, not its own.

.equ CLK 50000000
.equ BAUD 115200
.equ BIT CLK / BAUD
.equ COUNT 4
.equ FRAMING_ERROR 512

    ldi r3, COUNT
frame:
    wait IN0, 0             ; T := the start edge
    ldi r0, 0
    ldi r2, 8
    dly BIT + BIT / 2       ; middle of data bit 0
bit:
    get r0, IN0, +BIT       ; sample, LSB first
    djnz r2, bit
    ldi r4, 0
    geth r4, IN0            ; stop bit, at its middle
    bz r4, ferr
    push r0
    djnz r3, frame
    halt
ferr:
    ldi r5, FRAMING_ERROR
    push r5
    halt
