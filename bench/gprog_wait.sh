#!/bin/bash
for i in $(seq 1 60); do
  grep -qaiE "Chain programming (PASSED|FAILED)|PROGRAM (PASSED|FAILED)" /tmp/prog.out 2>/dev/null && break
  pgrep FPExpress_bin >/dev/null || { echo PROC_EXITED; break; }
  sleep 30
done
echo "=== prog.out tail ==="; grep -aiE "Executing action PROGRAM|Chain programming|PASSED|FAILED|Scan Chain|IDCODE|Error" /tmp/prog.out 2>/dev/null | grep -aviE "NDDF|cyusb|qt.qpa" | tail -18
