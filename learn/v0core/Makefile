# cocotb: the v0 learning core against the Python model. Run: make -B
SIM ?= icarus
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES = $(PWD)/v0core.v
TOPLEVEL = v0core
COCOTB_TEST_MODULES = test_v0core
export PYTHONPATH := $(PWD)/../../sw:$(PYTHONPATH)
include $(shell cocotb-config --makefiles)/Makefile.sim
