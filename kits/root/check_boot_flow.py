"""Model the boot script's gates/fallbacks locally; never runs U-Boot or ADB."""
import json
from pathlib import Path
import subprocess
import tempfile

BASE = Path(__file__).resolve().parent
script = json.loads((BASE / 'experiment-plan.json').read_text())['candidate']
model = r'''
gate_present=yes
image_loaded=no
header_saved=no
bootargs=stock
bootconfig=stock
boot_part=boot_b
active_slot=_b
loadaddr_kernel=0x3000000
dtb_mem_addr=0x1000000
[[ $mode == wrong_load_address ]] && loadaddr_kernel=0x4000000
setenv() { local task_key=$1; shift; printf -v "$task_key" '%s' "$*"; }
usb() { [[ $mode != usb_missing ]]; }
fatsize() { [[ $mode != gate_missing && $gate_present == yes ]]; }
fatrm() {
  [[ $mode == gate_remove_failed ]] && return 1
  [[ $mode != gate_removal_unverified ]] && gate_present=no
  printf 'GATE_REMOVE\n'
  return 0
}
run() {
  case "$1" in
    get_os_type) os_type=kernel;;
    storage_param|common_dtb_load) return 0;;
    storeboot_base) printf 'STOCK_BOOT\n'; exit 0;;
    *) printf 'UNEXPECTED_RUN\n'; exit 40;;
  esac
}
get_system_as_root_mode() { system_mode=0; }
fdt() { return 0; }
imgread() { printf 'STOCK_IMAGE_READ\n'; [[ $mode != imgread_failed ]]; }
itest.l() {
  case "$1" in
    0x3000000) return 0;;
    0x4000000) return 1;;
    '*0xbf621d24') [[ $mode != wrong_stock_code ]];;
    '*0xbf7c047c') [[ $mode != init_boot_used ]];;
    '*0x3000000'|'*0x3000004'|'*0x3000008'|'*0x300000c'|'*0x3000028')
      [[ $image_loaded == yes && $mode != bad_image_header ]];;
    *) printf 'UNEXPECTED_READ\n'; exit 41;;
  esac
}
load() {
  [[ $gate_present == no ]] || exit 42
  [[ $3 == 0x3000000 ]] || exit 43
  printf 'LOAD_PATCH\n'
  [[ $mode == load_failed ]] && return 1
  image_loaded=yes
  filesize=dc4000
  [[ $mode == wrong_image_size ]] && filesize=1000
  return 0
}
dcache() { [[ $mode != cache_flush_failed ]]; }
icache() { return 0; }
fatwrite() {
  [[ $image_loaded == yes && $gate_present == no ]] || exit 44
  [[ $mode == header_save_failed ]] && return 1
  header_saved=yes
  printf 'HEADER_SAVED\n'
}
bootm() {
  [[ $image_loaded == yes && $header_saved == yes && $gate_present == no ]] || exit 45
  if [[ $mode == boot_returned ]]; then printf 'BOOT_RETURNED\n'; return 1; fi
  printf 'PATCHED_BOOT\n'
  exit 0
}
reset() {
  [[ $gate_present == no ]] || exit 46
  printf 'RESET_WITH_GATE_CONSUMED\n'
  exit 0
}
'''
cases = {
    'success': 'PATCHED_BOOT',
    'usb_missing': 'STOCK_BOOT', 'gate_missing': 'STOCK_BOOT',
    'gate_remove_failed': 'STOCK_BOOT', 'gate_removal_unverified': 'STOCK_BOOT',
    'imgread_failed': 'RESET_WITH_GATE_CONSUMED',
    'wrong_load_address': 'RESET_WITH_GATE_CONSUMED',
    'wrong_stock_code': 'RESET_WITH_GATE_CONSUMED', 'init_boot_used': 'RESET_WITH_GATE_CONSUMED',
    'load_failed': 'RESET_WITH_GATE_CONSUMED', 'wrong_image_size': 'RESET_WITH_GATE_CONSUMED',
    'bad_image_header': 'RESET_WITH_GATE_CONSUMED', 'cache_flush_failed': 'RESET_WITH_GATE_CONSUMED',
    'header_save_failed': 'RESET_WITH_GATE_CONSUMED', 'boot_returned': 'RESET_WITH_GATE_CONSUMED',
}
results = []
with tempfile.TemporaryDirectory(prefix='onn26-script-model-') as directory:
    for mode, expected in cases.items():
        completed = subprocess.run(['bash', '-c', 'mode=' + mode + '\n' + model + '\n' + script],
                                   cwd=directory, capture_output=True, text=True, timeout=5)
        trace = completed.stdout.splitlines()
        assert completed.returncode == 0, (mode, completed.returncode, completed.stderr, trace)
        assert trace[-1] == expected, (mode, trace, expected)
        if expected == 'STOCK_BOOT':
            assert 'LOAD_PATCH' not in trace and 'STOCK_IMAGE_READ' not in trace
        if 'LOAD_PATCH' in trace:
            assert trace.index('GATE_REMOVE') < trace.index('LOAD_PATCH')
        if mode in ['wrong_load_address', 'wrong_stock_code', 'init_boot_used']:
            assert 'LOAD_PATCH' not in trace
        results.append({'mode': mode, 'outcome': expected, 'passed': True})
report = {'modeled_cases': results, 'all_passed': True, 'device_contacted': False,
          'limitation': 'Bash command stubs check script ordering and fallback logic. They do not prove U-Boot transport, image verification or Android root behavior.'}
(BASE / 'boot-flow-check.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': len(results), 'device_contacted': False}))
