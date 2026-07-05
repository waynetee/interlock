#!/bin/bash
rm -f /mnt/fpe/prog.out
setsid bash /mnt/fpe/do_program.sh > /mnt/fpe/prog.out 2>&1 < /dev/null &
disown
sleep 8
pgrep FPExpress_bin >/dev/null && echo LAUNCHED_OK || echo "warming up"
