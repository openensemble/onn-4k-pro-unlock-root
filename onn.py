#!/usr/bin/env python3
"""Guide for the earlier onn 4K Pro (jarvis/SNA); the new 2026 model is unsupported."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import uuid
import zipfile

from onnlib import (ROOT, WORK, PROFILE, Device, configuration, digest, latest_session,
                    load_transport, now, read, refresh_kit_manifest, require, save,
                    sessions, target_value, usb_value, validate_patched_image, verify_files)


def setup(args):
    target, usb = target_value(args.target), usb_value(args.usb_uuid)
    require(not (WORK / 'current.json').exists() or args.new_run,
            'A run exists. Preserve it; use --new-run only after restoring its device startup.')
    if args.adb:
        adb = Path(args.adb).expanduser().resolve()
    else:
        require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'AMD64'),
                'The bundled ADB is Linux x86_64. Supply --adb for another host; other hosts are untested.')
        adb = ROOT / 'tools/linux/adb'
    require(adb.is_file(), 'ADB binary missing')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run = WORK / 'runs' / run_id
    run.mkdir(parents=True)
    for kind in ['read', 'unlock', 'root']:
        kit = run / kind
        shutil.copytree(ROOT / 'kits' / kind, kit, ignore=shutil.ignore_patterns('__pycache__'))
        (kit / 'tools').mkdir(exist_ok=True)
        shutil.copy2(adb, kit / 'tools/adb')
        (kit / 'tools/adb').chmod(0o755)
        (kit / 'sessions').mkdir()
        runner = kit / 'test_later.py'
        text = runner.read_text()
        needle = "TARGET = '192.0.2.10:5555'"
        require(text.count(needle) == 1, 'Unexpected template target')
        runner.write_text(text.replace(needle, 'TARGET = ' + repr(target)))
        plan = read(kit / 'experiment-plan.json')
        plan['usb_mount'] = plan['usb_mount'].replace('ABCD-1234', usb)
        if kind == 'root':
            plan['full_patched_image'] = str(run / 'patched-boot.img')
        save(kit / 'experiment-plan.json', plan)
        refresh_kit_manifest(kit)
    config = {'created_at': now(), 'run_id': run_id, 'target': target, 'usb_uuid': usb}
    save(run / 'configuration.json', config)
    save(WORK / 'current.json', config)
    print('Prepared local run:', run)
    print('No device was contacted. Next: python3 onn.py doctor')


def prepare_usb(device, run):
    device.preflight()
    require(device.usb_present(), 'Expected FAT thumb drive is not mounted on the Onn 4K Pro')
    for kind in ['read', 'unlock', 'root']:
        path = read(run / kind / 'experiment-plan.json')['usb_mount']
        device.shell('if test -d ' + path + '; then test -z "$(ls -A ' + path + ')"; '
                     'else mkdir ' + path + '; fi')
    print('ONN23, ONN24 and ONN26 are present and empty. No test is armed.')


def set_target(args, config, run):
    target = target_value(args.target)
    for kind in ['read', 'unlock', 'root']:
        runner = run / kind / 'test_later.py'
        text = runner.read_text()
        needle = 'TARGET = ' + repr(config['target'])
        require(text.count(needle) == 1, 'Unexpected saved target')
        runner.write_text(text.replace(needle, 'TARGET = ' + repr(target)))
        refresh_kit_manifest(run / kind)
    config['target'] = target
    save(run / 'configuration.json', config)
    save(WORK / 'current.json', config)
    print('Local ADB target updated; test history preserved. No device contacted.')


def run_kit(run, kind, action):
    result = subprocess.run([sys.executable, str(run / kind / 'test_later.py'),
                             action, '--execute-device-test'])
    require(result.returncode == 0,
            'The operation did not complete. Do not repeat the test. Preserve work/ and follow docs/RECOVERY.md.')


def collect_unlock(args, run):
    # Collection is deliberately offline so recovery-mode ADB is unnecessary.
    kit = run / 'unlock'
    session = latest_session(kit)
    source = Path(args.usb_path).expanduser().resolve() / 'ONN24'
    require(source.is_dir(), 'Select the mounted thumb drive root, not its ONN24 subdirectory')
    plan = read(kit / 'experiment-plan.json')
    copied = []
    for name in plan['new_usb_files']:
        src, dest = source / name, session / name
        if src.is_file():
            if dest.exists():
                require(digest(src) == digest(dest), 'Saved capture differs; refusing overwrite: ' + name)
            else:
                shutil.copy2(src, dest)
                require(digest(src) == digest(dest), 'Capture copy mismatch')
            copied.append(name)
    gate = source / plan['input_gate_file']
    gate_was_present = gate.exists()
    if gate_was_present:
        shutil.copy2(gate, session / 'unconsumed-gate.saved')
        gate.unlink()
    save(session / 'host-collection.json', {'time': now(), 'copied': copied,
         'gate_was_present': gate_was_present, 'gate_absent_after_collection': not gate.exists()})
    module = load_transport(kit)
    result = module.collect_local(session)
    print(json.dumps(result, indent=2))
    require(result['unlock_request_accepted'] and result['secure_state_change_observed'],
            'Unlock success is not established. Do not rerun the writer; inspect these receipts.')
    print('The trusted service accepted the unlock. See the recovery/reset step in README.md.')


def extract_magisk(output, complete=False):
    output.mkdir(parents=True, exist_ok=True)
    apk = ROOT / 'assets/Magisk-v30.7.apk'
    require(digest(apk) == PROFILE['magisk_apk_sha256'], 'Magisk APK changed')
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            destination = None
            if name.startswith('lib/armeabi-v7a/lib') and name.endswith('.so'):
                destination = name.split('/')[-1][3:-3]
            elif name.startswith('assets/') and (name.endswith('.sh') or name == 'assets/stub.apk'
                    or (complete and (name == 'assets/bootctl' or name.startswith('assets/chromeos/')))):
                destination = name[len('assets/'):]
            if destination and not name.endswith('/'):
                path = output / destination
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
                path.chmod(0o755)


def patch(device, run, config):
    device.preflight('unlocked')
    require(not (run / 'patch.json').exists(), 'A patch record exists; inspect it rather than overwrite it')
    require(not (run / 'patched-boot.img').exists(), 'A patched image already exists')
    stock_gz = ROOT / 'firmware/stock-boot-15051976.img.gz'
    require(digest(stock_gz) == PROFILE['stock_boot_gzip_sha256'], 'Compressed stock image changed')
    stock = gzip.decompress(stock_gz.read_bytes())
    require(len(stock) == PROFILE['stock_boot_size'] and hashlib.sha256(stock).hexdigest() == PROFILE['stock_boot_sha256'],
            'Stock image integrity failed')
    (run / 'stock-boot.img').write_bytes(stock)
    tools = run / 'patch-tools'
    extract_magisk(tools)
    remote = '/data/local/tmp/onn-guide-patch-' + config['run_id']
    device.shell('test ! -e ' + remote + ' && mkdir ' + remote + ' && chmod 700 ' + remote)
    for path in sorted(tools.iterdir()):
        if path.is_file():
            device.call('push', str(path), remote + '/' + path.name, timeout=90)
    device.call('push', str(run / 'stock-boot.img'), remote + '/input-boot.img', timeout=120)
    receipt = {'started_at': now(), 'device_binding': device.binding(), 'boot_id': device.boot_id(),
               'remote_directory': remote, 'patched_on_this_device': False, 'firmware_written': False}
    save(run / 'patch.json', receipt)
    script = f'''#!/system/bin/sh
cd {remote} || exit 1
export BOOTMODE=true
. ./util_functions.sh
TMPDIR={remote}/work-tmp
mkdir -p "$TMPDIR" || exit 1
api_level_arch_detect
export SOURCEDMODE=true
export KEEPVERITY=true
export KEEPFORCEENCRYPT=true
export PATCHVBMETAFLAG=false
export RECOVERYMODE=false
export LEGACYSAR=false
. ./boot_patch.sh ./input-boot.img
'''
    (tools / 'patch.sh').write_text(script)
    device.call('push', str(tools / 'patch.sh'), remote + '/patch.sh')
    device.shell('chmod 755 ' + remote + '/*')
    result = device.shell('cd ' + remote + '; ASH_STANDALONE=1 ./busybox sh ./patch.sh', timeout=180, check=False)
    (run / 'patch.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Magisk patch failed; inspect patch.log. No partition was written.')
    device.call('pull', remote + '/new-boot.img', str(run / 'patched-boot.img'), timeout=120)
    patched = (run / 'patched-boot.img').read_bytes()
    payload = validate_patched_image(stock, patched)
    plan = read(run / 'root/experiment-plan.json')
    require(hashlib.sha256(payload).hexdigest() == plan['payload_sha256'], 'USB payload differs from tested candidate')
    (run / 'root' / plan['payload_file']).write_bytes(payload)
    refresh_kit_manifest(run / 'root')
    device.call('install', '-r', str(ROOT / 'assets/Magisk-v30.7.apk'), timeout=90)
    receipt.update({'completed_at': now(), 'patched_on_this_device': True,
                    'patched_sha256': digest(run / 'patched-boot.img'), 'kernel_unchanged': True,
                    'tested_payload_match': True})
    save(run / 'patch.json', receipt)
    print('Patched on this device, kernel unchanged, and output matches the tested layout. No firmware was flashed.')


def check_patch_binding(device, run):
    receipt = read(run / 'patch.json')
    require(receipt.get('patched_on_this_device') and receipt.get('tested_payload_match'), 'No validated on-device patch')
    require(receipt['device_binding'] == device.binding(), 'This patch belongs to another Android installation')
    require(digest(run / 'patched-boot.img') == PROFILE['expected_patched_sha256'], 'Patched image changed')
    return receipt


def root_proof(device, run):
    device.preflight('unlocked')
    check_patch_binding(device, run)
    session = latest_session(run / 'root')
    capture = read(session / 'capture-validation.json')
    roundtrip = read(session / 'roundtrip.json')
    require(capture['android_booted_via_candidate'], 'The USB boot marker and header were not proved')
    require(roundtrip['original_startup_restored_and_verified'], 'Restore normal startup first')
    require(device.boot_id() == roundtrip['boot_id_after'], 'The tested temporary-root boot is no longer running')
    print('If the Onn 4K Pro displays a Superuser request for Shell, choose Grant.', flush=True)
    result = device.root('id', timeout=55, check=False)
    proof = {'time': now(), 'boot_id': device.boot_id(), 'device_binding': device.binding(),
             'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
             'root_proven': bool(result.returncode == 0 and re.search(r'\buid=0\(root\)', result.stdout))}
    save(run / 'temporary-root-proof.json', proof)
    require(proof['root_proven'], 'Root not granted/proved. Run root-proof after granting Shell; do not repeat root-test.')
    print(result.stdout.strip())
    print('Temporary root proved. Normal startup restored. Next: install-root --accept-risk')


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Run with no command for the interactive guide. The process can erase data or brick the device.')
    sub = parser.add_subparsers(dest='command')
    p = sub.add_parser('wizard', help='Guided setup with automatic device and thumb drive selection (default)')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--preview', action='store_true', help='Show the guide without contacting any device')
    mode.add_argument('--status', action='store_true', help='Show saved progress without contacting any device')
    mode.add_argument('--discover-only', action='store_true', help='Find network ADB devices and list thumb drive volumes on the Onn 4K Pro; no setup or reboot')
    sub.add_parser('verify-files', help='Verify packaged files; no device contact')
    p = sub.add_parser('setup', help='Create a local run; no device contact')
    p.add_argument('--target', required=True)
    p.add_argument('--usb-uuid', required=True)
    p.add_argument('--adb')
    p.add_argument('--new-run', action='store_true')
    p = sub.add_parser('set-target', help='Update the local address after setup/reset; keep receipts')
    p.add_argument('--target', required=True)
    sub.add_parser('doctor', help='Read and validate firmware identity; no reboot or flash')
    sub.add_parser('prepare-usb', help='Create empty experiment folders on the mounted thumb drive')
    for command in ['read-state', 'root-test', 'install-root', 'restore-stock']:
        p = sub.add_parser(command)
        p.add_argument('--accept-risk', action='store_true')
    p = sub.add_parser('unlock')
    p.add_argument('--accept-data-loss', action='store_true')
    p = sub.add_parser('collect-unlock', help='Offline receipt collection from the thumb drive connected to the computer')
    p.add_argument('--usb-path', required=True)
    p = sub.add_parser('restore-startup')
    p.add_argument('--kit', choices=['read', 'unlock', 'root'], required=True)
    sub.add_parser('verify-unlock')
    sub.add_parser('patch')
    sub.add_parser('root-proof')
    p = sub.add_parser('verify-root')
    p.add_argument('--reboot', action='store_true')
    p.add_argument('--usb-removed', action='store_true')
    for command in ['disable-updates', 'restore-updates']:
        p = sub.add_parser(command, help='Change firmware update settings after verified permanent root')
        p.add_argument('--apply', action='store_true')
    sub.add_parser('updates-status', help='Check the saved firmware update choice on the Onn 4K Pro')
    args = parser.parse_args()
    count = verify_files()
    if args.command in (None, 'wizard'):
        from wizard import start
        start(args)
        return
    if args.command == 'verify-files':
        print(f'{count} packaged files verified. No device contacted.')
        return
    if args.command == 'setup':
        setup(args)
        return
    config, run = configuration()
    if args.command == 'set-target':
        set_target(args, config, run)
        return
    device = Device(config, run)
    if args.command == 'collect-unlock':
        collect_unlock(args, run)
        return
    if args.command == 'doctor':
        print(json.dumps(device.preflight(), indent=2))
        print('Thumb drive mounted:', device.usb_present())
    elif args.command == 'prepare-usb':
        prepare_usb(device, run)
    elif args.command in ['read-state', 'unlock', 'root-test']:
        if args.command == 'unlock':
            require(args.accept_data_loss, 'Unlock can erase data or brick the device; read README and supply --accept-data-loss')
            device.preflight('locked')
            receipt = read(latest_session(run / 'read') / 'capture-validation.json')
            require(receipt['secure_state_read_proven'] and receipt['lock_state'] == 1, 'A successful locked-state read is required first')
            binding = read(run / 'locked-read-binding.json')
            require(binding['device_binding'] == device.binding(), 'Locked-state read belongs to another installation')
            require(binding['boot_id_after'] == device.boot_id(), 'Device rebooted since the locked-state read; stop for review')
            kind = 'unlock'
        else:
            require(args.accept_risk, 'This reboot test can brick the device; read README and supply --accept-risk')
            kind = 'read' if args.command == 'read-state' else 'root'
            device.preflight('locked' if kind == 'read' else 'unlocked')
            if kind == 'root':
                check_patch_binding(device, run)
        run_kit(run, kind, 'test')
        if kind == 'read':
            session = latest_session(run / 'read')
            roundtrip = read(session / 'roundtrip.json')
            capture = read(session / 'capture-validation.json')
            require(capture['secure_state_read_proven'] and capture['lock_state'] == 1,
                    'Locked-state read was not proved; do not unlock')
            require(roundtrip['original_startup_restored_and_verified'], 'Original startup is not restored')
            save(run / 'locked-read-binding.json', {'device_binding': device.binding(),
                 'boot_id_after': roundtrip['boot_id_after']})
        if kind == 'root':
            root_proof(device, run)
    elif args.command == 'restore-startup':
        device.preflight()
        run_kit(run, args.kit, 'restore')
    elif args.command == 'verify-unlock':
        properties = device.preflight('unlocked')
        report = device.inspect_startup(install=True, fresh=True, kind='unlock')
        save(run / 'unlocked-proof.json', {'time': now(), 'properties': properties,
             'stock_startup': report['before'], 'boot_id': device.boot_id()})
        print('Android reports unlocked/orange, with original startup freshly verified.')
    elif args.command == 'patch':
        patch(device, run, config)
    elif args.command == 'root-proof':
        root_proof(device, run)
    elif args.command in ['disable-updates', 'restore-updates', 'updates-status']:
        import ota_updates
        if args.command == 'updates-status':
            ota_updates.status(device, run)
        else:
            require(args.apply, 'Read the firmware update option in README, then supply --apply')
            operation = ota_updates.disable if args.command == 'disable-updates' else ota_updates.restore
            operation(device, run)
    elif args.command in ['install-root', 'verify-root', 'restore-stock']:
        from root_install import install, verify, restore
        if args.command != 'verify-root':
            require(args.accept_risk, 'This writes boot_b. Read README and supply --accept-risk')
        if args.command == 'install-root':
            install(device, run, config)
        elif args.command == 'verify-root':
            verify(device, run, args)
        else:
            restore(device, run)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print('STOP:', error, file=sys.stderr)
        sys.exit(1)
