# cocotb conformance test for the interlock Core, checked against the Python
# golden model in ../../prototype (wire.py + interlock.py).
#
# The Core RTL is not written yet — this harness is its contract. Point
# VERILOG_SOURCES at the Core + its SHA-256 blocks once they exist, then `make`.
TOPLEVEL_LANG = verilog
SIM ?= verilator                       # or: SIM=questa / SIM=modelsim
VERILOG_SOURCES = $(PWD)/../src/interlock_core.sv   # TODO: Core RTL + SHA-256 blocks
TOPLEVEL = interlock_core
MODULE   = test_interlock_core
export PYTHONPATH := $(PWD)/../../prototype:$(PYTHONPATH)
include $(shell cocotb-config --makefiles)/Makefile.sim
