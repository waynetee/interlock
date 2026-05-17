#!/bin/bash
# Pre-build sanity checks for the interlock gateware build environment.
# Run on a fresh checkout or after a reboot — confirms that:
#   - Libero is on PATH (via wrappers in /usr/local/bin/)
#   - lmgrd is running on port 1702
#   - the system controller libstdc++ patches are in place
#   - the IP-vault has the pinned versions (or can fetch them)
# Does NOT build — that's build.sh's job.

PASS=0
FAIL=0

check() {
    local name="$1"
    local cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        echo "  ✓ $name"
        PASS=$((PASS+1))
    else
        echo "  ✗ $name"
        FAIL=$((FAIL+1))
    fi
}

echo "=== Libero wrappers ==="
check "libero in PATH"   "command -v libero"
check "acttclsh in PATH" "command -v acttclsh"
check "libero wrapper invokes /usr/bin/xvfb-run" "grep -q xvfb-run \$(command -v libero)"

echo
echo "=== License daemon ==="
check "lmgrd listening on port 1702" "ss -tln | grep -q ':1702 '"

echo
echo "=== libstdc++ patches (system glibcxx instead of bundled) ==="
check "Libero's bundled libstdc++ disabled"      "test -f /usr/local/microchip/Libero_SoC_v2024.2/Libero/lib64/rhel/libstdc++.so.6.disabled"
check "SynplifyPro's bundled libstdc++ disabled" "test -f /usr/local/microchip/Libero_SoC_v2024.2/SynplifyPro/linux_a_64/lib/libstdc++.so.6.disabled"

echo
echo "=== Pinned IP cores (vault state) ==="
check "PF_IOD_CDR 2.4.110 in vault"      "test -f /root/.actel/vault/Components/Actel/SystemBuilder/PF_IOD_CDR/2.4.110/fs/p0f0/PF_IOD_CDR.xml"
check "PF_IOD_CDR_CCC 2.1.111 in vault"  "test -f /root/.actel/vault/Components/Actel/SystemBuilder/PF_IOD_CDR_CCC/2.1.111/fs/p0f0/PF_IOD_CDR_CCC.xml"
check "PF_INIT_MONITOR 2.0.307 in vault" "test -f /root/.actel/vault/Components/Actel/SgCore/PF_INIT_MONITOR/2.0.307/fs/p0f0/PF_INIT_MONITOR.xml"
check "CORETSE 3.2.119 in vault"         "test -f /root/.actel/vault/Components/Actel/DirectCore/CORETSE/3.2.119/fs/p0f0/CORETSE.xml"
echo "  (missing cores will be auto-fetched by script.tcl's download_core block)"

echo
echo "=== Swap (P&R uses ~1 GB) ==="
SWAP_GB=$(free -g | awk '/^Swap:/ {print $2}')
if [[ "$SWAP_GB" -ge 4 ]]; then
    echo "  ✓ Swap: ${SWAP_GB} GiB"
    PASS=$((PASS+1))
else
    echo "  ✗ Swap: ${SWAP_GB} GiB (recommend >= 4 GiB; see /root/fpga/CLAUDE.md)"
    FAIL=$((FAIL+1))
fi

echo
echo "=== Summary ==="
echo "  $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && echo "Ready to build. Run ./build.sh"
exit "$FAIL"
