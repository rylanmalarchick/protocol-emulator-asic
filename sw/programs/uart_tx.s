; UART 8N1 transmit of the byte in r0. The same program as uartTx in
; lean/ProtoEmu/Probe/UartTx.lean. P is the bit period in cycles.
; 115200 baud at 50 MHz: P = 434.

.equ P 434

    ldi1 8          ; eight data bits
    pinlow          ; start bit at T
    dly P
bit:
    put             ; data bit, LSB first
    dly P
    djnz bit
    pinhigh         ; stop bit
    dly P
    waitt           ; hold the stop bit for one full period
    halt
