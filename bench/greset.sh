mountpoint -q /mnt/fpe || mount -t 9p -o trans=virtio,version=9p2000.L,msize=524288 fpehost /mnt/fpe 2>/dev/null
A=/mnt/fpe/Libero
export ACTEL_SW_DIR=$A LD_LIBRARY_PATH=$A/lib64:$A/lib:$A/libfp
export QT_QPA_PLATFORM_PLUGIN_PATH=$A/lib64/plugins/platforms QT_QPA_PLATFORM=xcb DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/rtroot
mkdir -p /tmp/rtroot; chmod 700 /tmp/rtroot
pkill Xvfb 2>/dev/null; sleep 1
Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 & sleep 4
cp /mnt/fpe/top.job /tmp/top.job; rm -rf /tmp/fpeproj; mkdir -p /tmp/fpeproj
cat > /tmp/devinfo.tcl <<'TCL'
create_job_project -job_project_location {/tmp/fpeproj} -job_file {/tmp/top.job}
refresh_prg_list
set_programming_action -name {MPF300TS} -action DEVICE_INFO
run_selected_actions
close_project
TCL
echo ===DEVINFO_RUN===
timeout 300 $A/bin64/FPExpress_bin SCRIPT:/tmp/devinfo.tcl LOGFILE:/tmp/devinfo.log CONSOLE_MODE:brief 2>&1 \
  | grep -aiE "action|device_info|idcode|passed|failed|error|succeed|unknown|invalid|not a valid|isc" | grep -aviE "qt.qpa|NDDF" | tail -25
echo "===EXIT===" ; tail -8 /tmp/devinfo.log 2>/dev/null
