#!/bin/bash
exec qemu-system-x86_64 -m 8192 -smp 8 \
  -drive file=/fpe/jammy.img,format=qcow2,if=virtio \
  -drive file=/fpe/seed.iso,format=raw,if=virtio \
  -netdev user,id=n0,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=n0 \
  -device qemu-xhci,id=xhci -device usb-host,vendorid=0x1514,productid=0x2008 \
  -virtfs local,path=/fpe,mount_tag=fpehost,security_model=none,id=fpe \
  -display none -serial file:/fpe/console.log
