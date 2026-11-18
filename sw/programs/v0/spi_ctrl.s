; SPI controller, modes 0 to 3, MSB first. Full duplex: sends each host
; byte on MOSI and pushes the byte read on MISO. CS stays low for the whole
; transfer.
; Pins: OUT1 = SCK, OUT2 = MOSI, OUT3 = CS, IN1 = MISO.
;
; One loop serves all four modes. Each bit has two SCK edges, A then B:
;   CPHA 0: A is the trailing edge (no change for bit 0), B is the leading edge.
;   CPHA 1: A is the leading edge, B is the trailing edge.
; MOSI changes 1 cycle after A. MISO is sampled 1 cycle after B. The target
; samples at the B edge and changes MISO at the A edge, so both are stable.

.equ HALF 25                ; half SCK period in cycles: 1 MHz
.equ CPOL 0
.equ CPHA 0
.equ A CPOL ^ CPHA
.equ B 1 - A

    cfg OUT1, PP
    cfg OUT2, PP
    cfg OUT3, PP            ; CS idles high
    sync
    set OUT1, CPOL, +HALF   ; SCK idle level
    set OUT3, 0, +HALF      ; CS low, first bit half a period later
next:
    pull r0
    mov r1, r0
    andi r1, 256
    bnz r1, done
    ldi r2, 8
    ldi r4, 0
bit:
    set OUT1, A, +1
    puth OUT2, r0, +(HALF - 1)
    set OUT1, B, +1
    geth r4, IN1, +(HALF - 1)
    djnz r2, bit
    push r4
    jmp next
done:
    set OUT1, CPOL, +HALF   ; last trailing edge for CPHA 0, no change for CPHA 1
    set OUT3, 1, +HALF      ; CS high
    waitt
    halt
