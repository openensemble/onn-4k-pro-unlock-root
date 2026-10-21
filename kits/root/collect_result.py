from pathlib import Path
import json
BASE = Path(__file__).resolve().parent

def collect_local(session):
    plan = json.loads((BASE / 'experiment-plan.json').read_text())
    receipt = json.loads((session / 'roundtrip.json').read_text())
    expected = (BASE / plan['payload_file']).read_bytes()[:4096]
    path = session / 'ONNHD26.BIN'
    header_ok = path.exists() and path.read_bytes() == expected
    marker = receipt.get('properties', {}).get(plan['marker_property'])
    result = {'patched_header_saved_before_boot': header_ok, 'android_marker': marker,
      'android_booted_via_candidate': bool(header_ok and marker == plan['expected_marker'] and receipt.get('android_returned')),
      'original_startup_restored_and_verified': receipt.get('original_startup_restored_and_verified', False),
      'root_proven': False, 'firmware_partition_flash': False, 'lock_state_write': False}
    result['conclusion'] = 'Patched header and Android marker match; a separate successful su -c id is required for root proof.' if result['android_booted_via_candidate'] else 'Patched Android boot is not proven; inspect receipts before further testing.'
    (session / 'capture-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
