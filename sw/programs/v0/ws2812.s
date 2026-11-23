; WS2812 LED chain driver. Sends each host byte MSB first (the host sends
; G, R, B for each LED), then holds the line low to latch the colors.
; Pins: OUT4 = DIN of the first LED.
;
; Each bit is 1.25 us. It starts high. At 0.4 us the pin takes the data bit:
; a 0 goes low here, a 1 stays high. At 0.8 us the pin goes low. So a 0 is
; high for 0.4 us and a 1 for 0.8 us, with no branch on the data.

.equ CLK 50000000
.equ T0H CLK * 0.4e-6       ; 20 cycles
.equ T1H CLK * 0.8e-6       ; 40 cycles
.equ TBIT CLK * 1.25e-6     ; 62.5 cycles
.equ RESET CLK * 300e-6     ; latch: low for more than 280 us

    cfg OUT4, PP0           ; the line idles low
    sync
    dly 16
next:
    pull r0
    mov r1, r0
    andi r1, 256
    bnz r1, done
    ldi r2, 8
bit:
    set OUT4, 1, +T0H
    puth OUT4, r0, +(T1H - T0H)
    set OUT4, 0, +(TBIT - T1H)
    djnz r2, bit
    jmp next
done:
    dly RESET
    waitt                   ; hold low until the LEDs latch
    halt
