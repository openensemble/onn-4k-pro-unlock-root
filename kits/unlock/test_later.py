#!/usr/bin/env python3
"""Default: inspect the local kit. Explicit test/restore/collect actions use the TV."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from collect_result import collect_local

BASE = Path(__file__).resolve().parent
ADB = str(BASE / 'tools/adb')
TARGET = '192.0.2.10:5555'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def verify_local():
    manifest = json.loads((BASE / 'checksums.json').read_text())
    for name, expected in manifest['files'].items():
        path = (BASE / name).resolve()
        require(path.is_relative_to(BASE), 'Unexpected manifest path')
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                'Local artifact changed or missing: ' + name)
    plan = json.loads((BASE / 'experiment-plan.json').read_text())
    require(plan['original'] == 'run storeboot_base;', 'Unexpected original startup')
    require(plan['candidate'].endswith('else '+plan['original']+' fi;'), 'Missing stock fallback')
    return plan


class Device:
    def __init__(self, plan, session, report):
        self.plan, self.session, self.report = plan, session, report
        self.sequence = 0

    def persist(self):
        save(self.session / 'roundtrip.json', self.report)

    def adb(self, *args, check=True, timeout=25):
        return subprocess.run([ADB, '-s', TARGET, *args], capture_output=True,
                              text=True, check=check, timeout=timeout)

    def prop(self, name):
        return self.adb('shell', 'getprop', name).stdout.strip()

    def boot_id(self):
        value = self.adb('shell', 'cat', '/proc/sys/kernel/random/boot_id').stdout.strip()
        require(re.fullmatch(r'[0-9a-f-]{36}', value) is not None, 'Invalid boot ID response')
        return value

    def remote(self, name):
        require(re.fullmatch(r'[A-Z0-9]{1,8}\.[A-Z0-9]{1,3}', name) is not None, 'Invalid USB filename')
        return self.plan['usb_mount'] + '/' + name

    def exists(self, path, directory=False):
        require(re.fullmatch(r'/[A-Za-z0-9/_.-]+', path) is not None, 'Unsafe remote path')
        flag = '-d' if directory else '-e'
        result = self.adb('shell', f'if test {flag} {path}; then echo PRESENT; else echo ABSENT; fi')
        value = result.stdout.strip()
        require(value in ('PRESENT', 'ABSENT'), 'Device file existence result is ambiguous')
        return value == 'PRESENT'

    def action(self, name):
        package = self.plan['package']
        self.adb('shell', 'run-as', package, 'rm', '-f', 'files/report.json')
        command = ['shell', 'am', 'broadcast', '--receiver-foreground', '-f', '0x20',
                   '-a', package + '.' + name, '-n', package + '/.' + self.plan['receiver']]
        if name in ('APPLY', 'RESTORE'):
            command += ['--es', 'write_authorization', 'explicitly-authorized']
        if name == 'RESTART_SERVICE':
            command += ['--es', 'restart_authorization', 'explicitly-authorized']
        response = self.adb(*command)
        self.sequence += 1
        stem = f'{self.sequence:03d}-{name.lower()}'
        (self.session / (stem + '.txt')).write_text(response.stdout + response.stderr)
        deadline = time.monotonic() + 15
        report = None
        while time.monotonic() < deadline:
            raw = self.adb('exec-out', 'run-as', package, 'cat', 'files/report.json', check=False)
            # JSON parsing is essential: exec-out may return zero for a failed cat.
            try:
                report = json.loads(raw.stdout)
            except json.JSONDecodeError:
                report = None
            if isinstance(report, dict) and report.get('stage') in ('complete', 'failed'):
                break
            time.sleep(0.5)
        require(isinstance(report, dict), 'No completed service receipt; do not assume the record is unchanged')
        save(self.session / (stem + '.json'), report)
        require(report.get('action') == package + '.' + name, 'Receipt action mismatch')
        require(report.get('stage') == 'complete', 'Service action failed: ' + str(report.get('error', report.get('stage'))))
        return report

    def fresh(self, expected):
        restarted = self.action('RESTART_SERVICE')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                inspected = self.action('INSPECT')
            except (subprocess.SubprocessError, RuntimeError):
                # The new HAL can be temporarily absent while init restarts it.
                continue
            if inspected['service_pid'] != restarted['service_pid']:
                require(inspected['before'] == expected, 'Fresh environment does not match expected startup')
                return inspected
        raise RuntimeError('Service restart not verified through a new PID')

    def check_device(self):
        require(self.prop('ro.build.fingerprint') == self.plan['fingerprint'], 'Firmware changed; stop')
        require(self.prop('ro.bootloader') == self.plan['bootloader'], 'Bootloader changed; stop')
        require(self.prop('sys.boot_completed') == '1', 'Android has not completed boot')

    def remove_gate(self):
        # These two names belong only to this fixed experiment.
        if self.exists(self.plan['usb_mount'], directory=True):
            for name in (self.plan['input_gate_file'], 'ONN24TMP.TXT'):
                path = self.remote(name)
                if self.exists(path):
                    self.adb('shell', 'rm', path)
                require(not self.exists(path), 'Could not remove one-use gate: ' + name)
            self.adb('shell', 'sync')
            self.report['gate_cleanup'] = 'absent_on_mounted_usb'
        else:
            self.report['gate_cleanup'] = 'usb_not_mounted; contents_not_verified'
        self.persist()

    def restore(self):
        self.check_device()
        # Restore startup even if USB cleanup fails; receipt records both outcomes.
        try:
            self.remove_gate()
        except Exception as error:
            self.report['gate_cleanup_error'] = repr(error)
            self.persist()
        current = self.action('INSPECT')
        if current['before'] == self.plan['candidate']:
            self.action('RESTORE')
        else:
            require(current['before'] == self.plan['original'], 'Unknown startup command; no blind overwrite')
        final = self.fresh(self.plan['original'])
        self.report['original_startup_restored_and_verified'] = True
        self.report['restored_service_pid'] = final['service_pid']
        self.persist()
        print('Original startup restored and verified from a fresh service process.', flush=True)

    def capture(self):
        require(self.exists(self.plan['usb_mount'], directory=True), 'USB is not mounted; cannot collect')
        for name in self.plan['new_usb_files']:
            remote = self.remote(name)
            if self.exists(remote):
                local = self.session / name
                expected = self.adb('shell', 'sha256sum', remote).stdout.split()[0]
                if local.exists():
                    require(hashlib.sha256(local.read_bytes()).hexdigest() == expected,
                            'Existing local trace differs; refusing to overwrite: ' + name)
                    continue
                temporary = local.with_suffix(local.suffix + '.partial')
                self.adb('pull', remote, str(temporary), timeout=40)
                require(hashlib.sha256(temporary.read_bytes()).hexdigest() == expected, 'Capture hash mismatch: ' + name)
                temporary.replace(local)
        self.report['capture_collection_complete'] = True
        self.persist()
        result = collect_local(self.session)
        print(result['conclusion'], flush=True)

    def test(self):
        attempted_write = False
        uploaded_gate = False
        recovery_handoff = False
        failure = None
        try:
            self.check_device()
            require(self.prop('ro.boot.flash.locked') == '1', 'Unexpected lock state')
            require(self.prop('ro.boot.vbmeta.device_state') == 'locked', 'Unexpected vbmeta state')
            require(self.prop('ro.boot.verifiedbootstate') == 'green', 'Unexpected verified boot state')
            require(self.exists(self.plan['usb_mount'], directory=True), 'Expected USB volume is not mounted')
            for name in self.plan['new_usb_files'] + [self.plan['input_gate_file'], 'ONN24TMP.TXT']:
                require(not self.exists(self.remote(name)), 'Stale USB artifact; refusing to overwrite: ' + name)
            self.adb('install', '-r', str(BASE / 'build/secure-state-unlock-experiment.apk'), timeout=90)
            before = self.fresh(self.plan['original'])
            self.report['before_service_pid'] = before['service_pid']
            self.report['boot_id_before'] = self.boot_id()
            self.persist()
            payload = BASE / self.plan['payload_file']
            require(not self.exists(self.remote(self.plan['payload_file'])), 'Stale payload file')
            self.adb('push', str(payload), self.remote(self.plan['payload_file']))
            payload_hash = self.adb('shell', 'sha256sum', self.remote(self.plan['payload_file'])).stdout.split()[0]
            require(payload_hash == self.plan['payload_sha256'], 'USB payload hash mismatch')
            gate = BASE / self.plan['input_gate_file']
            uploaded_gate = True
            self.adb('push', str(gate), self.remote('ONN24TMP.TXT'))
            remote_hash = self.adb('shell', 'sha256sum', self.remote('ONN24TMP.TXT')).stdout.split()[0]
            require(remote_hash == self.plan['input_gate_sha256'], 'USB gate hash mismatch')
            self.adb('shell', 'mv', self.remote('ONN24TMP.TXT'), self.remote(self.plan['input_gate_file']))
            self.adb('shell', 'sync')
            attempted_write = True
            applied = self.action('APPLY')
            require(applied['after'] == self.plan['candidate'], 'Candidate readback mismatch')
            fresh = self.fresh(self.plan['candidate'])
            self.report['candidate_persistence_verified'] = True
            self.report['candidate_service_pid'] = fresh['service_pid']
            require(self.boot_id() == self.report['boot_id_before'], 'Unexpected reboot during preparation')
            self.report['reboot_requested'] = True
            self.report['awaiting_factory_reset'] = True
            self.persist()
            print('Starting the one-use single secure unlock request and readback.', flush=True)
            # Recovery requires user input. Once the reboot may have been sent,
            # leave ADB and startup restoration alone until setup is complete.
            recovery_handoff = True
            try:
                result = self.adb('reboot', check=False, timeout=10)
                self.report['reboot_client_returncode'] = result.returncode
                if result.returncode != 0:
                    self.report['reboot_delivery_uncertain'] = True
            except subprocess.TimeoutExpired:
                self.report['reboot_client_timeout'] = True
                self.report['reboot_delivery_uncertain'] = True
            self.persist()
        except BaseException as error:
            failure = error
            self.report['error'] = repr(error)
            self.persist()
        finally:
            if attempted_write and not recovery_handoff:
                try:
                    self.restore()
                except BaseException as error:
                    self.report['restoration_error'] = repr(error)
                    self.persist()
                    print('RESTORATION NOT VERIFIED. Remove USB and power cycle; use restore when Android returns.', flush=True)
                    failure = failure or error
            elif uploaded_gate and not recovery_handoff:
                try:
                    self.remove_gate()
                except BaseException as error:
                    self.report['gate_cleanup_error'] = repr(error)
                    self.persist()
                    failure = failure or error
        if recovery_handoff:
            print('Reboot requested. Wait for the recovery screen before removing the thumb drive.\n'
                  'The command has stopped contacting the Onn 4K Pro.\n'
                  'Collect the thumb drive result on your computer, then follow the factory-reset instructions.\n'
                  'Come back when you have finished resetting and setting up your device.\n'
                  'Unlock success and startup restoration still need verification. Do not rerun unlock.', flush=True)
        if failure:
            raise failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='status', choices=('status', 'test', 'restore', 'collect'))
    parser.add_argument('--execute-device-test', action='store_true', help='Allow the explicit device action; test changes startup and reboots once.')
    parser.add_argument('--session', type=Path, help='Existing receipt directory for later collection only.')
    args = parser.parse_args()
    if args.action != 'status' and not args.execute_device_test:
        parser.error('Device actions require --execute-device-test; no device command was issued')
    plan = verify_local()
    if args.action == 'status':
        print(json.dumps({'local_artifacts_verified': True, 'hardware_tested_by_this_command': False,
                          'purpose': 'One-use single secure unlock request and readback; root/unlock unproven.',
                          'later_test': 'python3 test_later.py test --execute-device-test'}, indent=2))
        return
    if args.action == 'collect':
        require(args.session is not None, 'Collection needs --session')
        session = args.session.resolve()
        require(session.is_relative_to(BASE / 'sessions'), 'Session must be inside this kit sessions directory')
        report = json.loads((session / 'roundtrip.json').read_text())
        Device(plan, session, report).capture()
        return
    require(args.session is None, '--session is for collection only')
    if args.action == 'test':
        for old in (BASE / 'sessions').glob('*/roundtrip.json'):
            require(json.loads(old.read_text()).get('action') != 'test', 'This fixed test already has a session; preserve the evidence and prepare a new experiment before another attempt')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    session = BASE / 'sessions' / stamp
    session.mkdir(parents=True)
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'action': args.action,
              'experiment': 24, 'reboot_requested': False, 'android_returned': False,
              'original_startup_restored_and_verified': False}
    device = Device(plan, session, report)
    device.persist()
    print('Receipt directory: ' + str(session), flush=True)
    if args.action == 'test':
        device.test()
    else:
        # Reinstall the same fixed diagnostic package if Android lost it.
        device.check_device()
        device.adb('install', '-r', str(BASE / 'build/secure-state-unlock-experiment.apk'), timeout=90)
        try:
            device.restore()
        except BaseException as error:
            report['restoration_error'] = repr(error)
            device.persist()
            raise


if __name__ == '__main__':
    main()
