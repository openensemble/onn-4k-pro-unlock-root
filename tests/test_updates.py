"""Offline OTA controls: state preservation, refusal paths, and real shell flow."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import onn
import onnlib as lib
import ota_updates as ota


def initial_state():
    components = dict.fromkeys(ota.COMPONENTS, 0)
    components[ota.COMPONENTS[0]] = 1
    components[ota.COMPONENTS[4]] = 2  # Preserve pre-existing disabled components.
    return {'engine': 'running', 'setting': 'null', 'packages': {
        ota.GMS: {'enabled': 0, 'components': components},
        ota.UPDATER: {'enabled': 1, 'components': {}},
        ota.STORE: {'enabled': 1, 'components': {}}}}


def package_dump(package, state):
    lines = ['Packages:', f'  Package [{package}] (fixture):',
             f"    User 0: installed=true enabled={state['enabled']}"]
    for label, value in [('enabledComponents', 1), ('disabledComponents', 2)]:
        lines.append('      ' + label + ':')
        lines += ['        ' + name.split('/')[1] for name, state in state['components'].items() if state == value]
    # Neither another user nor the hidden factory APK may supply current state.
    lines += ['    User 10: installed=true enabled=3', 'Hidden system packages:',
              f'  Package [{package}] (old):', '    User 0: installed=true enabled=2']
    return '\n'.join(lines) + '\n'


class FakeDevice:
    def __init__(self, run):
        self.run = run
        self.config = {'run_id': '20261021T000000Z-1234abcd'}
        self.current = initial_state()
        self.events = 'onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)\n'
        self.calls = []
        self.uploads = {}
        self.module = False
        self.disabled = False
        self.fail_apply = False
        self.bad_hash = False
        lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True})
        lib.save(run / 'install/receipt.json', {'device_binding': 'fixture', 'flash_verified': True,
                 'remote_directory': '/data/local/tmp/onn-guide-install-' + self.config['run_id'],
                 'boot_id_before': 'old'})

    def binding(self):
        return 'fixture'

    def boot_id(self):
        return 'new'

    def preflight(self, state):
        assert state == 'unlocked'

    def property(self, name):
        return self.current['engine'] if name == 'init.svc.update_engine' else ''

    def call(self, action, local, remote, **kwargs):
        assert action == 'push'
        assert (self.run / 'updates/receipt.json').exists(), 'Backup must precede writes'
        self.uploads[remote] = Path(local)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def root(self, command, **kwargs):
        self.calls.append(command)
        output, code = '', 0
        if command == 'id':
            output = 'uid=0(root) gid=0(root)'
        elif command == '/debug_ramdisk/magisk -V':
            output = str(lib.PROFILE['magisk_version_code'])
        elif command.startswith('dumpsys package '):
            package = command.split()[-1]
            output = package_dump(package, self.current['packages'][package])
        elif command == 'settings get global ' + ota.SETTING:
            output = self.current['setting']
        elif command.startswith('timeout 4 '):
            output, code = self.events, 124
        elif command == 'test ! -e ' + ota.MODULE:
            lib.require(not self.module, 'Existing module')
        elif command.startswith('sha256sum '):
            paths = command.split()[1:]
            for name in paths:
                local = self.uploads[name] if name in self.uploads else self.run / 'updates/module' / Path(name).name
                output += ('0' * 64 if self.bad_hash else lib.digest(local)) + '  ' + name + '\n'
        elif command.startswith('set -eu\n'):
            self.module, self.disabled = True, True
        elif command.startswith('rm ' + ota.MODULE + '/disable'):
            self.current = ota.expected_paused(self.current)
            self.disabled = self.fail_apply
            output, code = ('failed', 1) if self.fail_apply else ('FIRMWARE_UPDATES_PAUSED', 0)
        elif command == 'cat ' + ota.MODULE + '/owner':
            output = lib.read(self.run / 'updates/receipt.json')['owner']
        elif command.startswith('test ! -e ' + ota.MODULE + '/disable'):
            lib.require(not self.disabled, 'Module disabled')
        elif command.startswith('#!/system/bin/sh\n'):
            self.current = lib.read(self.run / 'updates/receipt.json')['before']
            self.disabled = True
            output = 'UPDATE_SETTINGS_RESTORED'
        else:
            raise AssertionError('Unexpected device command: ' + command)
        return SimpleNamespace(returncode=code, stdout=output, stderr='')


class UpdateTests(unittest.TestCase):
    def test_apply_verify_and_restore_exact_original_states(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = Path(directory)
            device = FakeDevice(run)
            original = copy.deepcopy(device.current)
            ota.disable(device, run)
            receipt = lib.read(run / 'updates/receipt.json')
            self.assertEqual(receipt['before'], original)
            self.assertEqual(receipt['status'], 'disabled')
            self.assertEqual(device.current, ota.expected_paused(original))
            ota.status(device, run)
            device.module = False  # Manual module removal must not lose restoration.
            ota.restore(device, run)
            self.assertEqual(device.current, original)
            self.assertEqual(lib.read(run / 'updates/receipt.json')['status'], 'restored')
            restore = (run / 'updates/module/restore-state.sh').read_text()
            self.assertIn('pm enable --user 0 ' + ota.COMPONENTS[0], restore)
            self.assertIn('pm disable --user 0 ' + ota.COMPONENTS[4], restore)
            self.assertIn('settings delete global ' + ota.SETTING, restore)
            self.assertNotIn('pm enable --user 0 ' + ota.GMS + '\n', restore)
            self.assertNotIn('reboot', '\n'.join(device.calls))

    def test_busy_pending_unknown_or_last_nonidle_event_refuses_before_writes(self):
        for events in ('', 'onStatusUpdate(UPDATE_STATUS_DOWNLOADING (3), 0.5)',
                       'onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 0)',
                       'onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)\nonStatusUpdate(UPDATE_STATUS_CHECKING_FOR_UPDATE (1), 0)'):
            with self.subTest(events=events), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                device = FakeDevice(run)
                device.events = events
                with self.assertRaisesRegex(RuntimeError, 'No pause applied'):
                    ota.disable(device, run)
                self.assertFalse(device.uploads)
                self.assertFalse((run / 'updates').exists())

    def test_missing_root_proof_or_wrong_installation_cannot_change_updates(self):
        for invalid in ('proof', 'binding'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                device = FakeDevice(run)
                if invalid == 'proof':
                    lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': False})
                else:
                    device.binding = lambda: 'another-device'
                with self.assertRaises(RuntimeError):
                    ota.disable(device, run)
                self.assertFalse(device.uploads)

    def test_partial_failure_preserves_backup_refuses_replay_and_can_restore(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = Path(directory)
            device = FakeDevice(run)
            original = copy.deepcopy(device.current)
            device.fail_apply = True
            with self.assertRaisesRegex(RuntimeError, 'restore-updates'):
                ota.disable(device, run)
            backup = (run / 'updates/receipt.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'attempt exists'):
                ota.disable(device, run)
            self.assertEqual(backup, (run / 'updates/receipt.json').read_bytes())
            with self.assertRaisesRegex(RuntimeError, 'Module disabled'):
                ota.status(device, run)
            ota.restore(device, run)
            self.assertEqual(device.current, original)

    def test_changed_module_or_controls_cannot_be_reported_as_disabled(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = Path(directory)
            device = FakeDevice(run)
            ota.disable(device, run)
            device.bad_hash = True
            with self.assertRaisesRegex(RuntimeError, 'files differ'):
                ota.status(device, run)
            device.bad_hash = False
            device.current['engine'] = 'running'
            with self.assertRaisesRegex(RuntimeError, 'not fully verified'):
                ota.status(device, run)

    def test_stopped_engine_and_nondefault_global_state_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = Path(directory)
            device = FakeDevice(run)
            device.current.update(engine='stopped', setting='0')
            original = copy.deepcopy(device.current)
            ota.disable(device, run)
            self.assertFalse(any(c.startswith('timeout 4') for c in device.calls))
            ota.restore(device, run)
            self.assertEqual(device.current, original)

    def test_changed_backup_cannot_restore_the_wrong_configuration(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = Path(directory)
            device = FakeDevice(run)
            ota.disable(device, run)
            path = run / 'updates/receipt.json'
            receipt = lib.read(path)
            receipt['before']['setting'] = '0'
            lib.save(path, receipt)
            with self.assertRaisesRegex(RuntimeError, 'backup changed'):
                ota.restore(device, run)
            self.assertEqual(device.current['setting'], '1')

    def test_cli_requires_explicit_apply_without_contacting_device(self):
        for command in ('disable-updates', 'restore-updates'):
            with self.subTest(command=command), patch.object(onn, 'verify_files'), \
                    patch.object(onn, 'configuration', return_value=({}, Path('/unused'))), \
                    patch.object(onn, 'Device'), patch.object(ota, 'disable') as disable, \
                    patch.object(ota, 'restore') as restore, patch.object(onn.sys, 'argv', ['onn.py', command]):
                with self.assertRaisesRegex(RuntimeError, 'supply --apply'):
                    onn.main()
                disable.assert_not_called()
                restore.assert_not_called()


# Run the actual shell templates against stub Android commands, without ADB.
ANDROID_STUB = '''#!/usr/bin/env python3
import json, pathlib, sys
base = pathlib.Path(__file__).resolve().parent.parent
state = json.loads((base / 'state.json').read_text())
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
if name == 'getprop':
    print(state.get(args[0], ''))
elif name == 'update_engine_client':
    print(state['events'])
elif name == 'settings':
    if args[0] == 'get': print(state['setting'])
    else:
        state['setting'] = 'null' if args[0] == 'delete' else args[-1]
        state['writes'].append('settings')
elif name == 'setprop':
    state['init.svc.update_engine'] = 'stopped' if args[0] == 'ctl.stop' else 'running'
    state['writes'].append(args[0])
elif name == 'pm':
    sys.stdin.read()  # Must not consume the component list passed to the loop.
    state['writes'].append(args[-1])
    if state.get('fail_pm'):
        (base / 'state.json').write_text(json.dumps(state))
        sys.exit(1)
    state['pm'][args[-1]] = {'default-state': 0, 'enable': 1, 'disable': 2,
                             'disable-user': 3, 'disable-until-used': 4}[args[0]]
else:
    raise AssertionError(name)
(base / 'state.json').write_text(json.dumps(state))
'''


class BootScriptTests(unittest.TestCase):
    def test_boot_service_applies_all_components_and_refuses_busy_or_disabled_module(self):
        for scenario in ('idle', 'busy', 'disabled', 'failed-pm'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                module, binary = base / 'module', base / 'bin'
                module.mkdir()
                binary.mkdir()
                stub = binary / 'android-stub'
                stub.write_text(ANDROID_STUB)
                stub.chmod(0o755)
                for name in ('getprop', 'settings', 'setprop', 'pm', 'update_engine_client'):
                    (binary / name).symlink_to(stub)
                (binary / 'timeout').symlink_to('/usr/bin/timeout')
                (binary / 'sh').symlink_to('/bin/bash')
                for source, name in [('ota-common.sh', 'common.sh'), ('ota-pause.sh.in', 'pause.sh'),
                                     ('ota-service.sh', 'service.sh')]:
                    script = (lib.ROOT / 'tools' / source).read_text()
                    script = script.replace('/system/bin', str(binary)).replace('@FINGERPRINT@', lib.PROFILE['fingerprint'])
                    (module / name).write_text(script)
                (module / 'components.txt').write_text('\n'.join(ota.COMPONENTS) + '\n')
                owner = 'a' * 32
                (module / 'owner').write_text(owner + '\n')
                if scenario == 'disabled':
                    (module / 'disable').touch()
                state = {'init.svc.update_engine': 'running', 'sys.boot_completed': '1',
                         'ro.build.fingerprint': lib.PROFILE['fingerprint'], 'setting': 'null', 'writes': [],
                         'events': 'onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)' if scenario != 'busy' else
                         'onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 0)',
                         'fail_pm': scenario == 'failed-pm'}
                original_pm = {ota.UPDATER: 1, ota.STORE: 1, ota.GMS: 0, 'com.google.android.katniss': 3,
                               **initial_state()['packages'][ota.GMS]['components']}
                state['pm'] = original_pm
                (base / 'state.json').write_text(json.dumps(state))
                result = subprocess.run(['bash', str(module / 'service.sh')], stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True, timeout=15)
                after = lib.read(base / 'state.json')
                if scenario == 'idle':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(after['writes'], ['settings', 'ctl.stop', ota.UPDATER] + ota.COMPONENTS)
                    self.assertEqual(after['setting'], '1')
                    self.assertEqual(after['init.svc.update_engine'], 'stopped')
                    self.assertIn('FIRMWARE_UPDATES_PAUSED', (module / 'last-run.log').read_text())
                    # Exercise the actual generated restore script too, including
                    # ownership checks and restoration of nondefault overrides.
                    restore = ota.restore_script(initial_state(), owner)
                    restore = restore.replace('/system/bin', str(binary)).replace(ota.MODULE, str(module))
                    result = subprocess.run(['bash', '-c', restore], stdin=subprocess.DEVNULL,
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    restored = lib.read(base / 'state.json')
                    self.assertEqual(restored['pm'], original_pm)
                    self.assertEqual(restored['setting'], 'null')
                    self.assertEqual(restored['init.svc.update_engine'], 'running')
                    self.assertTrue((module / 'disable').exists())
                    self.assertTrue((module / 'remove').exists())
                elif scenario in ('busy', 'disabled'):
                    self.assertEqual(after['writes'], [])
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue((module / 'disable').exists())
                self.assertFalse((module / '.applying').exists())


if __name__ == '__main__':
    unittest.main()
