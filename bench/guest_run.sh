#!/bin/bash
sudo modprobe 9pnet_virtio 2>/dev/null
sudo mkdir -p /mnt/fpe
sudo mount -t 9p -o trans=virtio,version=9p2000.L,msize=524288 fpehost /mnt/fpe 2>/dev/null || sudo mount -t 9p -o trans=virtio fpehost /mnt/fpe
echo MOUNT_RC=$? ; ls /mnt/fpe | head
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq >/dev/null 2>&1
sudo apt-get install -y --no-install-recommends xvfb libxcb1 libx11-6 libx11-xcb1 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 libxcb-util1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libfreetype6 libxrender1 libxext6 libxi6 libsm6 libice6 libglib2.0-0 libdbus-1-3 libgl1 libnss3 libnspr4 libgssapi-krb5-2 libpci3 libpulse0 libpulse-mainloop-glib0 libxml2 libxslt1.1 libasound2 libwebp7 fonts-dejavu-core libxcursor1 libxdamage1 >/dev/null 2>&1
echo DEPS_DONE
A=/mnt/fpe/Libero
export ACTEL_SW_DIR=$A LD_LIBRARY_PATH=$A/lib64:$A/lib:$A/libfp
export QT_QPA_PLATFORM_PLUGIN_PATH=$A/lib64/plugins/platforms QT_QPA_PLATFORM=xcb DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/rt
mkdir -p /tmp/rt; chmod 700 /tmp/rt
Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 & sleep 4
cp /mnt/fpe/top.job /tmp/top.job; rm -rf /tmp/fpeproj; mkdir -p /tmp/fpeproj
cat > /tmp/scan.tcl <<TCL
create_job_project -job_project_location {/tmp/fpeproj} -job_file {/tmp/top.job}
refresh_prg_list
scan_chain_prg -name {E20093HAS6}
close_project
TCL
echo ===GUEST_SCAN===
timeout 500 $A/bin64/FPExpress_bin SCRIPT:/tmp/scan.tcl CONSOLE_MODE:brief 2>&1 | grep -aiE "instruction register|idcode|scan chain|found|fatal|FAILED|succeeded|FlashPro5|doesn" | grep -aviE "qt.qpa|FP6 programmers|NDDF"
echo ===GUEST_END===
