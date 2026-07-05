#!/bin/bash
# Guest-side: bind ftdi_sio to the FlashPro FTDI so its UART appears as ttyUSBn,
# then read the fabric telemetry. NOTE: ftdi_sio grabs the JTAG interface too —
# rmmod ftdi_sio before any reflash.
modprobe ftdi_sio 2>/dev/null
echo "1514 2008" > /sys/bus/usb-serial/drivers/ftdi_sio/new_id 2>/dev/null
sleep 1
echo "ttyUSB devices:"; ls /dev/ttyUSB* 2>/dev/null
for d in /dev/ttyUSB0 /dev/ttyUSB1 /dev/ttyUSB2 /dev/ttyUSB3; do
  [ -e "$d" ] || continue
  stty -F "$d" 115200 raw -echo 2>/dev/null
  echo "=== $d (3s) ==="
  timeout 3 cat "$d" | head -c 400 | tr -c '[:print:]\n' '.'
  echo
done
