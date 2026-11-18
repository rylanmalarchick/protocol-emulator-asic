# Host tools

Python tools for the program side: a reference model, an assembler, and a
deadline checker.

The model follows the Probe A machine in `lean/ProtoEmu/Probe/UartTx.lean`.
It is a probe, not the ISA. When `docs/isa.md` lands, these tools follow it.

| File | Contents |
|---|---|
| `protoemu/model.py` | Reference model. One rule per instruction, the same as the Lean `exec`. |
| `protoemu/asm.py` | Assembler: text to an instruction list. |
| `protoemu/check.py` | Deadline checker. Runs the program for each input byte and reports the slack of every timed action. |
| `programs/uart_tx.s` | UART 8N1 transmit. The same program as `uartTx` in the Lean file. |
| `tests/` | pytest tests. Exact values come from the Lean theorem `final_state`. |

## Run

```sh
cd sw
python -m pytest                                  # tests
python -m protoemu.check programs/uart_tx.s       # check at 115200 baud
python -m protoemu.check programs/uart_tx.s -D P=3   # fails: the loop is 4 cycles
```

Use the venv from `test/requirements.txt`. The tools need only the Python
standard library. The tests need pytest.

## Limits

The checker runs the model once per input byte. This method is exact only
because the Probe A machine has no data-dependent timing. When the ISA gets
data-dependent branches, the checker must bound every path.
