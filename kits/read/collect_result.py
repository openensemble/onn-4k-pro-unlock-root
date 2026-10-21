"""Validate the actual one-use stock secure-state read receipts."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import struct

BASE = Path(__file__).resolve().parent
ALLOWED = set(range(0x640, 0x6ac)) | set(range(0x6b0, 0x738))

def collect_local(session):
    plan = json.loads((BASE / 'experiment-plan.json').read_text())
    original = (BASE / plan['payload_file']).read_bytes()
    result = {'time_utc': datetime.now(timezone.utc).isoformat(), 'secure_state_read_proven': False,
              'root_proven': False, 'permanent_unlock_proven': False,
              'captures': {name: (session / name).exists() for name in plan['new_usb_files']}}
    before = session / 'ONNBEG23.BIN'
    result['pre_entry_checkpoint_matches_input'] = before.exists() and before.read_bytes() == original
    for filename, key in [('ONNST23.TXT', 'early_markers'), ('ONNCAP23.TXT', 'markers')]:
        path = session / filename
        env = {}
        if path.exists():
            env = dict(line.split('=', 1) for line in path.read_bytes().rstrip(b'\0').decode(errors='replace').splitlines() if '=' in line)
        result[key] = {k: v for k, v in env.items() if k.startswith('onn23_')}
    returned = session / 'ONNRET23.BIN'
    if returned.exists():
        data = returned.read_bytes()
        result['returned_bytes'] = len(data)
        result['returned_sha256'] = hashlib.sha256(data).hexdigest()
        if len(data) == len(original) == 0x840:
            result['only_expected_bytes_changed'] = {i for i, (a, b) in enumerate(zip(original, data)) if a != b} <= ALLOWED
            result['probe_code_unchanged'] = data[64:0x640] == original[64:0x640]
            result['marker'] = data[0x640:0x644].decode(errors='replace')
            result['status'] = struct.unpack_from('<I', data, 0x644)[0]
            context = dict(zip(['x18', 'lr', 'sp', 'current_el', 'sctlr_el2', 'daif', 'relocaddr', 'getter', 'primary_reader', 'tee_reader', 'original_par'], struct.unpack_from('<11Q', data, 0x648)))
            result['context'] = {k: hex(v) for k, v in context.items()}
            rc, lock, calls = struct.unpack_from('<3I', data, 0x6a0)
            result.update({'getter_success': rc, 'lock_state': lock, 'getter_call_count': calls})
            after_sp, after_x18 = struct.unpack_from('<2Q', data, 0x6b0)
            after_sctlr = struct.unpack_from('<Q', data, 0x730)[0]
            result['call_context_preserved'] = (after_sp, after_x18, after_sctlr) == (context['sp'], context['x18'], context['sctlr_el2'])
            result['prefixes'] = {}
            for address, before_offset, after_offset in [(0xbf621d24, 0x6c0, 0x6d0), (0xbf64bcc8, 0x6e0, 0x6f0), (0xbf6702f4, 0x710, 0x720)]:
                pre, post = data[before_offset:before_offset+16].hex(), data[after_offset:after_offset+16].hex()
                result['prefixes'][hex(address)] = {'before': pre, 'after': post, 'matches_stock': pre == post == plan['prefixes'][hex(address)]}
            result['stock_reader_prefixes_unchanged'] = all(v['matches_stock'] for v in result['prefixes'].values())
            result['native_completion_proven'] = bool(result['pre_entry_checkpoint_matches_input'] and result['only_expected_bytes_changed'] and result['probe_code_unchanged']
                and result['marker'] == 'ON23' and context['current_el'] == 8 and context['x18'] == 0xb96055c0
                and context['lr'] == 0xbf662828 and context['sp'] % 16 == 0 and context['getter'] == 0xbf621d24
                and result['markers'].get('onn23_go') == 'returned_zero')
            result['secure_state_read_proven'] = bool(result['native_completion_proven'] and result['status'] == 2
                and rc == 1 and lock in (0, 1) and calls == 1 and result['call_context_preserved'] and result['stock_reader_prefixes_unchanged'])
    if result['secure_state_read_proven']:
        result['state_name'] = 'locked' if result['lock_state'] else 'unlocked'
        conclusion = f"The unmodified stock secure-state getter returned success and state {result['lock_state']} ({result['state_name']}). No persistent unlock was attempted."
    elif result.get('native_completion_proven'):
        conclusion = f"Native probe returned status {result['status']}; a valid secure-state read is not proven."
    elif result['pre_entry_checkpoint_matches_input']:
        conclusion = 'Before-entry checkpoint present; native completion is not proven. Inspect captures before further tests.'
    else:
        conclusion = 'No matching before-entry checkpoint; inspect setup captures.'
    result['conclusion'] = conclusion
    (session / 'capture-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
