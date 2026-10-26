# AGENTS.md

Rules for every coding agent (Claude Code, Codex, Cursor, OpenCode) and every
person who works in this repo. These rules bind. If a rule blocks the task,
stop and ask. Do not work around the rule.

## Project

A programmable protocol emulator for the Jane Street protocol emulator ASIC
competition. The design is a Tiny Tapeout project on IHP 130 nm CMOS5L
(`sg13cmos5l`), 6x4 tiles, 50 MHz. The submission deadline is 2027-01-18.

Required: UART, SPI, and I2C run as firmware, and the chip is reprogrammable
after fabrication. Stretch: low-speed USB, 10 Mbit Ethernet.

The core idea is a timestamped-event ISA. Instructions schedule pin edges at
absolute times and capture input edges with timestamps. An off-chip assembler
checks every protocol deadline before it emits a program.

## Layout

| Path | Contents |
|---|---|
| `src/` | RTL. List each file in `info.yaml` `source_files` and in `test/Makefile` `PROJECT_SOURCES`. |
| `test/` | cocotb testbench (`tb.v`, `test.py`). |
| `docs/info.md` | Tiny Tapeout datasheet. |
| `docs/isa.md` | ISA spec. The contract between the chip side and the program side. |
| `info.yaml` | Tiny Tapeout metadata: top module, tiles, clock, pinout. |
| `notes/` | Private notes. A separate git repo. This repo ignores it. |
| `tt/`, `runs/` | Hardening tools and outputs. Generated. Never commit. |

## Session start

1. If `notes/` exists, read `notes/plan.txt` and the last 40 lines of
   `notes/log.txt`.
2. Run `git status` and `git log --oneline -5`.
3. Work in a git worktree on a branch. Never edit on `main`.

## Commands

```sh
verify                     # local gate: cocotb RTL sim. Prints PASS, FAIL, or NO GATE.
cd test && make -B         # the same RTL sim by hand
cd test && make -B GATES=yes   # gate-level sim. Needs PDK_ROOT and gate_level_netlist.v.
```

If cocotb fails with `GLIBC_2.36 not found`, put `/usr/bin` before the OSS CAD
Suite in `PATH`. The OSS CAD Suite `vvp` cannot load the system libpython.

Hardening (RTL to GDS) follows the
[Tiny Tapeout local hardening guide](https://www.tinytapeout.com/guides/local-hardening/).
Pin the versions to `TinyTapeout/tt-gds-action@ihp-cmos5l`. A run that skips
`Magic.DRC` is for iteration only. It is not sign-off.

CI (GitHub Actions):

| Workflow | Runs | Sign-off for |
|---|---|---|
| `test.yaml` | RTL sim | behavior |
| `gds.yaml` | hardening, `gl_test`, precheck, viewer | the chip |
| `docs.yaml` | datasheet build | docs |

If only the viewer job fails, do not rerun that job by itself. Run
`gh workflow run gds.yaml`.

## Workflow

1. Never push to `main`. Open a PR. The other person reviews it.
2. One commit, one concern. The subject is imperative and under 72 characters.
3. Before you report work as done, run `verify`. Report its last line exactly.
4. Report CI status exactly. "11 skipped" is not "passing". A local run is not CI.
5. After a decision or a measured result, append an entry to `notes/log.txt`.
   Use the format in that file. Do not edit old entries.

## ISA contract

`docs/isa.md` is the interface between the RTL and the assembler.

1. A change to `docs/isa.md` needs a PR that both people approve.
2. Land the spec change first, or in the same PR as the RTL and assembler
   changes. `main` never has RTL and assembler that disagree with the spec.
3. Give every instruction an encoding, a cycle count, and a cocotb test.

## RTL

1. Start every file with `` `default_nettype none ``.
2. Use one clock, `clk`. Reset is synchronous from `rst_n`. Reset every
   register.
3. Synchronize every asynchronous input (`ui_in`, `uio_in`) with two
   flip-flops before use.
4. No latches. No `initial` blocks in synthesizable RTL. ASIC registers have
   no power-on value.
5. Assign every output: `uo_out`, `uio_out`, `uio_oe`.
6. All memories go through one wrapper module. The wrapper selects the SRAM
   macro (ASIC), block RAM (FPGA), or a behavioral model (sim).
7. If a change adds state or logic, read the cell count from the hardening
   stats. Put the before and after numbers in the PR description.
8. Do not change `top_module`, `tiles`, or `clock_hz` in `info.yaml` without
   agreement from both people and a log entry.

## Tests

1. Every RTL module gets a cocotb test. A feature lands with its test.
2. A new test must fail for the right reason before the fix makes it pass.
3. This design has deterministic timing. Assert exact cycle counts and exact
   pin values. Do not assert ranges.
4. Bound every wait. Use `ClockCycles` or `with_timeout`. A test must not hang.
5. For protocol checks, prefer an independent bus model (for example
   `cocotbext-uart`) over a model written in the same change as the RTL.
6. Never edit a test, an expected value, or `.verify` to turn FAIL into PASS.
   Never skip a test silently.

## Python

1. No blanket `except Exception`. Catch the specific error, or let it raise.
2. No unbounded loops. Bound the loop in its header.
3. Pin tool versions in `test/requirements.txt`.

## Writing

READMEs, docs, PR text, and commit messages use Simplified Technical English:
active voice, one idea per sentence, short common words, no marketing
adjectives. State what a thing is and how to run it.

## Never

1. Never commit `notes/`, `tt/`, `runs/`, secrets, host names, or IP addresses.
   This repo is public.
2. Never quote private notes in a public file, a PR, or an issue.
3. Never add a self-hosted runner or a `pull_request_target` workflow. A fork
   PR could run code on the runner host.
4. Never force-push a shared branch. Never bypass hooks or branch protection.
