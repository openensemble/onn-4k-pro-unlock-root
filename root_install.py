"""Guarded boot_b installation. No automatic reboot or retry after a write."""
import re
import shutil
import tarfile

from onnlib import ROOT, PROFILE, digest, now, read, require, save

ENV_CHECK = '''MAGISKTMP=/debug_ramdisk
. /data/adb/magisk/app_functions.sh
. /data/adb/magisk/util_functions.sh
env_check 30.7 30700 || exit 1
echo MAGISK_ENVIRONMENT_VERIFIED
'''


def root_identity(device):
    result = device.root('id', timeout=55)
    require(re.search(r'\buid=0\(root\)', result.stdout), 'Root identity not proved')
    return result.stdout.strip()


def validate_temporary_proof(proof, boot_id, binding, marker):
    require(proof.get('root_proven') is True, 'Temporary root has not been proved')
    require(proof['boot_id'] == boot_id, 'Temporary-root boot changed; stop')
    require(proof['device_binding'] == binding, 'Temporary-root proof belongs to another installation')
    require(marker == 'ONN-MAGISK-26-20261021', 'Expected the tested USB root boot')


def check_partition_result(before, after):
    target = PROFILE['boot_target']
    require(after.get(target) == PROFILE['expected_patched_sha256'], 'Patched boot_b readback failed; do not reboot')
    require(set(before) == set(after) and len(before) == 4, 'Incomplete partition comparison')
    require(all(after[name] == value for name, value in before.items() if name != target),
            'Another partition changed; do not reboot')


def render_template(name, remote, boot_id):
    require(re.fullmatch(r'/data/local/tmp/onn-guide-install-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', remote),
            'Invalid staging path')
    require(re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', boot_id), 'Invalid boot ID')
    result = (ROOT / 'tools' / name).read_text().replace('@DEVICE_DIR@', remote).replace('@EXPECTED_BOOT_ID@', boot_id)
    require(not re.search(r'@[A-Z_]+@', result), 'Unresolved script placeholder')
    return result


def install(device, run, config):
    from onn import check_patch_binding, extract_magisk
    device.preflight('unlocked')
    patch = check_patch_binding(device, run)
    boot_id = device.boot_id()
    validate_temporary_proof(read(run / 'temporary-root-proof.json'), boot_id,
                             device.binding(), device.property('ro.boot.onn_rootprobe'))
    root_identity(device)
    device.inspect_startup(fresh=True)
    directory = run / 'install'
    require(not directory.exists(), 'An install preparation/attempt exists. Preserve it and inspect receipts; do not retry.')
    directory.mkdir()
    receipt_path = directory / 'receipt.json'
    remote = '/data/local/tmp/onn-guide-install-' + config['run_id']
    upload = remote + '-upload'
    receipt = {'started_at': now(), 'boot_id_before': boot_id,
               'device_binding': patch['device_binding'], 'remote_directory': remote,
               'flash_attempted': False, 'flash_verified': False, 'reboot_requested': False}
    save(receipt_path, receipt)
    device.read_partition('boot_b', directory / 'stock-boot-b.img')
    receipt['partition_hashes_before'] = device.partition_hashes()
    require(receipt['partition_hashes_before'][PROFILE['boot_target']] == PROFILE['stock_boot_sha256'],
            'boot_b is not the tested stock image')
    save(receipt_path, receipt)
    for template in ['apply-boot-b.sh.in', 'restore-stock-boot-b.sh.in']:
        (directory / template[:-3]).write_text(render_template(template, remote, boot_id))
    environment = directory / 'environment'
    extract_magisk(environment, complete=True)
    checksums = ''.join(digest(path) + '  ' + str(path.relative_to(environment)) + '\n'
                        for path in sorted(environment.rglob('*')) if path.is_file())
    (environment / 'SHA256SUMS').write_text(checksums)
    with tarfile.open(directory / 'magisk-environment.tar', 'w') as archive:
        for path in sorted(environment.rglob('*')):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(environment)), recursive=False)
    shutil.copy2(ROOT / 'firmware/stock-boot-15051976.img.gz', directory / 'stock-boot-b.img.gz')
    # Only an empty environment is supported, as in the original measured run.
    environment_script = f'''#!/system/bin/sh
set -eu
cd {remote}
mkdir environment
tar -xf magisk-environment.tar -C environment
cd environment
sha256sum -c SHA256SUMS
[ -d /data/adb/magisk ]
[ -z "$(ls -A /data/adb/magisk)" ] || {{ echo EXISTING_MAGISK_ENVIRONMENT_REQUIRES_REVIEW; exit 1; }}
cp -a . /data/adb/magisk/
chown -R 0:0 /data/adb/magisk
chmod -R 755 /data/adb/magisk
chmod 700 /data/adb
backup=/data/magisk_backup_{PROFILE['stock_boot_sha1']}
mkdir -p "$backup"
if [ ! -e "$backup/boot.img.gz" ]; then cp {remote}/stock-boot-b.img.gz "$backup/boot.img.gz"; fi
chmod 600 "$backup/boot.img.gz"
[ "$(gzip -dc "$backup/boot.img.gz" | sha256sum | cut -d ' ' -f 1)" = {PROFILE['stock_boot_sha256']} ]
{ENV_CHECK}
'''
    (directory / 'setup-environment.sh').write_text(environment_script)
    device.root('test ! -e ' + remote + ' && mkdir ' + remote + ' && chmod 700 ' + remote)
    device.shell('test ! -e ' + upload + ' && mkdir ' + upload + ' && chmod 700 ' + upload)
    inputs = {name: directory / name for name in ['stock-boot-b.img', 'stock-boot-b.img.gz',
               'apply-boot-b.sh', 'restore-stock-boot-b.sh', 'magisk-environment.tar', 'setup-environment.sh']}
    inputs['patched-boot-b.img'] = run / 'patched-boot.img'
    for name, path in inputs.items():
        device.call('push', str(path), upload + '/' + name, timeout=120)
        device.root('cp ' + upload + '/' + name + ' ' + remote + '/' + name +
                    ' && chown 0:0 ' + remote + '/' + name + ' && chmod 600 ' + remote + '/' + name)
        actual = device.root('sha256sum ' + remote + '/' + name).stdout.split()[0]
        require(actual == digest(path), 'Staged input hash mismatch: ' + name)
    check = device.root('sh ' + remote + '/apply-boot-b.sh check', timeout=120)
    require('ALL_INSTALL_GUARDS_PASSED' in check.stdout, 'Install guards did not pass')
    result = device.root('sh ' + remote + '/setup-environment.sh', timeout=120, check=False)
    (directory / 'environment.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0 and 'MAGISK_ENVIRONMENT_VERIFIED' in result.stdout,
            'Magisk environment setup failed. No boot partition was written; inspect environment.log.')
    device.inspect_startup(fresh=True)
    require(device.boot_id() == boot_id, 'Boot changed before flash; stop')
    receipt['flash_attempted'] = True
    save(receipt_path, receipt)
    # Once only. A timeout is not permission to retry or reboot.
    result = device.root('sh ' + remote + '/apply-boot-b.sh apply-authorized', timeout=180, check=False)
    (directory / 'flash.log').write_text(result.stdout + result.stderr)
    receipt['flash_returncode'] = result.returncode
    save(receipt_path, receipt)
    require(result.returncode == 0 and 'PATCHED_BOOT_B_READBACK_VERIFIED' in result.stdout,
            'Flash not verified. DO NOT REBOOT or retry. Inspect flash.log and docs/RECOVERY.md.')
    after = device.partition_hashes()
    check_partition_result(receipt['partition_hashes_before'], after)
    receipt.update({'completed_at': now(), 'flash_verified': True, 'partition_hashes_after': after})
    save(receipt_path, receipt)
    print('boot_b written and read back correctly; other checked partitions unchanged. No reboot requested.')
    print('Remove the thumb drive, then: python3 onn.py verify-root --reboot --usb-removed')


def saved_install(device, run):
    receipt = read(run / 'install/receipt.json')
    require(receipt['device_binding'] == device.binding(), 'Install receipt belongs to another Android installation')
    expected = '/data/local/tmp/onn-guide-install-' + device.config['run_id']
    require(receipt['remote_directory'] == expected, 'Unexpected install directory')
    return receipt


def verify(device, run, args):
    device.preflight('unlocked')
    installed = saved_install(device, run)
    require(installed.get('flash_verified') is True, 'A verified flash is required before rebooting')
    path = run / 'permanent-root-proof.json'
    report = read(path) if path.exists() else {'started_at': now(), 'permanent_root_proven': False}
    require(not device.usb_present(), 'Remove the thumb drive first')
    if args.reboot:
        require(args.usb_removed, 'Physically remove the thumb drive, then supply --usb-removed')
        require(device.boot_id() == installed['boot_id_before'], 'Device already rebooted; use verify-root without --reboot')
        root_identity(device)
        device.inspect_startup(fresh=True)
        check_partition_result(installed['partition_hashes_before'], device.partition_hashes())
        report['usb_removal_confirmed'] = True
        device.reboot_wait(report, path)
    device.preflight('unlocked')
    require(device.boot_id() != installed['boot_id_before'], 'Reboot verification needs a new boot')
    require(not device.usb_present(), 'The thumb drive is mounted; permanent-root proof requires it removed')
    require(device.property('ro.boot.onn_rootprobe') == '', 'Temporary USB boot marker is still present')
    identity = root_identity(device)
    startup = device.inspect_startup(fresh=True)
    after = device.partition_hashes()
    check_partition_result(installed['partition_hashes_before'], after)
    version = device.root('/debug_ramdisk/magisk -V').stdout.strip()
    require(version == str(PROFILE['magisk_version_code']), 'Unexpected running Magisk version')
    environment = device.root(ENV_CHECK)
    require('MAGISK_ENVIRONMENT_VERIFIED' in environment.stdout, 'Magisk environment not verified')
    report.update({'completed_at': now(), 'boot_id_after': device.boot_id(), 'root_identity': identity,
                   'stock_startup': startup['before'], 'partition_hashes_after': after,
                   'usb_volume_absent': True, 'temporary_boot_marker_absent': True,
                   'magisk_version_code': version, 'permanent_root_proven': True})
    save(path, report)
    print('Permanent root verified after a new boot, with the thumb drive absent and normal startup restored.')
    print(identity)


def restore(device, run):
    device.preflight('unlocked')
    receipt = saved_install(device, run)
    root_identity(device)
    path = run / 'install/restore-receipt.json'
    require(not path.exists(), 'A restore attempt exists; inspect it before any further write')
    script = receipt['remote_directory'] + '/restore-stock-boot-b.sh'
    local = run / 'install/restore-stock-boot-b.sh'
    require(device.root('sha256sum ' + script).stdout.split()[0] == digest(local), 'Restore script changed')
    report = {'started_at': now(), 'restore_attempted': True, 'restored': False, 'reboot_requested': False}
    save(path, report)
    result = device.root('sh ' + script + ' restore-authorized', timeout=180, check=False)
    (run / 'install/restore.log').write_text(result.stdout + result.stderr)
    report.update({'returncode': result.returncode, 'restored': result.returncode == 0 and
                  any(marker in result.stdout for marker in ['STOCK_ALREADY_PRESENT', 'STOCK_BOOT_B_RESTORED_AND_VERIFIED'])})
    save(path, report)
    require(report['restored'], 'Stock restore not verified. Do not reboot; inspect restore.log.')
    print('Stock boot_b restored and verified. Bootloader remains unlocked. No reboot requested.')
