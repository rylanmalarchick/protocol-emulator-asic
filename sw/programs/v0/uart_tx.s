; UART 8N1 transmit. Sends each byte from the host FIFO, back to back.
; Pins: OUT0 = TX.
; BIT is a fraction of a cycle exact to 1/256: T keeps the fraction, so the
; edges do not drift over a long message.

.equ CLK 50000000
.equ BAUD 115200
.equ BIT CLK / BAUD

    cfg OUT0, PP
    sync
    set OUT0, 1, +16        ; idle high, first frame 16 cycles later
next:
    pull r0
    mov r1, r0
    andi r1, 256
    bnz r1, done            ; FIFO empty
    ldi r2, 8
    set OUT0, 0, +BIT       ; start bit
bit:
    put OUT0, r0, +BIT      ; data bits, LSB first
    djnz r2, bit
    set OUT0, 1, +BIT       ; stop bit
    jmp next
done:
    waitt                   ; hold the last stop bit for its full period
    halt
