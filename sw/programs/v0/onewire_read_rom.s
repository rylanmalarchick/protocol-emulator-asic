; 1-Wire READ ROM, standard speed. Sends a reset, checks for a presence
; pulse, sends command 0x33, and reads the 8-byte ROM code (family code,
; 48-bit serial, CRC). Pushes the 8 bytes, LSB-first bits, byte 0 first.
; If no device answers the reset, pushes NODEV.
; Pins: IO2 = the 1-Wire line, open drain with a pull-up.
;
; Slot times follow Maxim application note 126 (standard speed).
; A write slot puts the data bit on the line 6 us after it goes low: a 1
; releases the line, a 0 keeps it low to 60 us. No branch on the data.

.equ CLK 50000000
.equ US CLK / 1000000       ; 50 cycles per microsecond
.equ NODEV 512
.equ READ_ROM 0x33

    cfg IO2, OD
    sync
    dly 10 * US
    set IO2, 0, +480 * US   ; reset pulse (H)
    set IO2, 1, +70 * US    ; release, then sample presence at 70 us (I)
    ldi r4, 0
    geth r4, IO2, +410 * US ; 0 means a device answered (J: rest of the slot)
    bnz r4, nodev
    ldi r0, READ_ROM
    ldi r2, 8
wbit:
    set IO2, 0, +6 * US     ; slot start (A)
    put IO2, r0, +54 * US   ; 1: release now; 0: stay low to 60 us (C)
    set IO2, 1, +10 * US    ; release, recovery (D)
    djnz r2, wbit
    ldi r3, 8
rbyte:
    ldi r0, 0
    ldi r2, 8
rbit:
    set IO2, 0, +6 * US     ; slot start (A)
    set IO2, 1, +9 * US     ; release (E)
    get r0, IO2, +55 * US   ; sample 15 us into the slot, LSB first (F)
    djnz r2, rbit
    push r0
    djnz r3, rbyte
    halt
nodev:
    ldi r5, NODEV
    push r5
    halt
