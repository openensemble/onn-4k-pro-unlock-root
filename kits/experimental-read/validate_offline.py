"""Exercise the probe with the captured getter/reader code and a modeled TEE."""
from pathlib import Path
import json
import struct
import sys
import tempfile

BASE = Path(__file__).resolve().parent
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
import unicorn.arm64_const as r
from collect_result import collect_local, ALLOWED

ENTRY, RETURN, GD, SP = 0x3000040, 0xbf662828, 0xb96055c0, 0xb96040f0
GETTER, READER = 0xbf621d24, 0xbf6702f4
plan = json.loads((BASE / 'experiment-plan.json').read_text())
image = (BASE / plan['payload_file']).read_bytes()
fixture = json.loads((BASE / 'emulator-fixture.json').read_text())
binary = bytearray(fixture['allocation_size'])
for address, fragment in fixture['chunks'].items():
    offset = int(address, 16) - int(fixture['base'], 16)
    binary[offset:offset + len(bytes.fromhex(fragment))] = bytes.fromhex(fragment)
binary = bytes(binary)
cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
instructions = {}
for ins in cs.disasm(image[64:0x640], ENTRY):
    instructions[ins.address] = (ins.mnemonic, ins.op_str)
    assert ins.mnemonic not in ('bl', 'stp', 'ldp', 'dc', 'ic', 'tlbi', 'smc')
    if ins.mnemonic == 'blr':
        assert ins.op_str == 'x4'
    if ins.mnemonic == 'ret':
        break
for begin, end in [(GETTER, 0xbf621df4), (READER, 0xbf670370)]:
    for ins in cs.disasm(binary[begin-0xbf616000:end-0xbf616000], begin):
        instructions[ins.address] = (ins.mnemonic, ins.op_str)

cases = []
captures = {}
for name, changes, expected_status in [
    ('locked', {}, 2), ('unlocked', {'tee_state': 0}, 2),
    ('tee_read_rejected', {'tee_error': 2}, 4),
    ('backend_unavailable', {'available': 0}, 4),
    ('avb_init_failed', {'initialized': 0}, 4),
    ('wrong_el', {'currentel': 4}, 3),
    ('unaligned_stack', {'sp': SP + 8}, 3),
    ('wrong_gd', {'gd': GD + 16}, 3),
    ('wrong_relocation', {'reloc': 0xbf617000}, 3),
    ('getter_prefix_mismatch', {'bad_prefix': GETTER}, 9),
    ('primary_reader_prefix_mismatch', {'bad_prefix': 0xbf64bcc8}, 9),
    ('tee_reader_prefix_mismatch', {'bad_prefix': READER}, 9),
    ('post_call_code_change', {'post_change': True}, 5),
]:
    values = {'tee_state': 1, 'tee_error': 0, 'available': 1, 'initialized': 1,
              'currentel': 8, 'sctlr_el2': 0x30c51835, 'daif': 0x2c0,
              'par_el1': 0x1122334400, 'sp': SP, 'gd': GD, 'reloc': 0xbf616000, **changes}
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(0x3000000, 0x1000)
    uc.mem_write(0x3000000, image)
    uc.mem_map(0xbf616000, 0x1d0000)
    uc.mem_write(0xbf616000, binary)
    uc.mem_map(0xb9600000, 0x6000)
    uc.mem_write(GD + 0x70, struct.pack('<Q', values['reloc']))
    uc.mem_map(0x6000000, 0x1000)
    uc.mem_write(0x6000000, struct.pack('<Q', 0x6000100))
    uc.mem_write(0x6000048, struct.pack('<Q', READER))
    uc.mem_write(0xbf7b7060, struct.pack('<Q', 0x6000000))
    if values.get('bad_prefix'):
        uc.mem_write(values['bad_prefix'], b'XXXX')
    preserved = {getattr(r, f'UC_ARM64_REG_X{n}'): 0xabc00000+n*256 for n in range(18, 30)}
    preserved[r.UC_ARM64_REG_X18] = values['gd']
    for register, value in preserved.items():
        uc.reg_write(register, value)
    uc.reg_write(r.UC_ARM64_REG_SP, values['sp'])
    uc.reg_write(r.UC_ARM64_REG_X30, RETURN)
    state = {'getter_calls': 0, 'tee_calls': 0, 'par': values['par_el1'], 'writes': 0}

    def return_mock(result):
        target = uc.reg_read(r.UC_ARM64_REG_X30)
        for n in range(1, 18):
            uc.reg_write(getattr(r, f'UC_ARM64_REG_X{n}'), 0xdead0000+n)
        uc.reg_write(r.UC_ARM64_REG_X0, result)
        uc.reg_write(r.UC_ARM64_REG_PC, target)

    def code_hook(uc, address, size, _):
        assert address != 0xbf621918, 'Persistent writer must never execute'
        if address == GETTER:
            state['getter_calls'] += 1
            assert uc.reg_read(r.UC_ARM64_REG_X0) == 0x30006a4
        if address in (0xbf621a08, 0xbf6218cc, 0xbf701fd8):
            return_mock({0xbf621a08: values['available'], 0xbf6218cc: values['initialized'], 0xbf701fd8: 0}[address])
            return
        if address == 0xbf670188:
            state['tee_calls'] += 1
            assert uc.reg_read(r.UC_ARM64_REG_X0) == 0x6000100
            assert uc.reg_read(r.UC_ARM64_REG_X1) == 2
            assert uc.reg_read(r.UC_ARM64_REG_X2) == 1
            param = uc.reg_read(r.UC_ARM64_REG_X3)
            assert struct.unpack('<Q', bytes(uc.mem_read(param, 8)))[0] == 2
            if not values['tee_error']:
                uc.mem_write(param + 8, struct.pack('<Q', values['tee_state']))
            if values.get('post_change'):
                uc.mem_write(0xbf64bcc8, b'XXXX')
            return_mock(values['tee_error'])
            return
        mnemonic, operands = instructions[address]
        if mnemonic == 'mrs':
            dst, src = operands.split(', ')
            value = state['par'] if src == 'par_el1' else values[src]
            uc.reg_write(getattr(r, 'UC_ARM64_REG_' + dst.upper()), value)
            uc.reg_write(r.UC_ARM64_REG_PC, address + 4)
        elif mnemonic == 'msr':
            assert operands == 'par_el1, x3'
            state['par'] = uc.reg_read(r.UC_ARM64_REG_X3)
            uc.reg_write(r.UC_ARM64_REG_PC, address + 4)

    def write_hook(uc, access, address, size, value, _):
        state['writes'] += 1
        in_output = set(range(address-0x3000000, address-0x3000000+size)) <= ALLOWED
        in_stock_stack = 0xb9600000 <= address and address+size <= SP
        assert in_output or in_stock_stack, (name, hex(address), size)

    uc.hook_add(UC_HOOK_CODE, code_hook)
    uc.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    uc.emu_start(ENTRY, RETURN, count=1500)
    data = bytes(uc.mem_read(0x3000000, len(image)))
    assert uc.reg_read(r.UC_ARM64_REG_PC) == RETURN
    assert uc.reg_read(r.UC_ARM64_REG_X0) == 0
    assert uc.reg_read(r.UC_ARM64_REG_SP) == values['sp']
    assert all(uc.reg_read(register) == value for register, value in preserved.items()), name
    assert state['par'] == values['par_el1']
    assert data[0x640:0x644] == b'ON23'
    assert struct.unpack_from('<I', data, 0x644)[0] == expected_status, name
    assert state['getter_calls'] <= 1 and state['tee_calls'] <= 1
    if expected_status == 2:
        assert struct.unpack_from('<3I', data, 0x6a0) == (1, values['tee_state'], 1)
        captures[name] = data
    cases.append({'case': name, 'passed': True, 'expected_status': expected_status,
                  'getter_calls': state['getter_calls'], 'tee_read_calls': state['tee_calls'], 'abi_preserved': True})

collector_cases = []
for name, variant, mutation, expected in [
    ('valid_locked', 'locked', None, True), ('valid_unlocked', 'unlocked', None, True),
    ('missing_checkpoint', 'locked', 'missing', False),
    ('changed_code', 'locked', 'code', False),
    ('failed_getter', 'locked', 'rc', False),
    ('invalid_state', 'locked', 'state', False),
    ('changed_stock_prefix', 'locked', 'prefix', False),
    ('missing_return_marker', 'locked', 'marker', False),
]:
    with tempfile.TemporaryDirectory() as directory:
        session = Path(directory)
        data = bytearray(captures[variant])
        if mutation == 'code': data[64] ^= 1
        if mutation == 'rc': struct.pack_into('<I', data, 0x6a0, 0)
        if mutation == 'state': struct.pack_into('<I', data, 0x6a4, 7)
        if mutation == 'prefix': data[0x6d0] ^= 1
        if mutation != 'missing': (session / 'ONNBEG23.BIN').write_bytes(image)
        (session / 'ONNRET23.BIN').write_bytes(data)
        (session / 'ONNCAP23.TXT').write_text('onn23_go=entered\n' if mutation == 'marker' else 'onn23_go=returned_zero\n')
        result = collect_local(session)
        assert result['secure_state_read_proven'] == expected, (name, result)
        collector_cases.append({'case': name, 'passed': True})

(BASE / 'offline-validation.json').write_text(json.dumps({
    'native_cases': cases, 'collector_cases': collector_cases, 'hardware_tested': False,
    'limits': 'Runs captured getter and lock-reader machine code, but mocks backend discovery, initialization, printf and the TEE command response. This does not prove live TEE behavior.'
}, indent=2) + '\n')
print(json.dumps({'native_cases_passed': len(cases), 'collector_cases_passed': len(collector_cases), 'device_contacted': False}))
