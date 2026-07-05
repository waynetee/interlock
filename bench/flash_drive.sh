#!/bin/bash
# Drive the FPGA flash across the namespace chain:
#   host(claude) -> docker exec box64test -> ssh VM:2222 (ubuntu) -> Libero FPExpress
# The VM's /mnt/fpe is the live 9p mirror of host ~/fpe, so ~/fpe/top.job IS what gets
# flashed. gprog_launch.sh runs FPExpress detached in the VM; gprog_wait.sh polls.
VMSSH='sshpass -p ubuntu ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 ubuntu@127.0.0.1'
case "${1:-}" in
  verify) docker exec box64test bash -lc "$VMSSH 'md5sum /mnt/fpe/top.job; ls -la /mnt/fpe/top.job'" ;;
  launch) docker exec box64test bash -lc "$VMSSH 'sudo bash /mnt/fpe/gprog_launch.sh'" ;;
  wait)   docker exec box64test bash -lc "$VMSSH 'sudo bash /mnt/fpe/gprog_wait.sh'" ;;
  tail)   docker exec box64test bash -lc "$VMSSH 'sudo tail -20 /tmp/prog.out 2>/dev/null; echo ===PROC===; pgrep -a FPExpress_bin || echo NO_FPEXPRESS'" ;;
  *) echo "usage: flash_drive.sh {verify|launch|wait|tail}" ;;
esac
