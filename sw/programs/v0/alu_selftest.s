; ALU and timeline self-test. Pushes one result per instruction to the host.
; The chip test compares the results and the cycles with the model.
; Pins: OUT5 pulses once when the test ends.

    ldi r0, 0x1234
    addi r0, 0xF00F         ; 0x0243 (wraps)
    push r0
    mov r1, r0
    xori r1, 0xFFFF         ; 0xFDBC
    push r1
    shli r1, 4              ; 0xDBC0
    push r1
    shri r1, 9              ; 0x006D
    push r1
    andi r1, 0x0F           ; 0x000D
    push r1
    ldi r2, 3
loop:
    addi r3, 7
    djnz r2, loop           ; r3 = 21
    push r3
    bz r2, zero             ; taken
    push r0                 ; skipped
zero:
    cfg OUT5, PP0
    sync
    dly 100
    set OUT5, 1, +5         ; 100 cycles after sync
    set OUT5, 0, +50
    waitt                   ; stalls to floor(T), 50 cycles after the last set
    pull r4                 ; empty: 0x100
    push r4
    halt
