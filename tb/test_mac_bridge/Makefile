# cocotb testbench for mac_bridge.sv
TOPLEVEL_LANG    = verilog
TOPLEVEL         = mac_bridge
MODULE           = test_mac_bridge

REPO_ROOT       := $(realpath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
VERILOG_SOURCES  = $(REPO_ROOT)/gateware/src/src_hdl/mac_bridge.sv

# Smaller FIFO depth for fast simulation (overrides the synthesis default of 11).
# Verilator uses -G, iverilog uses -P (different syntax for the same thing).
ifeq ($(SIM),verilator)
    COMPILE_ARGS += -GDEPTH_LOG2=6
else
    COMPILE_ARGS += -Pmac_bridge.DEPTH_LOG2=6
endif

include $(REPO_ROOT)/tb/common.mk
