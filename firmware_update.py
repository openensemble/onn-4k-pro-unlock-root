"""Pinned, data-preserving 15051976/B -> 16202347/A update with root retention.

The underlying procedure was measured on one device. This portable wrapper is
tested offline; it is not a second hardware validation. Never retries a write.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import queue
import shlex
import shutil
import struct
import subprocess
import tarfile
import threading
import time
from types import SimpleNamespace
import urllib.request
import uuid
import zipfile
import zlib

from onnlib import (ROOT, WORK, PROFILE, NEW_PROFILE, Device, check_properties,
                    digest, now, read, require, save, target_value, validate_patched_image,
                    refresh_kit_manifest)
import discovery
import ota_updates

CURRENT = WORK / 'firmware-update.json'
MODULES = ('/data/adb/modules/onn_ota_pause', '/data/adb/modules/oe_ota_pause')
BACKUP_TREES = ('adb', 'app', 'data', 'user_de/0', 'system', 'system_ce/0',
                'system_de/0', 'misc/adb', 'media/0')
WARNING = '''Update 15051976 slot B -> 16202347 slot A, retaining existing unlock/root.
Verified on ONE already-unlocked 2024 jarvis/SNA device, November 6, 2026.
The packaged updater has offline tests; it has not been run end to end on hardware.
It does not request a reset or relock. Flashing can still cause data loss or
permanently brick the device. Backups are not a guaranteed recovery method.
16202347 is the newest REVIEWED build; this tool never installs an unknown OTA.
Fresh unlocking on 16202347 is a separate, UNTESTED experimental workflow.'''


def add_parser(sub):
    p = sub.add_parser('update-firmware', help='Pinned 16202347 upgrade; underlying procedure verified on one device')
    actions = p.add_mutually_exclusive_group()
    for name in ('prepare', 'apply', 'reboot', 'verify', 'status'):
        actions.add_argument('--' + name, action='store_true')
    actions.add_argument('--set-target', metavar='IP:PORT', help='Change saved address only after it changes')
    p.add_argument('--target', help='Source device address for --prepare')
    p.add_argument('--ota-file', type=Path, help='Use a local copy of the exact pinned OTA instead of downloading')
    p.add_argument('--accept-risk', action='store_true', help='Acknowledge data-loss and permanent-brick risk')


@contextmanager
def operation_lock():
    import fcntl
    WORK.mkdir(exist_ok=True)
    with (WORK / 'wizard.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another guide/update is running. Do not start concurrent device actions.') from None
        yield


def saved_update():
    config = read(CURRENT)
    require(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', config['run_id']), 'Invalid update run')
    target_value(config['target'])
    run = WORK / 'firmware-updates' / config['run_id']
    report = read(run / 'receipt.json')
    require(report.get('version') == 1 and report['run_id'] == config['run_id'], 'Update receipt mismatch')
    return UpdateDevice(config, run), report


class UpdateDevice(Device):
    def __init__(self, config, run):
        super().__init__(config, run)
        self.adb = [str(ROOT / 'tools/linux/adb'), '-s', config['target']]
        self.remote = '/data/local/tmp/onn-firmware-' + config['run_id']
        self.ota = '/data/ota_package/onn-firmware-' + config['run_id']

    def call(self, *args, timeout=30, check=True):
        logs = self.run / 'commands'
        logs.mkdir(exist_ok=True)
        path = logs / (uuid.uuid4().hex + '.json')
        receipt = {'time': now(), 'argv': list(args), 'status': 'starting'}
        save(path, receipt)
        process = subprocess.Popen(self.adb + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, errors='replace')
        started = time.monotonic()
        while True:
            try:
                stdout, stderr = process.communicate(timeout=min(15, max(0.1, timeout-(time.monotonic()-started))))
                result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic()-started >= timeout:
                    process.kill()
                    stdout, stderr = process.communicate()
                    path.with_suffix('.log').write_text(stdout + stderr)
                    receipt.update(status='client_timeout', elapsed_seconds=round(time.monotonic()-started))
                    save(path, receipt)
                    raise subprocess.TimeoutExpired(process.args, timeout)
                label = 'Transferring files' if args[0] in ('push', 'pull') else 'Waiting for the current device step'
                print(f'{label} ({round(time.monotonic()-started)} seconds); keep power connected.', flush=True)
        path.with_suffix('.log').write_text(result.stdout + result.stderr)
        receipt.update(status='returned', returncode=result.returncode)
        save(path, receipt)
        require(not check or result.returncode == 0, 'Device command failed; inspect ' + str(path.with_suffix('.log')))
        return result

    def guard(self, report, new=False, same_boot=True):
        self.profile = NEW_PROFILE if new else PROFILE
        props = self.preflight('unlocked')
        all_props = discovery.parse_properties(self.shell('getprop').stdout)
        require(discovery.device_identity(all_props) == report['hardware_identity'], 'Different physical device')
        require(self.binding() == report['device_binding'], 'Android installation changed; stop')
        if same_boot:
            require((self.boot_id() != report['boot_id_before']) if new else
                    (self.boot_id() == report['boot_id_before']), 'Unexpected boot ID; inspect the saved update')
        require('uid=0(root)' in self.root('id', timeout=55).stdout, 'Magisk root is required')
        require(self.root('/debug_ramdisk/magisk -V').stdout.strip() == '30700', 'Only Magisk 30.7 is covered')
        require(self.property('ro.boot.onn_rootprobe') == '', 'Temporary USB root boot is unsupported')
        target = 'boot_a' if new else 'boot_b'
        expected = NEW_PROFILE['expected_patched_sha256'] if new else PROFILE['expected_patched_sha256']
        require(self.root('sha256sum /dev/block/by-name/' + target, timeout=90).stdout.split()[0] == expected,
                'Active boot image differs from the covered installation')
        return props

    def check_startup(self, install=False):
        kit = self.run / 'root'
        if not kit.exists():
            shutil.copytree(ROOT/'kits/root', kit, ignore=shutil.ignore_patterns('__pycache__'))
            (kit/'tools').mkdir(exist_ok=True)
            shutil.copyfile(ROOT/'tools/linux/adb',kit/'tools/adb')
            (kit/'tools/adb').chmod(0o755)
        runner=kit/'test_later.py'
        text=runner.read_text()
        text,count=re.subn(r"^TARGET = '[^']+'$",'TARGET = '+repr(self.config['target']),text,flags=re.M)
        require(count==1,'Unexpected startup helper configuration')
        runner.write_text(text)
        refresh_kit_manifest(kit)
        return self.inspect_startup(install=install,fresh=True)

    def stream(self, command, destination, timeout=1800):
        require(not destination.exists() and not destination.with_suffix(destination.suffix + '.partial').exists(),
                'Backup already exists; preserve it, do not overwrite')
        partial = destination.with_suffix(destination.suffix + '.partial')
        with partial.open('xb') as output, destination.with_suffix('.transport.log').open('xb') as errors:
            process = subprocess.Popen(self.adb + ['exec-out', '/debug_ramdisk/su -c ' + shlex.quote(command)],
                                       stdout=output, stderr=errors)
            started = time.monotonic()
            while True:
                try:
                    code = process.wait(timeout=15)
                    break
                except subprocess.TimeoutExpired:
                    print(f'Backup {destination.name}: {partial.stat().st_size // (1024*1024)} MiB received '
                          f'({round(time.monotonic()-started)} seconds).', flush=True)
                    if time.monotonic()-started >= timeout:
                        process.kill(); process.wait()
                        raise RuntimeError('Backup transfer timed out; preserve partial output. No update applied.')
        require(code == 0, 'ADB backup interrupted; preserve partial output')
        # exec-out can conceal remote failure. Every caller validates size/hash
        # or tar status, diagnostics and the complete archive before accepting it.
        partial.replace(destination)


def engine_status(device):
    result = device.root('timeout 5 /system/bin/update_engine_client --follow', timeout=15, check=False)
    events = re.findall(r'onStatusUpdate\((UPDATE_STATUS_[A-Z_]+) \((\d+)\), ([^)]+)\)', result.stdout + result.stderr)
    require(result.returncode in (0, 124) and events, 'Updater status unavailable; do not apply/reboot')
    return int(events[-1][1])


def engine_start(device):
    state = device.property('init.svc.update_engine')
    require(state in ('running', 'stopped'), 'Unknown update engine state')
    if state == 'stopped':
        device.root('setprop ctl.start update_engine')
        for _ in range(20):
            if device.property('init.svc.update_engine') == 'running':
                break
            time.sleep(0.5)
    require(device.property('init.svc.update_engine') == 'running', 'Updater did not start')


def snapshot_state(device):
    value = device.root('/system/bin/snapshotctl dump').stdout
    require(re.search(r'^Update state: [a-z-]+$', value, re.M), 'Unknown snapshot status')
    return value


def validate_backup(path):
    """Validate every header, member extent and a real tar end marker, without extraction."""
    size = path.stat().st_size
    require(size % 512 == 0, 'Truncated or contaminated backup archive')
    roots, files = set(), 0
    with path.open('rb') as source:
        while True:
            header = source.read(512)
            require(len(header) == 512, 'Backup has no complete end marker')
            if header == bytes(512):
                require(source.read(512) == bytes(512), 'Backup end marker is incomplete')
                require(not any(source.read()), 'Unexpected data after backup end marker')
                break
            member = tarfile.TarInfo.frombuf(header, 'utf-8', 'surrogateescape')
            name = member.name.removeprefix('./').rstrip('/')
            roots.update(tree for tree in BACKUP_TREES if name == tree or name.startswith(tree + '/'))
            require(member.size >= 0, 'Invalid backup member')
            source.seek((member.size + 511) // 512 * 512, 1)
            require(source.tell() <= size - 1024, 'Truncated backup member')
            files += member.isfile()
    require(roots == set(BACKUP_TREES) and files > 0, 'Required backup trees are missing')
    return {'complete_archive_verified': True, 'required_trees_present': True,
            'bytes': size, 'sha256': digest(path), 'regular_files': files,
            'limitation': 'Live file backup; not atomic and not a guaranteed Android restore.'}


def verify_tar_diagnostics(returncode, text):
    lines = text.splitlines()
    allowed = {"tar: unknown file type '140000'", 'tar: had errors'}
    require((returncode == '0' and not lines) or
            (returncode == '1' and bool(lines) and set(lines) <= allowed
             and "tar: unknown file type '140000'" in lines),
            'Backup reported unexpected errors; no firmware update permitted')
    return {'omitted_runtime_sockets': lines.count("tar: unknown file type '140000'")}


def boot_control(raw):
    require(len(raw) == 32 and struct.unpack_from('<I', raw, 4)[0] == 0x42414342, 'Invalid A/B control record')
    require(struct.unpack_from('<I', raw, 28)[0] == zlib.crc32(raw[:28]), 'A/B control CRC mismatch')
    require(raw[8] == 1 and raw[9] & 7 == 2, 'Unexpected A/B control version or slot count')
    return [{'priority': raw[12 + i*2] & 15, 'tries': (raw[12 + i*2] >> 4) & 7,
             'successful': bool(raw[12 + i*2] & 128), 'corrupt': bool(raw[13 + i*2] & 1)} for i in range(2)]


def read_boot_control(device):
    encoded = device.root('dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | base64').stdout
    import base64
    return boot_control(base64.b64decode(encoded))


def prepare_ota(run, local=None):
    destination = run / 'update.zip'
    require(not destination.exists(), 'OTA already staged; preserve existing preparation')
    if local:
        require(local.is_file() and local.stat().st_size == NEW_PROFILE['ota_size'] and
                digest(local) == NEW_PROFILE['ota_sha256'], 'Local OTA does not match pinned build 16202347')
        shutil.copyfile(local, destination)
    else:
        partial = destination.with_suffix('.zip.partial')
        print('Downloading the pinned official OTA (about 899 MB).', flush=True)
        with urllib.request.urlopen(NEW_PROFILE['ota_url'], timeout=45) as response, partial.open('xb') as output:
            require(response.url.startswith('https://'), 'OTA transport must stay on HTTPS')
            total, notified = 0, time.monotonic()
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                require(total <= NEW_PROFILE['ota_size'], 'OTA exceeds the pinned size')
                output.write(chunk)
                if time.monotonic() - notified >= 10:
                    print(f'OTA downloaded: {total // (1024*1024)} MiB', flush=True)
                    notified = time.monotonic()
        partial.replace(destination)
    require(destination.stat().st_size == NEW_PROFILE['ota_size'] and digest(destination) == NEW_PROFILE['ota_sha256'],
            'OTA integrity check failed; no installation permitted')
    with zipfile.ZipFile(destination) as archive:
        properties = dict(line.split('=', 1) for line in archive.read('payload_properties.txt').decode().splitlines())
        require(properties == NEW_PROFILE['payload_properties'], 'Payload properties changed')
        member = archive.getinfo('payload.bin')
        require(member.compress_type == zipfile.ZIP_STORED and member.file_size == NEW_PROFILE['payload_size'],
                'Unexpected OTA payload layout')
        with destination.open('rb') as raw:
            raw.seek(member.header_offset)
            header = raw.read(30)
            offset = member.header_offset + 30 + sum(struct.unpack_from('<HH', header, 26))
            require(offset == NEW_PROFILE['payload_offset'], 'Unexpected payload offset')
            raw.seek(offset)
            metadata = raw.read(NEW_PROFILE['payload_metadata_size'])
        require(len(metadata) == NEW_PROFILE['payload_metadata_size'] and metadata[:4] == b'CrAU', 'Invalid payload metadata')
    (run / 'payload-metadata.bin').write_bytes(metadata)
    return destination


def setup_state(device):
    require(device.shell('settings get secure user_setup_complete').stdout.strip() == '1' and
            device.shell('settings get global device_provisioned').stdout.strip() == '1', 'Finish Android setup first')
    packages = sorted(line[8:] for line in device.shell('pm list packages -3').stdout.splitlines() if line.startswith('package:'))
    home = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME').stdout.splitlines()
    require(packages and home and '/' in home[-1], 'Could not inventory apps and home launcher')
    return {'packages': packages, 'home': home[-1], 'android_id_hash': device.binding()}


def pause_modules(device, run):
    modules = []
    for path in MODULES:
        exists = device.root(f'if test -d {path}; then echo present; else echo absent; fi').stdout.strip()
        require(exists in ('present', 'absent'), 'Ambiguous OTA module state')
        if exists == 'absent':
            continue
        device.root(f'test ! -e {path}/remove && test ! -d {path}/.applying')
        enabled = device.root(f'if test -e {path}/disable; then echo disabled; else echo enabled; fi').stdout.strip()
        require(enabled in ('enabled', 'disabled'), 'Unknown module state')
        files = {}
        for name in ('pause.sh', 'restore-state.sh'):
            content = device.root(f'cat {path}/{name}').stdout
            local = run / (path.rsplit('/', 1)[1] + '-' + name)
            local.write_text(content)
            files[name] = {'file': local.name, 'sha256': digest(local)}
        modules.append({'path': path, 'enabled': enabled == 'enabled', 'files': files})
    return modules


def prepare(args):
    require(args.target, '--prepare requires --target IP:PORT')
    require(not CURRENT.exists(), 'An update run exists. Use --status/--verify; never replace an ambiguous attempt.')
    target = target_value(args.target)
    require(digest(ROOT / 'tools/linux/adb') == PROFILE['adb_sha256'], 'ADB binary changed')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run = WORK / 'firmware-updates' / run_id
    run.mkdir(parents=True, mode=0o700)
    config = {'run_id': run_id, 'target': target}
    device = UpdateDevice(config, run)
    device.preflight('unlocked')
    props = discovery.parse_properties(device.shell('getprop').stdout)
    report = {'version': 1, 'run_id': run_id, 'started_at': now(), 'stage': 'preparing',
              'hardware_identity': discovery.device_identity(props), 'device_binding': device.binding(),
              'boot_id_before': device.boot_id(), 'source_fingerprint': PROFILE['fingerprint'],
              'target_fingerprint': NEW_PROFILE['fingerprint'], 'reset_requested': False, 'relock_requested': False,
              'flash_attempted': False, 'reboot_requested': False}
    device.guard(report)
    require('Update state: none\n' in snapshot_state(device), 'A snapshot update is pending; finish it before preparing another')
    before = ota_updates.snapshot(device, require_idle=True)
    usage = discovery.parse_df(device.root('df -k /data').stdout)
    require(usage['free'] >= 4 * 1024**3, 'Free at least 4 GiB on the device')
    require(shutil.disk_usage(run).free >= max(8 * 1024**3, usage['size'] - usage['free'] + 4 * 1024**3),
            'Insufficient host space for the live setup backup plus OTA and boot backups')
    report.update(policy_before=before, setup_before=setup_state(device), modules=pause_modules(device, run))
    save(CURRENT, config)
    save(run / 'receipt.json', report)
    print('Checking normal startup and saving boot/recovery backups.',flush=True)
    device.check_startup(install=True)
    device.shell('test ! -e ' + device.remote + ' && mkdir ' + device.remote + ' && chmod 700 ' + device.remote)
    for name in ('boot_a', 'boot_b', 'vendor_boot_a', 'vendor_boot_b', 'vbmeta_a', 'vbmeta_b', 'misc', 'env'):
        print('Saving recovery backup: '+name,flush=True)
        size = int(device.root('blockdev --getsize64 /dev/block/by-name/' + name).stdout.strip())
        require(size <= 100663296 and size > 0, 'Unexpected backup partition size')
        output = run / ('backup-' + name + '.img')
        expected = device.root('sha256sum /dev/block/by-name/' + name, timeout=90).stdout.split()[0]
        device.stream('cat /dev/block/by-name/' + name + ' 2>/dev/null', output, timeout=180)
        require(output.stat().st_size == size and digest(output) == expected, 'Partition backup failed: ' + name)
    print('Backing up installed apps, settings and local media. Keep power/network connected.', flush=True)
    backup = run / 'setup-backup.tar'
    command = ('tar -cf - -C /data ' + ' '.join(BACKUP_TREES) + ' 2>' + device.remote + '/backup-errors; '
               'rc=$?; printf "%s\\n" "$rc" > ' + device.remote + '/backup-status')
    device.stream(command, backup)
    result = verify_tar_diagnostics(device.root('cat ' + device.remote + '/backup-status').stdout.strip(),
                                    device.root('cat ' + device.remote + '/backup-errors').stdout)
    result.update(validate_backup(backup))
    save(run / 'setup-backup.json', result)
    print('Setup backup validated. Preparing the exact signed OTA.',flush=True)
    ota = prepare_ota(run, args.ota_file)
    from onn import extract_magisk
    print('Preparing Magisk tools and the new stock boot image.',flush=True)
    tools = run / 'patch-tools'
    extract_magisk(tools)
    stock_gzip = ROOT / 'firmware/stock-boot-16202347.img.gz'
    require(digest(stock_gzip) == NEW_PROFILE['stock_boot_gzip_sha256'], 'New stock boot archive changed')
    stock = gzip.decompress(stock_gzip.read_bytes())
    require(hashlib.sha256(stock).hexdigest() == NEW_PROFILE['stock_boot_sha256'], 'Wrong new stock boot')
    (run / 'stock-boot.img').write_bytes(stock)
    with tarfile.open(run / 'patch-tools.tar', 'w') as archive:
        for path in sorted(tools.iterdir()):
            archive.add(path, arcname=path.name, recursive=False)
    for path, name in ((run/'patch-tools.tar','patch-tools.tar'), (run/'stock-boot.img','input-boot.img'),
                       (stock_gzip,'stock-boot.img.gz'), (ota,'update.zip'), (run/'payload-metadata.bin','payload-metadata.bin')):
        device.call('push', str(path), device.remote + '/' + name, timeout=300)
        require(device.root('sha256sum ' + device.remote + '/' + name, timeout=120).stdout.split()[0] == digest(path),
                'Upload hash mismatch: ' + name)
    patch_script = f'''set -eu
cd {device.remote}
mkdir patch
tar -xf patch-tools.tar -C patch
mv input-boot.img patch/input-boot.img
cd patch
chmod 755 ./*
set +eu
export BOOTMODE=true
. ./util_functions.sh
TMPDIR={device.remote}/patch/work-tmp
mkdir -p "$TMPDIR"
api_level_arch_detect
export SOURCEDMODE=true KEEPVERITY=true KEEPFORCEENCRYPT=true
export PATCHVBMETAFLAG=false RECOVERYMODE=false LEGACYSAR=false
. ./boot_patch.sh input-boot.img
chmod 644 new-boot.img
'''
    (run/'patch.sh').write_text(patch_script)
    device.call('push', str(run/'patch.sh'), device.remote+'/patch.sh')
    print('Creating your new root image on your device; no firmware write yet.',flush=True)
    # Match the on-device invocation used in the measured update, using Magisk's shell.
    device.root(f'cd {device.remote}; mkdir bootstrap; tar -xf patch-tools.tar -C bootstrap; chmod 755 bootstrap/busybox; '
                f'ASH_STANDALONE=1 ./bootstrap/busybox sh {device.remote}/patch.sh', timeout=180)
    device.call('pull', device.remote+'/patch/new-boot.img', str(run/'patched-boot.img'), timeout=120)
    validate_patched_image(stock, (run/'patched-boot.img').read_bytes(), NEW_PROFILE)
    save(run/'patch.json', {'patched_on_target': True, 'device_binding': report['device_binding'],
                           'sha256': digest(run/'patched-boot.img'), 'kernel_unchanged': True})
    device.root(f'mkdir -p {device.ota}; chmod 755 {device.ota}; '
                f'mv {device.remote}/update.zip {device.remote}/payload-metadata.bin {device.ota}/; '
                f'chmod 644 {device.ota}/*; restorecon -R {device.ota}')
    engine_start(device)
    try:
        require(engine_status(device) == 0, 'Updater is not idle')
        verified = device.root('/system/bin/update_engine_client --verify --metadata=' + device.ota + '/payload-metadata.bin')
        require('Payload is applicable.' in verified.stdout + verified.stderr, 'Native OTA applicability not proved')
    finally:
        if before['engine'] == 'stopped' and engine_status(device) == 0:
            device.root('setprop ctl.stop update_engine')
    device.guard(report)
    print('Checking the new root image and native OTA applicability.',flush=True)
    report.update(stage='prepared', prepared_at=now(), backup_verified=True, payload_applicable=True,
                  patched_sha256=digest(run/'patched-boot.img'))
    save(run/'receipt.json',report)
    print('Preparation complete: backups, official OTA and target-generated Magisk image verified. No flash or reboot.')
    print('Next: python3 onn.py update-firmware --apply --accept-risk')


def quiet_automatic_updates(device, report):
    for module in report['modules']:
        if module['enabled']:
            device.root('test ! -e '+module['path']+'/disable && touch '+module['path']+'/disable')
    device.root('settings put global ota_disable_automatic_update 1\n'
                'pm disable-user --user 0 '+ota_updates.UPDATER+'\n'+
                '\n'.join('pm disable --user 0 '+c for c in ota_updates.COMPONENTS), timeout=90)
    expected = ota_updates.expected_paused(report['policy_before'])
    expected['engine'] = 'running'
    require(ota_updates.snapshot(device) == expected, 'Could not suspend automatic update controls')


def verify_new_slot(device):
    for name, expected in NEW_PROFILE['physical_partition_images'].items():
        result = device.root(f'set -o pipefail; head -c {expected["size"]} /dev/block/by-name/{name}_a | sha256sum', timeout=90)
        require(result.stdout.split()[0] == expected['sha256'], 'New stock partition verification failed: '+name)
    a,b = read_boot_control(device)
    require(a['priority'] > b['priority'] and a['tries'] > 0 and not a['corrupt'] and b['successful'],
            'Native updater did not select a valid new slot A')


def render_boot_installer(device, report):
    require(re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', report['boot_id_before']), 'Invalid boot ID')
    require(re.fullmatch(r'/data/local/tmp/onn-firmware-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', device.remote), 'Invalid staging path')
    return (ROOT/'tools/apply-updated-boot-a.sh.in').read_text().replace('@DEVICE_DIR@',device.remote).replace('@EXPECTED_BOOT_ID@',report['boot_id_before'])


def install_new_root(device, report):
    device.guard(report)
    require(engine_status(device) == 6, 'OTA is not ready for reboot')
    verify_new_slot(device)
    device.root('printf "%s\\n" 16202347 > '+device.remote+'/ota-completed-and-verified')
    script = device.run/'apply-updated-boot-a.sh'
    script.write_text(render_boot_installer(device, report))
    device.call('push', str(script), device.remote+'/apply-updated-boot-a.sh')
    require(device.root('sha256sum '+device.remote+'/apply-updated-boot-a.sh').stdout.split()[0] == digest(script), 'Installer upload changed')
    report.update(stage='root-write-attempted', root_flash_attempted=True)
    save(device.run/'receipt.json',report)
    result = device.root('/system/bin/sh '+device.remote+'/apply-updated-boot-a.sh apply-authorized',timeout=180,check=False)
    (device.run/'root-flash.log').write_text(result.stdout+result.stderr)
    require(result.returncode == 0 and 'NEW_BOOT_A_ROOT_IMAGE_READBACK_VERIFIED' in result.stdout,
            'Root write unverified. KEEP POWER ON. Do not reboot or retry; inspect root-flash.log.')
    report.update(stage='ready-to-reboot', root_flash_verified=True)
    save(device.run/'receipt.json',report)


def apply(device, report):
    require(report['stage'] in ('prepared','ota-verified'), 'An update/write attempt already exists; use --verify, never blindly replay --apply')
    device.guard(report)
    device.check_startup()
    if report['stage'] == 'prepared':
        require(report.get('backup_verified') and read(device.run/'setup-backup.json')['complete_archive_verified'], 'Missing valid setup backup')
        require(read(device.run/'patch.json')['device_binding'] == device.binding() and
                digest(device.run/'patched-boot.img') == NEW_PROFILE['expected_patched_sha256'], 'Patch binding/hash mismatch')
        require('Update state: none\n' in snapshot_state(device), 'Another update is pending')
        engine_start(device)
        require(engine_status(device) == 0, 'Update engine is not idle')
        report.update(stage='ota-attempted', flash_attempted=True)
        save(device.run/'receipt.json',report)
        device.root('mkdir '+device.remote+'/ota-attempt')
        quiet_automatic_updates(device, report)
        headers='\n'.join(k+'='+v for k,v in NEW_PROFILE['payload_properties'].items())+'\nPOWERWASH=0\nSWITCH_SLOT_ON_REBOOT=1'
        command=shlex.join(['/system/bin/update_engine_client','--update','--follow',
                           '--payload=file://'+device.ota+'/update.zip','--offset='+str(NEW_PROFILE['payload_offset']),
                           '--size='+str(NEW_PROFILE['payload_size']),'--headers='+headers])
        code = follow_updater(device, command)
        text=(device.run/'ota-application.log').read_text()
        require(code==0 and 'onPayloadApplicationComplete(ErrorCode::kSuccess (0))' in text,
                'OTA completion unverified. Do not retry or reboot; use --verify and inspect the log.')
        report.update(stage='ota-verified', native_ota_success=True)
        save(device.run/'receipt.json',report)
    install_new_root(device,report)
    print('New OTA and Magisk boot_a readback verified. No reboot requested.')
    print('Next: python3 onn.py update-firmware --reboot --accept-risk')


def reboot(device, report):
    require(report['stage']=='ready-to-reboot' and report.get('root_flash_verified'), 'No fully verified new-slot installation')
    require(not report.get('reboot_requested'), 'Reboot already requested; approve debugging and use --verify')
    device.guard(report)
    device.check_startup()
    require(engine_status(device)==6, 'Updater is not ready for reboot')
    require(device.root('sha256sum /dev/block/by-name/boot_a',timeout=90).stdout.split()[0] == NEW_PROFILE['expected_patched_sha256'], 'New boot_a changed; do not reboot')
    a,b=read_boot_control(device)
    require(a['priority']>b['priority'] and a['tries']>0 and not a['corrupt'], 'Unexpected selected slot')
    print('Rebooting once. Approve USB debugging again if the device asks.',flush=True)
    report['reboot_requested']=True
    save(device.run/'receipt.json',report)
    try:
        device.call('reboot',timeout=10,check=False)
    except subprocess.SubprocessError:
        pass  # A disconnected client is not permission for a second reboot.
    started=time.monotonic()
    while time.monotonic()-started < 480:
        print(f'Waiting for Android and debugging authorization ({round(time.monotonic()-started)} seconds).',flush=True)
        try:
            device.call('connect',device.config['target'],timeout=8,check=False)
            if device.boot_id()!=report['boot_id_before'] and device.property('sys.boot_completed')=='1':
                report.update(android_returned=True,boot_id_after=device.boot_id())
                save(device.run/'receipt.json',report)
                break
        except (RuntimeError,subprocess.SubprocessError):
            pass
        time.sleep(10)
    else:
        raise RuntimeError('Reboot verification timed out. Approve debugging, adjust --set-target if needed, then --verify. Do not repeat the reboot.')
    print('Android returned. Next: python3 onn.py update-firmware --verify')


def update_progress(line):
    match=re.search(r'onStatusUpdate\(UPDATE_STATUS_([A-Z_]+) \(\d+\), ([\d.eE+-]+)\)',line)
    if not match: return None
    phase,value=match.groups()
    labels={'IDLE':'Starting updater','UPDATE_AVAILABLE':'Preparing firmware',
            'CLEANUP_PREVIOUS_UPDATE':'Preparing snapshots','DOWNLOADING':'Installing firmware',
            'VERIFYING':'Verifying firmware','FINALIZING':'Finalizing installation',
            'UPDATED_NEED_REBOOT':'Installation complete; reboot has not been requested'}
    label=labels.get(phase,phase.replace('_',' ').capitalize())
    return label+(f': {round(float(value)*100)}%' if phase in ('DOWNLOADING','VERIFYING','FINALIZING') else '')


def follow_updater(device,command):
    lines=queue.Queue()
    process=subprocess.Popen(device.adb+['shell','/debug_ramdisk/su -c '+shlex.quote(command)],
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    def receive():
        try:
            for line in process.stdout: lines.put(line)
        finally:
            process.stdout.close(); lines.put(None)
    reader=threading.Thread(target=receive,daemon=True)
    reader.start()
    previous=None
    with (device.run/'ota-application.log').open('x') as log:
        while True:
            try:
                line=lines.get(timeout=15)
            except queue.Empty:
                print('Updater is still working; keep power connected. Do not start another update.',flush=True)
                continue
            if line is None: break
            log.write(line); log.flush()
            message=update_progress(line)
            if message and message!=previous:
                print(message,flush=True); previous=message
            elif 'onPayloadApplicationComplete' in line:
                print(line.rstrip(),flush=True)
    reader.join()
    return process.wait()


def migrate_pause_module(device, module):
    # Existing pause scripts may be pinned to the old fingerprint. Change only
    # that literal after checking their saved bytes; do not loosen the guard.
    for name, item in module['files'].items():
        content=(device.run/item['file']).read_text()
        updated=content.replace(PROFILE['fingerprint'],NEW_PROFILE['fingerprint'])
        target=module['path']+'/'+name
        actual=device.root('sha256sum '+target).stdout.split()[0]
        changed_hash=hashlib.sha256(updated.encode()).hexdigest()
        require(actual in (item['sha256'],changed_hash), 'OTA pause module changed during update')
        if actual != changed_hash:
            local=device.run/('updated-'+Path(item['file']).name)
            local.write_text(updated)
            remote=device.remote+'/updated-'+name
            device.call('push',str(local),remote)
            require(device.root('sha256sum '+remote).stdout.split()[0]==changed_hash, 'Module upload mismatch')
            device.root('cat '+remote+' > '+target+' && chmod 700 '+target)
        item['updated_sha256']=changed_hash


def restore_policy(device, report):
    require('Update state: none\n' in snapshot_state(device) and engine_status(device)==0,
            'Snapshot merge and idle updater are required before restoring update policy')
    before=report['policy_before']
    actions={0:'default-state',1:'enable',2:'disable',3:'disable-user',4:'disable-until-used'}
    commands=['set -eu']
    for component in ota_updates.COMPONENTS:
        value=before['packages'][ota_updates.GMS]['components'][component]
        require(type(value) is int and value in (0,1,2), 'Invalid saved component state')
        commands.append('pm '+actions[value]+' --user 0 '+component)
    value=before['packages'][ota_updates.UPDATER]['enabled']
    require(type(value) is int and value in actions, 'Invalid saved updater state')
    commands.append('pm '+actions[value]+' --user 0 '+ota_updates.UPDATER)
    require(before['setting'] in ('null','0','1'), 'Invalid saved OTA setting')
    commands.append('settings '+('delete global ota_disable_automatic_update' if before['setting']=='null' else
                                 'put global ota_disable_automatic_update '+before['setting']))
    device.root('\n'.join(commands),timeout=90)
    for module in report['modules']:
        migrate_pause_module(device,module)
        if module['enabled']:
            device.root('rm -f '+module['path']+'/disable')
    if before['engine']=='stopped':
        device.root('setprop ctl.stop update_engine')
        for _ in range(10):
            if device.property('init.svc.update_engine')=='stopped': break
            time.sleep(1)
    require(ota_updates.snapshot(device)==before, 'Original OTA policy was not fully restored')
    report['ota_policy_restored']=True
    save(device.run/'receipt.json',report)


def associate_original_run(device, report):
    """Keep the original guide's OTA controls usable without reusing its flash receipts."""
    if not (WORK/'current.json').exists(): return
    from onnlib import configuration
    config,run=configuration()
    install=run/'install/receipt.json'
    if not install.exists(): return
    installed=read(install)
    proof=run/'permanent-root-proof.json'
    if (installed.get('device_binding') != report['device_binding'] or not installed.get('flash_verified')
            or not proof.exists() or not read(proof).get('permanent_root_proven')): return
    for module in report['modules']:
        receipt_path=run/'updates/receipt.json'
        if module['path'] != ota_updates.MODULE or not receipt_path.exists(): continue
        saved=read(receipt_path)
        require(device.root('cat '+ota_updates.MODULE+'/owner').stdout.strip()==saved['owner'], 'Original guide OTA owner changed')
        for name,item in module['files'].items():
            content=(device.run/item['file']).read_text().replace(PROFILE['fingerprint'],NEW_PROFILE['fingerprint'])
            (run/'updates/module'/name).write_text(content)
            saved['files'][name]=item['updated_sha256']
        save(receipt_path,saved)
    config.update(firmware_mode='updated-16202347',active_slot='_a',target=device.config['target'])
    save(run/'configuration.json',config); save(WORK/'current.json',config)
    save(run/'firmware-update-proof.json',{'verified':True,'device_binding':report['device_binding'],
                                         'update_run_id':report['run_id'],'fingerprint':NEW_PROFILE['fingerprint'],
                                         'boot_id':device.boot_id(),'boot_sha256':NEW_PROFILE['expected_patched_sha256']})


def verify(device,report):
    fingerprint=device.property('ro.build.fingerprint')
    if fingerprint == PROFILE['fingerprint']:
        device.guard(report)
        require(report.get('flash_attempted'), 'No update was applied; use --status')
        engine_start(device)
        require(engine_status(device)==6, 'OTA is not complete; keep power on, inspect logs and do not retry')
        actual=device.root('sha256sum /dev/block/by-name/boot_a',timeout=90).stdout.split()[0]
        if actual == NEW_PROFILE['stock_boot_sha256'] and not report.get('root_flash_attempted'):
            verify_new_slot(device)
            report.update(stage='ota-verified',native_ota_success=True)
            save(device.run/'receipt.json',report)
            print('Completed stock OTA verified. Continue root installation only with --apply --accept-risk.')
            return
        require(actual==NEW_PROFILE['expected_patched_sha256'] and report.get('root_flash_attempted'),
                'New boot is unverified. Do not reboot, retry or reset; inspect receipts.')
        # Independently establish write success after a lost client response.
        report.update(stage='ready-to-reboot',root_flash_verified=True)
        save(device.run/'receipt.json',report)
        print('New boot_a matches the expected root image. Use --reboot --accept-risk once; do not rerun the flash.')
        return
    require(fingerprint==NEW_PROFILE['fingerprint'], 'Unexpected firmware; stop without further changes')
    require(report.get('root_flash_attempted'), 'Missing record of this update root installation')
    properties=device.guard(report,new=True)
    require(device.root('sha256sum /dev/block/by-name/boot_b',timeout=90).stdout.split()[0]==PROFILE['expected_patched_sha256'], 'Old boot_b changed')
    control=read_boot_control(device)
    require(control[0]['successful'] and not control[0]['corrupt'], 'Android has not marked the new slot successful')
    if report['stage']=='complete':
        print('Completed update, exact new boot image, unlocked state and root verified again. No changes made.')
        return
    engine_start(device)
    deadline=time.monotonic()+900
    while True:
        state=snapshot_state(device)
        (device.run/'snapshot-final.log').write_text(state)
        if 'Update state: none\n' in state: break
        require(time.monotonic()<deadline, 'Snapshot merge is still pending; keep power connected and resume --verify')
        if 'Update state: unverified\n' in state and not report.get('merge_requested'):
            report['merge_requested']=True; save(device.run/'receipt.json',report)
            # This is Android's successful-update cleanup, not a slot switch.
            device.root('timeout 8 /system/bin/update_engine_client --merge',timeout=15,check=False)
        print(next((s for s in state.splitlines() if s.startswith('Merge completion:')),state.splitlines()[0]),flush=True)
        time.sleep(5)
    require(engine_status(device)==0, 'Updater not idle after merge; resume --verify later')
    backup='/data/magisk_backup_'+NEW_PROFILE['stock_boot_sha1']
    device.root(f'''set -eu
set -o pipefail
mkdir -p {backup}
chmod 700 {backup}
if test ! -e {backup}/boot.img.gz; then cp {device.remote}/stock-boot.img.gz {backup}/boot.img.gz; fi
chmod 600 {backup}/boot.img.gz
restorecon -R {backup}
[ "$(gzip -dc {backup}/boot.img.gz | sha256sum | cut -d ' ' -f 1)" = {NEW_PROFILE['stock_boot_sha256']} ]
''',timeout=90)
    after=setup_state(device)
    preserved=(after['home']==report['setup_before']['home'] and after['android_id_hash']==report['device_binding'] and
               set(report['setup_before']['packages']) <= set(after['packages']))
    report.update(properties_after=properties,setup_after=after,setup_preserved=preserved,
                  snapshot_merge_complete=True,root_verified=True,existing_unlock_preserved=True,
                  fresh_unlock_tested=False,boot_id_after=device.boot_id())
    save(device.run/'receipt.json',report)
    restore_policy(device,report)
    associate_original_run(device,report)
    require(preserved, 'Update/root verified, but apps/launcher inventory differs. OTA policy restored; inspect receipt, do not reset.')
    report.update(stage='complete',completed_at=now(),pending_device_actions=[])
    save(device.run/'receipt.json',report)
    print('16202347 update verified: Magisk root, existing unlock, apps and launcher preserved.')
    print('Snapshot merge complete; original OTA policy restored. No factory reset or relock was requested.')
    print('Keep the private backup and receipts: '+str(device.run))


def dispatch(args):
    if not any(getattr(args,k,False) for k in ('prepare','apply','reboot','verify','status','set_target')):
        from wizard import Paused
        try:
            guide()
        except Paused:
            print('Exited. Saved update receipts are preserved; resume with update-firmware.')
        return
    if args.status:
        if not CURRENT.exists(): print('No saved firmware update.'); return
        device,report=saved_update()
        print(json.dumps({'stage':report['stage'],'target_build':'16202347','receipts':str(device.run),
                          'reboot_requested':report.get('reboot_requested',False),
                          'ota_policy_restored':report.get('ota_policy_restored',False)},indent=2)); return
    require(not (args.apply or args.reboot) or args.accept_risk, 'Read docs/FIRMWARE_UPDATE.md and supply --accept-risk')
    with operation_lock():
        if args.prepare:
            print(WARNING); prepare(args); return
        device,report=saved_update()
        if args.set_target:
            config={**device.config,'target':target_value(args.set_target)}
            save(CURRENT,config)
            print('Saved update address changed locally; the next command verifies the same device and Android installation.'); return
        if args.apply: apply(device,report)
        elif args.reboot: reboot(device,report)
        elif args.verify: verify(device,report)


def guide():
    from wizard import ask, confirm, select_box
    print(WARNING)
    if not CURRENT.exists():
        confirm('Prepare the update: check your already-rooted source device, save private backups,\n'
                'download the pinned OTA and patch its new boot on your box. No flash or reboot yet.', 'PREPARE UPDATE')
        box=select_box(ROOT/'tools/linux/adb')
        args=SimpleNamespace(target=box['target'],ota_file=None)
        with operation_lock(): prepare(args)
    while True:
        device,report=saved_update()
        print('Update step: '+report['stage']+'\nPrivate receipts: '+str(device.run))
        if report['stage']=='complete': return
        if report['stage'] in ('prepared','ota-verified'):
            confirm('Install the signed OTA, preserve userdata, then write and verify the new slot A root image.\n'
                    'This writes internal flash and can permanently brick the device. Keep normal power connected.\n'
                    'No automatic reboot will occur during this step.', 'INSTALL UPDATE AT MY OWN RISK')
            with operation_lock(): apply(device,report)
        elif report['stage']=='ready-to-reboot' and not report.get('reboot_requested'):
            confirm('Reboot once into the verified new firmware. Approve USB debugging again if prompted.', 'REBOOT')
            with operation_lock(): reboot(device,report)
        else:
            confirm('Approve debugging on the same box. Verify the saved attempt without replaying a write.\n'
                    'After a successful new boot, finish Android snapshot merge and restore the saved OTA policy.\n'
                    'If the address changed, leave and use update-firmware --set-target IP:PORT.', 'VERIFY')
            with operation_lock(): verify(device,report)
