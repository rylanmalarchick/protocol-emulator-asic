# cocotb test for the timed_out learning block. Run: make -B
SIM ?= icarus
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES = $(PWD)/timed_out.v
TOPLEVEL = timed_out
COCOTB_TEST_MODULES = test_timed_out
include $(shell cocotb-config --makefiles)/Makefile.sim

# Formal proof of the `ifdef FORMAL properties.
formal:
	sby -f timed_out.sby
