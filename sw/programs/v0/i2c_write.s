; I2C controller write. The host FIFO holds the address byte (addr << 1 | 0)
; and then the data bytes. Sends START, the bytes, and STOP. On a NACK it
; pushes NACK to the host and sends STOP.
; Pins: IO0 = SDA, IO1 = SCL, both open drain with pull-ups.
;
; SCL is low for 55% of the period and high for 45%. Fast mode needs
; tLOW >= 1.3 us of a 2.5 us period, so a 50% duty cycle fails at 400 kHz.
; SDA changes at the middle of SCL low. After each SCL release, `wait` puts T
; on the cycle that SCL really goes high, so a target that stretches the
; clock moves the rest of the timeline with it.

.equ CLK 50000000
.equ FSCL 100000
.equ P CLK / FSCL           ; SCL period in cycles
.equ LOW P * 11 / 20
.equ HIGH P - LOW
.equ HL LOW / 2             ; SDA changes this long after SCL falls
.equ HH HIGH / 2            ; ACK sample point after SCL rises
.equ NACK 256

    cfg IO0, OD
    cfg IO1, OD
    sync
    dly HIGH                ; bus free time
    set IO0, 0, +HIGH       ; START: SDA low while SCL high
    set IO1, 0, +HL         ; SCL low
next:
    pull r0
    mov r1, r0
    andi r1, 256
    bnz r1, stop
    ldi r2, 8
bit:
    puth IO0, r0, +(LOW - HL)   ; data bit, MSB first
    set IO1, 1              ; release SCL
    wait IO1, 1             ; T := SCL high
    dly HIGH
    set IO1, 0, +HL         ; SCL low
    djnz r2, bit
    ldi r4, 0
    set IO0, 1, +(LOW - HL)     ; release SDA for the ACK bit
    set IO1, 1
    wait IO1, 1
    dly HH
    geth r4, IO0, +(HIGH - HH)  ; ACK bit: 0 is ACK
    set IO1, 0, +HL
    bz r4, next
    ldi r5, NACK
    push r5
stop:
    set IO0, 0, +(LOW - HL)     ; SDA low
    set IO1, 1              ; release SCL
    wait IO1, 1
    dly HIGH
    set IO0, 1, +HIGH       ; STOP: SDA high while SCL high
    waitt
    halt
