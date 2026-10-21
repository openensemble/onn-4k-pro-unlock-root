"""Optional firmware OTA pause for an installation with verified permanent root."""
import copy
import re
import shlex
import tarfile
import uuid

from onnlib import ROOT, PROFILE, digest, now, read, require, save
from root_install import root_identity, saved_install

MODULE = '/data/adb/modules/onn_ota_pause'
SETTING = 'ota_disable_automatic_update'
GMS = 'com.google.android.gms'
UPDATER = 'com.onn.updatenotification'
STORE = 'com.android.vending'
COMPONENTS = [GMS + '/' + GMS + '.update.' + name for name in (
    'SystemUpdateService', 'SystemUpdateGcmTaskService', 'UpdateFromSdCardService',
    'SystemUpdatePersistentListenerService', 'UucNotificationReceiverService',
    'UpdateJobService', 'SystemUpdatePanoActivity', 'LegacySystemUpdatePanoActivity',
    'OtaPanoSetupActivity', 'LegacyOtaPanoSetupActivity', 'CompleteDialog')]
RESTORE = 'python3 onn.py restore-updates --apply'
MODULE_FILES = {'owner', 'before.json', 'module.prop', 'skip_mount', 'components.txt',
                'common.sh', 'pause.sh', 'service.sh', 'restore-state.sh'}


def package_state(output, package):
    # Use the active package's in-memory state, not the hidden factory APK or a
    # possibly stale package-restrictions.xml on disk. Only user 0 is changed.
    sections = re.findall(r'^Packages:\n((?:[ \t].*\n|\n)*)', output, re.M)
    require(len(sections) == 1, 'Cannot read current package state: ' + package)
    blocks = re.findall(r'^  Package \[' + re.escape(package) + r'\].*\n((?: {4}.*\n|\n)*)',
                        sections[0], re.M)
    require(len(blocks) == 1, 'Ambiguous package: ' + package)
    users = re.findall(r'^    User 0: ([^\n]*)\n((?: {6}.*\n|\n)*)', blocks[0], re.M)
    require(len(users) == 1 and 'installed=true' in users[0][0], 'Package missing for user 0: ' + package)
    state = re.search(r'\benabled=([0-4])\b', users[0][0])
    require(state is not None, 'Unknown package enabled state: ' + package)
    overrides = {}
    for label, value in [('enabledComponents', 1), ('disabledComponents', 2)]:
        for group in re.findall(r'^      ' + label + r':\n((?: {8}[^\n]+\n)*)', users[0][1], re.M):
            for name in group.splitlines():
                name = name.strip()
                require(name not in overrides, 'Ambiguous component override')
                overrides[name] = value
    return {'enabled': int(state[1]), 'components': {
        component: overrides.get(component.split('/', 1)[1], 0)
        for component in COMPONENTS if component.startswith(package + '/')}}


def snapshot(device, require_idle=False):
    packages = {package: package_state(device.root('dumpsys package ' + package).stdout, package)
                for package in (GMS, UPDATER, STORE)}
    setting = device.root('settings get global ' + SETTING).stdout.strip()
    require(setting in ('null', '0', '1'), 'Unexpected automatic-update setting; no change made')
    engine = device.property('init.svc.update_engine')
    require(engine in ('running', 'stopped'), 'Unknown update engine state')
    if require_idle and engine == 'running':
        status = device.root('timeout 4 /system/bin/update_engine_client --follow', timeout=10, check=False)
        events = re.findall(r'onStatusUpdate\(([^\r\n]*)', status.stdout + status.stderr)
        require(status.returncode in (0, 124) and events and events[-1].strip() == 'UPDATE_STATUS_IDLE (0), 0)',
                'An update is active, pending reboot, or its state is unknown. No pause applied.')
    return {'packages': packages, 'setting': setting, 'engine': engine}


def check_device(device, run):
    require(read(run / 'permanent-root-proof.json').get('permanent_root_proven') is True,
            'Verify permanent root before changing update settings')
    device.preflight('unlocked')
    installed = saved_install(device, run)
    require(installed.get('flash_verified') is True, 'Missing verified root installation')
    require(device.boot_id() != installed['boot_id_before'] and
            device.property('ro.boot.onn_rootprobe') == '', 'Permanent root must be running')
    root_identity(device)
    require(device.root('/debug_ramdisk/magisk -V').stdout.strip() == str(PROFILE['magisk_version_code']),
            'Unexpected Magisk version')
    return installed['device_binding']


def saved_receipt(device, run, binding):
    receipt = read(run / 'updates/receipt.json')
    require(receipt.get('version') == 1 and receipt.get('device_binding') == binding
            and receipt.get('run_id') == device.config['run_id'], 'Update backup belongs to a different installation')
    require(re.fullmatch(r'[a-f0-9]{32}', receipt['owner']), 'Invalid update backup owner')
    require(set(receipt['files']) == MODULE_FILES and
            all(re.fullmatch(r'[a-f0-9]{64}', value) for value in receipt['files'].values()),
            'Invalid OTA module file manifest')
    backup = run / 'updates/module/before.json'
    require(digest(backup) == receipt['files']['before.json'] and read(backup) == receipt['before'],
            'Saved update backup changed; preserve it for review')
    return receipt


def restore_script(before, owner):
    # All shell targets are fixed; only validated state numbers select commands.
    commands = ['#!/system/bin/sh', 'set -eu',
                '[ "$(/system/bin/getprop ro.build.fingerprint)" = ' + shlex.quote(PROFILE['fingerprint']) + ' ]',
                (ROOT / 'tools/ota-common.sh').read_text(),
                f'if [ -e {MODULE} ]; then',
                f'  [ "$(cat {MODULE}/owner)" = {shlex.quote(owner)} ]',
                f'  touch {MODULE}/disable', 'fi', 'attempt=0',
                f'while [ -d {MODULE}/.applying ]; do',
                '  attempt=$((attempt + 1))', '  [ "$attempt" -lt 30 ] || exit 1', '  sleep 1', 'done']
    require(before['engine'] in ('running', 'stopped'), 'Invalid saved engine state')
    if before['engine'] == 'stopped':
        commands.append('ensure_idle')
    actions = {0: 'default-state', 1: 'enable', 2: 'disable', 3: 'disable-user', 4: 'disable-until-used'}
    for component in COMPONENTS:
        value = before['packages'][GMS]['components'][component]
        require(type(value) is int and value in (0, 1, 2), 'Invalid saved component state')
        commands.append('/system/bin/pm ' + actions[value] + ' --user 0 ' + component)
    value = before['packages'][UPDATER]['enabled']
    require(type(value) is int and value in actions, 'Invalid saved updater state')
    commands.append('/system/bin/pm ' + actions[value] + ' --user 0 ' + UPDATER)
    require(before['setting'] in ('null', '0', '1'), 'Invalid saved update setting')
    commands.append('/system/bin/settings ' + ('delete global ' + SETTING if before['setting'] == 'null'
                    else 'put global ' + SETTING + ' ' + before['setting']))
    action = 'start' if before['engine'] == 'running' else 'stop'
    commands += [f'/system/bin/setprop ctl.{action} update_engine', 'wait_engine ' + before['engine'],
                 f'if [ -d {MODULE} ]; then touch {MODULE}/remove; fi', 'echo UPDATE_SETTINGS_RESTORED']
    return '\n'.join(commands) + '\n'


def expected_paused(before):
    result = copy.deepcopy(before)
    result.update(setting='1', engine='stopped')
    result['packages'][UPDATER]['enabled'] = 3
    result['packages'][GMS]['components'] = dict.fromkeys(COMPONENTS, 2)
    return result


def verify_paused(device, receipt):
    require(device.root(f'cat {MODULE}/owner').stdout.strip() == receipt['owner'], 'Different OTA pause module')
    device.root(f'test ! -e {MODULE}/disable && test ! -e {MODULE}/remove && test ! -d {MODULE}/.applying')
    result = device.root('sha256sum ' + ' '.join(MODULE + '/' + name for name in receipt['files']))
    actual = {line.split()[1]: line.split()[0] for line in result.stdout.splitlines() if len(line.split()) == 2}
    require(actual == {MODULE + '/' + name: value for name, value in receipt['files'].items()},
            'OTA pause module files differ from the saved installation')
    require(snapshot(device) == expected_paused(receipt['before']),
            'Firmware update pause is not fully verified. Inspect the log or restore with: ' + RESTORE)


def disable(device, run):
    binding = check_device(device, run)
    directory = run / 'updates'
    require(not directory.exists(), 'An update-settings attempt exists. Use updates-status or ' + RESTORE)
    device.root(f'test ! -e {MODULE}')
    before = snapshot(device, require_idle=True)
    require(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', device.config['run_id']), 'Invalid run ID')
    owner = uuid.uuid4().hex
    module = directory / 'module'
    module.mkdir(parents=True)
    (module / 'owner').write_text(owner + '\n')
    save(module / 'before.json', before)
    (module / 'module.prop').write_text('id=onn_ota_pause\nname=Onn firmware update pause\nversion=1\n'
                                      'versionCode=1\nauthor=OpenEnsemble\n'
                                      'description=Pauses firmware OTA updates. Use onn.py restore-updates to undo.\n')
    (module / 'skip_mount').touch()
    (module / 'components.txt').write_text('\n'.join(COMPONENTS) + '\n')
    (module / 'common.sh').write_text((ROOT / 'tools/ota-common.sh').read_text())
    (module / 'pause.sh').write_text((ROOT / 'tools/ota-pause.sh.in').read_text().replace('@FINGERPRINT@', PROFILE['fingerprint']))
    (module / 'service.sh').write_text((ROOT / 'tools/ota-service.sh').read_text())
    (module / 'restore-state.sh').write_text(restore_script(before, owner))
    files = {path.name: digest(path) for path in sorted(module.iterdir())}
    (module / 'SHA256SUMS').write_text(''.join(value + '  ' + name + '\n' for name, value in files.items()))
    (module / 'disable').touch()  # No boot-time action before installation is complete.
    receipt = {'version': 1, 'started_at': now(), 'device_binding': binding, 'run_id': device.config['run_id'],
               'owner': owner, 'before': before, 'files': files, 'pause_attempted': False, 'status': 'prepared'}
    path = directory / 'receipt.json'
    save(path, receipt)  # Save the original state before any device mutation.
    archive_path = directory / 'module.tar'
    with tarfile.open(archive_path, 'w') as archive:
        for item in sorted(module.iterdir()):
            archive.add(item, arcname=item.name, recursive=False)
    upload = '/data/local/tmp/onn-ota-' + device.config['run_id'] + '.tar'
    staging = '/data/adb/modules/.onn-ota-' + device.config['run_id']
    device.call('push', str(archive_path), upload, timeout=60)
    require(device.root('sha256sum ' + upload).stdout.split()[0] == digest(archive_path), 'OTA module upload changed')
    device.root(f'''set -eu
test ! -e {MODULE}
mkdir -p /data/adb/modules
mkdir {staging}
chmod 700 {staging}
tar -xf {upload} -C {staging}
cd {staging}
sha256sum -c SHA256SUMS
chown -R 0:0 .
chmod 600 ./*
chmod 700 ./*.sh
test ! -e {MODULE}
mv {staging} {MODULE}
''', timeout=60)
    receipt.update(pause_attempted=True, status='applying')
    save(path, receipt)
    result = device.root(f'rm {MODULE}/disable && /system/bin/sh {MODULE}/pause.sh', timeout=90, check=False)
    (directory / 'disable.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0 and 'FIRMWARE_UPDATES_PAUSED' in result.stdout,
            'Update pause did not finish. Restore the saved settings with: ' + RESTORE)
    verify_paused(device, receipt)
    receipt.update(status='disabled', completed_at=now())
    save(path, receipt)
    print('Automatic firmware updates disabled. Play Store app update settings are unchanged.')
    print('The Magisk module will reapply the pause at boot. No reboot was requested.')
    print('To restore the previous settings: ' + RESTORE)


def restore(device, run):
    binding = check_device(device, run)
    receipt = saved_receipt(device, run, binding)
    # Works even if the module was removed in Magisk; persistent package/settings
    # changes still need restoration. Never replace an unrelated module.
    receipt['status'] = 'restoring'
    save(run / 'updates/receipt.json', receipt)
    result = device.root(restore_script(receipt['before'], receipt['owner']), timeout=120, check=False)
    (run / 'updates/restore.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0 and 'UPDATE_SETTINGS_RESTORED' in result.stdout,
            'Restoration incomplete; inspect updates/restore.log and preserve the backup')
    require(snapshot(device) == receipt['before'], 'Previous update settings are not fully restored')
    receipt.update(status='restored', restored_at=now())
    save(run / 'updates/receipt.json', receipt)
    print('Previous firmware update settings restored. Pause module marked for removal; no reboot requested.')


def status(device, run):
    binding = check_device(device, run)
    receipt = saved_receipt(device, run, binding)
    require(receipt['status'] != 'restoring', 'Restoration was interrupted. Complete it with: ' + RESTORE)
    if receipt['status'] == 'restored':
        require(snapshot(device) == receipt['before'], 'Update settings changed since restoration')
        print('Previous firmware update settings restored.')
        return
    verify_paused(device, receipt)
    receipt.update(status='disabled', checked_at=now())
    save(run / 'updates/receipt.json', receipt)
    print('Automatic firmware updates are disabled; the boot module is enabled and its files verified.')
    print('To restore the previous settings: ' + RESTORE)
