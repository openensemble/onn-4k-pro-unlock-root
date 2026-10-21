"""Shared, guarded operations for the exact tested onn firmware."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'work'
PROFILE = json.loads((ROOT / 'firmware/tested-profile.json').read_text())


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def verify_files():
    manifest = read(ROOT / 'MANIFEST.json')['files']
    for name, expected in manifest.items():
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT), 'Unsafe manifest path')
        require(path.is_file() and digest(path) == expected, 'File changed or missing: ' + name)
    return len(manifest)


def target_value(value):
    host, separator, port = value.rpartition(':')
    require(separator and port.isdecimal(), 'Use an IPv4 address and ADB port, such as 192.0.2.10:5555')
    ipaddress.IPv4Address(host)
    require(1 <= int(port) <= 65535, 'Invalid ADB port')
    return host + ':' + str(int(port))


def usb_value(value):
    require(re.fullmatch(r'[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}', value), 'Thumb drive UUID must look like ABCD-1234')
    return value.upper()


def configuration():
    config = read(WORK / 'current.json')
    require(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', config['run_id']), 'Invalid run ID')
    target_value(config['target'])
    usb_value(config['usb_uuid'])
    run = WORK / 'runs' / config['run_id']
    require(run.is_dir(), 'Run directory missing; do not recreate a previous test')
    return config, run


def refresh_kit_manifest(kit):
    files = {}
    for path in sorted(kit.rglob('*')):
        relative = path.relative_to(kit)
        if (path.is_file() and path.name != 'checksums.json'
                and 'sessions' not in relative.parts and '__pycache__' not in relative.parts):
            files[str(relative)] = digest(path)
    save(kit / 'checksums.json', {'files': files})


def load_transport(kit):
    # Each command uses one kit at a time. Load its collector explicitly rather
    # than accidentally importing another kit's identically named module.
    spec = importlib.util.spec_from_file_location('collect_result', kit / 'collect_result.py')
    collector = importlib.util.module_from_spec(spec)
    sys.modules['collect_result'] = collector
    # Configured targets can change twice within one timestamp tick. Compile
    # current source directly so a same-size address edit cannot reuse stale pyc.
    exec(compile((kit / 'collect_result.py').read_bytes(), str(kit / 'collect_result.py'), 'exec'), collector.__dict__)
    spec = importlib.util.spec_from_file_location('kit_transport', kit / 'test_later.py')
    module = importlib.util.module_from_spec(spec)
    exec(compile((kit / 'test_later.py').read_bytes(), str(kit / 'test_later.py'), 'exec'), module.__dict__)
    return module


def sessions(kit, action='test'):
    return sorted(p.parent for p in (kit / 'sessions').glob('*/roundtrip.json')
                  if read(p).get('action') == action)


def latest_session(kit):
    found = sessions(kit)
    require(len(found) == 1, 'Expected exactly one saved test session in ' + str(kit))
    return found[0]


def check_properties(properties, state=None):
    required = {
        'ro.build.fingerprint': PROFILE['fingerprint'],
        'ro.bootloader': PROFILE['bootloader'],
        'ro.build.version.security_patch': PROFILE['security_patch'],
        'ro.boot.slot_suffix': PROFILE['active_slot'],
        'ro.product.first_api_level': PROFILE['first_api_level'],
        'ro.product.cpu.abi': PROFILE['abi'],
        'sys.boot_completed': '1',
    }
    if state:
        required.update({
            'ro.boot.flash.locked': '1' if state == 'locked' else '0',
            'ro.boot.vbmeta.device_state': state,
            'ro.boot.verifiedbootstate': 'green' if state == 'locked' else 'orange',
        })
    for name, expected in required.items():
        require(properties.get(name) == expected,
                f'Unsupported device/state: {name}={properties.get(name)!r}; expected {expected!r}. Stop; do not bypass this check.')


def validate_patched_image(stock, patched):
    require(len(stock) == len(patched) == PROFILE['stock_boot_size'], 'Unexpected boot image size')
    require(hashlib.sha256(stock).hexdigest() == PROFILE['stock_boot_sha256'], 'Wrong stock image')
    require(hashlib.sha256(patched).hexdigest() == PROFILE['expected_patched_sha256'],
            'Device-generated patched image differs from the tested layout. Stop; do not substitute another device\'s patched image.')
    require(patched[:8] == b'ANDROID!' and struct.unpack_from('<I', patched, 40)[0] == 4,
            'Unexpected Android boot header')
    kernel, ramdisk = struct.unpack_from('<II', patched, 8)
    require(kernel == struct.unpack_from('<I', stock, 8)[0], 'Kernel size changed')
    require(stock[4096:4096 + kernel] == patched[4096:4096 + kernel], 'Kernel bytes changed')
    magic, major, minor, length, _, _ = struct.unpack_from('>4sIIQQQ', patched, len(patched) - 64)
    aligned = lambda size: (size + 4095) & ~4095
    require(magic == b'AVBf' and major == 1, 'Unexpected AVB footer')
    require(length == 4096 + aligned(kernel) + aligned(ramdisk), 'Unexpected boot image layout')
    require(0x3000000 + length < 0x4000000, 'USB image would exceed the tested memory range')
    return patched[:length]


class Device:
    def __init__(self, config, run):
        self.config, self.run = config, run
        self.adb = [str(run / 'root/tools/adb'), '-s', config['target']]

    def call(self, *args, timeout=30, check=True):
        result = subprocess.run(self.adb + list(args), capture_output=True, text=True,
                                errors='replace', timeout=timeout)
        if check:
            require(result.returncode == 0, result.stdout + result.stderr)
        return result

    def shell(self, command, **kwargs):
        return self.call('shell', command, **kwargs)

    def root(self, command, **kwargs):
        return self.shell('/debug_ramdisk/su -c ' + shlex.quote(command), **kwargs)

    def property(self, name):
        return self.call('shell', 'getprop', name).stdout.strip()

    def boot_id(self):
        value = self.shell('cat /proc/sys/kernel/random/boot_id').stdout.strip()
        require(re.fullmatch(r'[0-9a-f-]{36}', value), 'Invalid boot ID')
        return value

    def binding(self):
        # Only a hash is saved locally; run/config files are ignored by Git.
        android_id = self.shell('settings get secure android_id').stdout.strip()
        require(re.fullmatch(r'[0-9a-fA-F]{16}', android_id), 'Cannot bind the patch to this Android installation')
        return hashlib.sha256(android_id.lower().encode()).hexdigest()

    def preflight(self, state=None):
        self.call('connect', self.config['target'], timeout=8, check=False)
        names = ['ro.build.fingerprint', 'ro.bootloader', 'ro.build.version.security_patch',
                 'ro.boot.slot_suffix', 'ro.product.first_api_level', 'ro.product.cpu.abi',
                 'sys.boot_completed', 'ro.boot.flash.locked', 'ro.boot.vbmeta.device_state',
                 'ro.boot.verifiedbootstate']
        properties = {name: self.property(name) for name in names}
        check_properties(properties, state)
        save(self.run / 'last-device-status.json', {'time': now(), 'properties': properties})
        return properties

    def transport(self, kind='root'):
        kit = self.run / kind
        module = load_transport(kit)
        receipt_dir = self.run / 'inspections' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        receipt_dir.mkdir(parents=True)
        return module.Device(module.verify_local(), receipt_dir, {})

    def inspect_startup(self, fresh=False, install=False, kind='root'):
        kit = self.run / kind
        apk = next((kit / 'build').glob('*.apk'))
        if install:
            self.call('install', '-r', str(apk), timeout=90)
        transport = self.transport(kind)
        report = transport.fresh(PROFILE['stock_startup']) if fresh else transport.action('INSPECT')
        require(report['before'] == PROFILE['stock_startup'], 'Unexpected startup command; use restore-startup before proceeding')
        return report

    def usb_present(self):
        path = '/storage/' + self.config['usb_uuid']
        result = self.shell('if test -d ' + path + '; then echo PRESENT; else echo ABSENT; fi').stdout.strip()
        require(result in ('PRESENT', 'ABSENT'), 'Ambiguous thumb drive mount result')
        return result == 'PRESENT'

    def read_partition(self, name, output):
        require(name == 'boot_b', 'Only the tested boot_b backup is supported')
        require(not output.exists(), 'Refusing to overwrite a boot backup')
        temporary = output.with_suffix('.img.partial')
        command = "/debug_ramdisk/su -c 'dd if=/dev/block/by-name/boot_b bs=1048576 count=96 2>/dev/null'"
        with temporary.open('xb') as dest:
            result = subprocess.run(self.adb + ['exec-out', command], stdout=dest,
                                    stderr=subprocess.PIPE, timeout=120)
        require(result.returncode == 0 and temporary.stat().st_size == PROFILE['stock_boot_size'], 'Incomplete boot backup')
        require(digest(temporary) == PROFILE['stock_boot_sha256'], 'Boot partition does not match the verified stock image')
        temporary.replace(output)

    def partition_hashes(self):
        result = self.root('sha256sum /dev/block/by-name/boot_a /dev/block/by-name/boot_b '
                           '/dev/block/by-name/vbmeta_b /dev/block/by-name/vendor_boot_b')
        hashes = {line.split()[1]: line.split()[0] for line in result.stdout.splitlines()
                  if re.match(r'^[0-9a-f]{64}  /dev/block/', line)}
        require(len(hashes) == 4, 'Incomplete partition hashes')
        return hashes

    def reboot_wait(self, report, receipt):
        require(not report.get('reboot_requested'), 'A reboot was already requested; do not issue another automatically')
        before = self.boot_id()
        report.update({'boot_id_before': before, 'reboot_requested': True})
        save(receipt, report)
        try:
            result = self.call('reboot', timeout=10, check=False)
            report['reboot_returncode'] = result.returncode
        except subprocess.TimeoutExpired:
            report['reboot_client_timeout'] = True
        save(receipt, report)
        deadline = time.monotonic() + 330
        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                value = self.boot_id()
                if value != before and self.property('sys.boot_completed') == '1':
                    report.update({'boot_id_after': value, 'android_returned': True})
                    save(receipt, report)
                    return
            except (RuntimeError, subprocess.SubprocessError):
                pass
            try:
                self.call('connect', self.config['target'], timeout=5, check=False)
            except subprocess.SubprocessError:
                pass
        raise RuntimeError('Android did not return. Do not repeat the write or reboot. Read docs/RECOVERY.md.')
