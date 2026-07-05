#!/bin/bash
A=/mnt/fpe/Libero
mountpoint -q /mnt/fpe || { mkdir -p /mnt/fpe; mount -t 9p -o trans=virtio,version=9p2000.L,msize=524288 fpehost /mnt/fpe; }
export ACTEL_SW_DIR=$A LD_LIBRARY_PATH=$A/lib64:$A/lib:$A/libfp
export QT_QPA_PLATFORM_PLUGIN_PATH=$A/lib64/plugins/platforms QT_QPA_PLATFORM=xcb DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/rtroot
mkdir -p /tmp/rtroot; chmod 700 /tmp/rtroot
pkill -9 FPExpress_bin 2>/dev/null; pkill Xvfb 2>/dev/null; sleep 1
Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 & sleep 4
cp /mnt/fpe/top.job /tmp/top.job; rm -rf /tmp/fpeproj; mkdir -p /tmp/fpeproj
printf "create_job_project -job_project_location {/tmp/fpeproj} -job_file {/tmp/top.job}\nrefresh_prg_list\nrun_selected_actions\nclose_project\n" > /tmp/prog.tcl
rm -f /tmp/prog.out
setsid bash -c "$A/bin64/FPExpress_bin SCRIPT:/tmp/prog.tcl LOGFILE:/tmp/prog.log CONSOLE_MODE:brief > /tmp/prog.out 2>&1" </dev/null >/dev/null 2>&1 &
disown; sleep 3; echo "LAUNCHED pid=$(pgrep FPExpress_bin | head -1)"
