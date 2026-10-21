"""Interactive front end to the existing guarded commands; Linux x86_64 only."""
from pathlib import Path
import platform
import queue
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace

import discovery
import onn
from onnlib import (ROOT, WORK, PROFILE, Device, configuration, digest, latest_session,
                    now, read, require, save, sessions, target_value)

INTRO = '''
onn. 4K Pro guided unlock and root

Earlier jarvis / SNA hardware only. The new 2026 model is NOT supported.
Only build URO4.260304.011.B1 / 15051976, bootloader 01.01.260304.175641,
March 2026 security patch, and active slot _b have been tested, on ONE unit.
The complete packaged workflow has not been tested end to end on hardware.

Unlocking will enter recovery and require a factory reset. This erases apps,
accounts, and settings. Startup experiments and internal flashing can brick the box;
recovery is not guaranteed. Back up anything you need before starting.

You need Linux x86_64, Python 3.10+, the Onn 4K Pro's normal power supply,
a trusted shared network, and a thumb drive with a FAT32 FIRST partition.
Have at least 1 GB free on the computer, Onn 4K Pro, and thumb drive. Know how
to use the Onn 4K Pro's stock recovery menu. This guide never formats a drive
or performs a factory reset.

On the Onn 4K Pro, go to Settings > System > About, then click
Android TV OS build 7 times to enable developer mode.
Then enable USB debugging in Developer options. Keep Android fully started.
Accept this computer's debugging authorization when it appears on the Onn 4K Pro.
Network ADB on port 5555 must be available; the guide cannot enable it remotely.

The guide finds the Onn 4K Pro and thumb drives, explains when to move the
thumb drive, and pauses before each reboot or write. To exit, type q and
press Enter at a prompt inside this guide. To resume later, run python3 onn.py
from the repository folder in your terminal. Do not delete work/ to force a retry.
'''

STEPS = '''
1. Find the exact supported Onn 4K Pro and select its mounted thumb drive.
2. Prepare empty capture folders, then perform one secure-state read/reboot.
3. Confirm data loss and request the unlock once.
4. Move the thumb drive to the computer; select it to collect and verify the result.
5. Factory-reset the Onn 4K Pro, finish setup, and re-enable USB debugging.
   Return to the guide and confirm ANDROID READY to reconnect, authorize
   debugging, and restore normal startup.
6. Move the thumb drive back to the Onn 4K Pro. Patch Magisk on that box
   and test one boot from the thumb drive.
7. Grant Shell root, back up boot_b, explicitly confirm the internal write.
8. Remove the thumb drive, then verify permanent root after one normal reboot.
9. Choose whether to disable automatic firmware updates to help preserve root.
'''


class Paused(Exception):
    pass


def ask(prompt):
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise Paused() from None
    if answer.lower() == 'q':
        raise Paused()
    return answer


def confirm(message, phrase='CONTINUE'):
    print('\n' + message)
    if ask('Type ' + phrase + ' to continue, or q to leave: ') != phrase:
        raise Paused()


def size_label(size):
    return f'{size / (1024 ** 3):.1f} GiB' if size else 'size unknown'


def choose_drives(loader, title, expected_uuid=None, minimum_free=False):
    while True:
        print('\n' + title)
        drives = loader()
        for index, drive in enumerate(drives, 1):
            if expected_uuid and drive['uuid'] != expected_uuid:
                drive.update(eligible=False, reason='Different volume; the original thumb drive is required.')
            if minimum_free and drive.get('free', 0) < 1024 ** 3:
                drive.update(eligible=False, reason='At least 1 GiB free is required.')
            free = ' / ' + size_label(drive['free']) + ' free' if 'free' in drive else ''
            print(f"  {index}. {discovery.readable(drive['label'] or 'Unlabelled')} | "
                  f"{size_label(drive['size'])}{free} | {discovery.readable(drive['filesystem'])}")
            print('     ' + discovery.readable(drive['path'] or drive.get('device', '')))
            print('     ' + discovery.readable(drive['uuid']) + ' - ' + drive['reason'])
        if not drives:
            print('  No thumb drive volumes found. Insert the drive and wait for it to mount.')
        answer = ask('Select a drive number, r to refresh, or q to leave: ')
        if answer.lower() == 'r':
            continue
        if answer.isdecimal() and 1 <= int(answer) <= len(drives):
            selected = drives[int(answer) - 1]
            if selected['eligible']:
                return selected
            print('That drive cannot be used: ' + selected['reason'])
        else:
            print('Choose one of the listed numbers.')


def select_box(adb, expected_identity=None, require_locked=False):
    boxes = discovery.discover_boxes(adb)
    if not any(box['eligible'] and (not expected_identity or box.get('identity') == expected_identity)
               and (not require_locked or box['properties'].get('ro.boot.flash.locked') == '1')
               for box in boxes):
        boxes = discovery.discover_boxes(adb, scan=True)
    while True:
        print('\nAvailable network ADB devices')
        for index, box in enumerate(boxes, 1):
            print(f"  {index}. {discovery.readable(box['model'])} | {box['target']}")
            print('     ' + box['reason'])
        if not boxes:
            print('  None found. Check power, the shared network, and debugging authorization.')
        answer = ask('Select a device number, r to refresh, s to search LAN, a for an address, or q: ')
        if answer.lower() in ('r', 's'):
            boxes = discovery.discover_boxes(adb, scan=answer.lower() == 's')
            continue
        if answer.lower() == 'a':
            raw = ask('Onn 4K Pro IPv4 address (optional :port; default 5555): ')
            try:
                target = target_value(raw if ':' in raw else raw + ':5555')
                discovery.command([adb, 'connect', target], timeout=8)
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                print(discovery.readable(error))
            boxes = discovery.discover_boxes(adb)
            continue
        if not answer.isdecimal() or not 1 <= int(answer) <= len(boxes):
            print('Choose one of the listed numbers.')
            continue
        box = boxes[int(answer) - 1]
        # Refresh identity and firmware at selection, not only at initial scan.
        box = discovery.inspect_box(adb, box['target'], box['state'])
        if not box['eligible']:
            print('Cannot use this device: ' + box['reason'])
            continue
        if expected_identity and box['identity'] != expected_identity:
            print('That is a different physical device. Select the box that started this run.')
            continue
        if require_locked and box['properties'].get('ro.boot.flash.locked') != '1':
            print('This box is already unlocked. A new first-install run cannot unlock or reflash it.')
            continue
        return box


def kit_result(run, kind):
    session = latest_session(run / kind)
    return read(session / 'roundtrip.json'), read(session / 'capture-validation.json')


def next_after_interruption(run, action):
    """Only receipts, never a timeout or a menu answer, permit moving forward."""
    if action == 'unlock':
        require(len(sessions(run / 'unlock')) == 1,
                'Unlock was started but there is no unique session. Stop; do not retry the writer.')
        return 'collect'
    if action == 'read-state':
        roundtrip, capture = kit_result(run, 'read')
        require(roundtrip.get('original_startup_restored_and_verified')
                and capture.get('secure_state_read_proven') and capture.get('lock_state') == 1
                and (run / 'locked-read-binding.json').exists(),
                'The locked-state read is incomplete. Do not repeat it automatically.')
        return 'unlock'
    if action == 'patch':
        patch = read(run / 'patch.json')
        require(patch.get('patched_on_this_device') and patch.get('tested_payload_match')
                and digest(run / 'patched-boot.img') == PROFILE['expected_patched_sha256'],
                'Patch is incomplete. Preserve the files; do not overwrite them or substitute an image.')
        return 'root-test'
    if action == 'root-test':
        roundtrip, capture = kit_result(run, 'root')
        require(roundtrip.get('original_startup_restored_and_verified')
                and capture.get('android_booted_via_candidate'),
                'The temporary USB boot is not proved. Do not repeat root-test.')
        return 'root-proof'
    if action == 'install-root':
        require(read(run / 'install/receipt.json').get('flash_verified') is True,
                'Internal write is not verified. DO NOT REBOOT, power off, or retry the flash.')
        return 'verify'
    if action == 'verify-root':
        # Even if the previous command was interrupted before recording its
        # reboot request, never issue a second reboot automatically.
        return 'verify-check'
    if action in ('disable-updates', 'updates-status'):
        # Never replay a partially applied update change or replace its backup.
        return 'updates-check' if (run / 'updates/receipt.json').exists() else 'updates'
    require(action in ('prepare-usb', 'collect-unlock', 'restore-startup', 'verify-unlock', 'root-proof'),
            'Unknown interrupted action; inspect the saved run.')
    return None  # These existing guarded commands can be resumed without another boot/write.


def run_command(arguments, log_path, lock_fd=None):
    """Stream instructions while keeping a local log and leaving child cleanup intact."""
    argv = [sys.executable, '-u', str(ROOT / 'onn.py'), *arguments]
    lines = queue.Queue()
    with log_path.open('x') as log:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors='replace', start_new_session=True,
                                   pass_fds=() if lock_fd is None else (lock_fd,))

        def receive():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                process.stdout.close()
                lines.put(None)

        worker = threading.Thread(target=receive, daemon=True)
        worker.start()
        while True:
            try:
                line = lines.get(timeout=15)
                if line is None:
                    break
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            except queue.Empty:
                print('Still waiting for this step. Watch the Onn 4K Pro screen; do not start another command.', flush=True)
            except KeyboardInterrupt:
                print('\nLetting the current device action and its cleanup finish. Do not power off.', flush=True)
        worker.join()
        return process.wait()


class Guide:
    def __init__(self, config, run, state, lock_fd=None):
        self.config, self.run, self.state = config, run, state
        self.adb = run / 'root/tools/adb'
        # The child retains this lock if the terminal/guide exits unexpectedly.
        # A second guide cannot collect USB or resume while that action runs.
        self.lock_fd = lock_fd

    def persist(self):
        save(self.run / 'wizard.json', self.state)

    def connection(self, rediscover=False):
        box = None
        if not rediscover:
            try:
                discovery.command([self.adb, 'connect', self.config['target']], timeout=8)
                box = discovery.inspect_box(self.adb, self.config['target'])
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
        if not box or not box['eligible'] or box.get('identity') != self.state['device_identity']:
            print('Reconnect and authorize the same physical Onn 4K Pro. The IP may have changed after reset.')
            box = select_box(self.adb, expected_identity=self.state['device_identity'])
        if box['target'] != self.config['target']:
            onn.set_target(SimpleNamespace(target=box['target']), self.config, self.run)
        return Device(self.config, self.run)

    def action(self, arguments, next_stage=None, offline=False):
        if not offline:
            self.connection()
        if arguments[0] in ('read-state', 'unlock', 'root-test'):
            self.drive_on_tv()
        # Record the attempt before starting a process. A restart must resolve
        # its receipts, not replay an unlock or a partially completed flash.
        number = len(self.state.setdefault('history', [])) + 1
        log = self.run / f'wizard-{number:03d}-{arguments[0]}.log'
        self.state['pending'] = arguments[0]
        entry = {'command': arguments, 'started_at': now(), 'log': log.name}
        self.state['history'].append(entry)
        self.persist()
        code = run_command(arguments, log, lock_fd=self.lock_fd)
        entry.update(returncode=code, completed_at=now())
        self.persist()
        if code != 0:
            # An interrupted unlock goes to offline result collection, never a
            # retry. A root prompt can be missed after a successful USB boot.
            if arguments[0] in ('unlock', 'root-test'):
                next_stage = next_after_interruption(self.run, arguments[0])
                print('Continuing with result verification; the device action will not be repeated.')
            else:
                raise RuntimeError('Step stopped. Saved output: ' + str(log))
        self.state.pop('pending', None)
        if next_stage:
            self.state['stage'] = next_stage
        self.persist()

    def resume_pending(self):
        if self.state.get('pending'):
            stage = next_after_interruption(self.run, self.state['pending'])
            if stage:
                self.state['stage'] = stage
            self.state.pop('pending')
            self.persist()

    def drive_on_tv(self, minimum_free=False):
        self.connection()
        while True:
            drive = choose_drives(lambda: discovery.discover_tv_drives(self.adb, self.config['target']),
                                  'Thumb drives connected to the Onn 4K Pro (select the original drive)',
                                  self.config['usb_uuid'], minimum_free)
            if drive.get('usb_disk_count') == 1:
                return drive
            print('Leave only the selected thumb drive connected to the Onn 4K Pro, then refresh.\n'
                  'The tested bootloader reads its first USB disk; Android cannot guarantee\n'
                  'which disk is first when several are connected. No device action was started.')

    def execute(self):
        self.resume_pending()
        if self.state['stage'] == 'complete' and 'updates_choice' not in self.state:
            # Offer the new option once when resuming an older completed guide.
            self.state['stage'] = 'updates'
            self.persist()
        while self.state['stage'] != 'complete':
            stage = self.state['stage']
            print('\nCurrent step: ' + stage + '\nReceipts: ' + str(self.run))
            if stage == 'prepare':
                self.drive_on_tv(minimum_free=True)
                confirm('Leave the thumb drive in the Onn 4K Pro. This creates empty ONN23, ONN24, and ONN26 folders.\n'
                        'Existing captures are preserved; a nonempty folder stops the guide.')
                self.action(['prepare-usb'], 'read-state')
            elif stage == 'read-state':
                confirm('The next step temporarily changes startup and reboots once to read the secure\n'
                        'lock state. It does not request an unlock, but experimental boot code can\n'
                        'brick the device. Keep the thumb drive in the Onn 4K Pro and power connected.', 'READ STATE')
                self.action(['read-state', '--accept-risk'], 'unlock')
            elif stage == 'unlock':
                confirm('The next step WRITES the secure AVB lock state and reboots once.\n'
                        'The Onn 4K Pro will enter recovery and require a factory reset. This erases\n'
                        'apps, accounts, and settings. The unlock can also brick the box.\n'
                        'Keep the thumb drive connected until the recovery screen appears.\n'
                        'The guide will pause for the reset and setup. Do not rerun unlock.', 'ERASE AND UNLOCK')
                self.action(['unlock', '--accept-data-loss'], 'collect')
            elif stage == 'collect':
                confirm('Wait for the Onn 4K Pro to show the recovery message:\n'
                        '"Can\'t load Android system. Your data may be corrupt".\n'
                        'Keep the thumb drive connected until that screen appears.\n'
                        'If it does not appear, stop here and preserve the saved result; do not rerun unlock.\n'
                        'Confirm only after the recovery screen has appeared.', 'RECOVERY SHOWN')
                print('Remove the thumb drive from the Onn 4K Pro and insert it into this computer. Open the drive in\n'
                      'your file manager if it is not mounted. Keep the Onn 4K Pro powered on.\n'
                      'Collection checks for the measured secure-state change 1 -> 0 and removes\n'
                      'any unused one-use gate. It does not retry the unlock.')
                drive = choose_drives(lambda: discovery.discover_host_drives(self.config['usb_uuid']),
                                      'Thumb drives connected to this computer', self.config['usb_uuid'])
                # Revalidate the selected mount immediately before collection.
                require(any(d['eligible'] and d['path'] == drive['path'] for d in
                            discovery.discover_host_drives(self.config['usb_uuid'])), 'Thumb drive mount changed; refresh.')
                confirm('Collect the unlock result from ' + discovery.readable(drive['path']) + '?')
                self.action(['collect-unlock', '--usb-path', drive['path']], 'reconnect', offline=True)
            elif stage == 'reconnect':
                confirm('Keep the thumb drive out of the Onn 4K Pro. At the recovery screen,\n'
                        'use the button on the front of the unit:\n'
                        '1. Use quick presses to cycle through the menu to Factory data reset.\n'
                        '2. Press and hold to select the option. The bar will turn green.\n'
                        '3. Press once more to confirm the selection.\n'
                        'THIS ERASES APPS, ACCOUNTS, AND SETTINGS.\n'
                        'If you have already completed the reset, continue with setup.\n'
                        'Finish Android setup and re-enable USB debugging.\n'
                        'If the front button does not operate the recovery menu, stop.\n'
                        'Come back when you have finished resetting and setting up your device.\n'
                        'The guide will not look for the Onn 4K Pro until you confirm ANDROID READY.\n'
                        'Then accept the debugging authorization on the Onn 4K Pro when prompted.', 'ANDROID READY')
                self.connection(rediscover=True)
                self.action(['restore-startup', '--kit', 'unlock'])
                self.action(['verify-unlock'], 'patch')
            elif stage == 'patch':
                print('Safely eject the thumb drive from the computer and put it back in the Onn 4K Pro.\n'
                      'Use the same volume. Do not clear the earlier captures or prepare the thumb drive again.')
                self.drive_on_tv()
                confirm('Patch the stock image on this Onn 4K Pro using the included official Magisk tools.\n'
                        'This installs the Magisk manager but writes no firmware partition.\n'
                        'Do not use Magisk Direct Install; this build requires boot_b, not init_boot.')
                self.action(['patch'], 'root-test')
            elif stage == 'root-test':
                confirm('Reboot once through the one-use USB Magisk image. Experimental boot code\n'
                        'can brick the box. Leave the thumb drive connected and choose Grant for Shell if the\n'
                        'Onn 4K Pro shows a Superuser prompt. Do not reboot again before installation.', 'TEST ROOT')
                self.action(['root-test', '--accept-risk'], 'root-proof')
            elif stage == 'root-proof':
                confirm('Choose Grant for Shell in the Magisk Superuser prompt on the Onn 4K Pro.\n'
                        'This checks root in the same temporary boot without another reboot.')
                self.action(['root-proof'], 'install')
            elif stage == 'install':
                confirm('The installer will back up boot_b, check the images and temporary root,\n'
                        'then WRITE INTERNAL FLASH once and verify its readback. Power loss or a\n'
                        'failed write can brick the box. Removing the thumb drive cannot undo this write.\n'
                        'Keep power connected. This command will not reboot automatically.', 'WRITE BOOT_B')
                self.action(['install-root', '--accept-risk'], 'verify')
            elif stage in ('verify', 'verify-check'):
                confirm('Physically remove the thumb drive from the Onn 4K Pro. Permanent root must work without it.\n'
                        'The next step checks the saved installation and root.', 'THUMB DRIVE REMOVED')
                device = self.connection()
                installed = read(self.run / 'install/receipt.json')
                proof_path = self.run / 'permanent-root-proof.json'
                proof = read(proof_path) if proof_path.exists() else {}
                arguments = ['verify-root']
                if (stage == 'verify' and not proof.get('reboot_requested')
                        and device.boot_id() == installed['boot_id_before']):
                    confirm('Request one normal reboot now, then verify internal root with the thumb drive absent.', 'REBOOT')
                    arguments += ['--reboot', '--usb-removed']
                else:
                    print('Checking the current boot only; no additional reboot will be requested.')
                self.action(arguments, 'updates')
            elif stage == 'updates':
                require(read(self.run / 'permanent-root-proof.json').get('permanent_root_proven') is True,
                        'Verify permanent root before choosing update settings.')
                if (self.run / 'updates/receipt.json').exists():
                    self.state['stage'] = 'updates-check'
                    self.persist()
                    continue
                print('Permanent root is verified. Automatic firmware updates can replace the rooted boot image.\n'
                      'Disabling them also pauses firmware security fixes. Play Store app updates stay enabled.\n'
                      'This helps preserve root; it does not guarantee the bootloader can never relock.\n'
                      'The previous update settings will be saved so you can restore them later.')
                answer = ask('Disable automatic firmware updates? (y/n, or q to leave): ').lower()
                if answer in ('y', 'yes'):
                    self.state['updates_choice'] = 'disable'
                    self.persist()
                    self.action(['disable-updates', '--apply'], 'complete')
                elif answer in ('n', 'no'):
                    self.state.update(updates_choice='unchanged', stage='complete')
                    self.persist()
                    print('Automatic firmware update settings left unchanged.')
                else:
                    print('Enter y or n. No update settings have been changed.')
            elif stage == 'updates-check':
                self.action(['updates-status'], 'complete')
                self.state['updates_choice'] = read(self.run / 'updates/receipt.json')['status']
                self.persist()
            else:
                raise RuntimeError('Unknown saved step; preserve wizard.json and inspect the run.')
        proof = read(self.run / 'permanent-root-proof.json')
        require(proof.get('permanent_root_proven') is True, 'The final root proof is missing.')
        print('\nPermanent root was verified: ' + proof['completed_at'])
        print('Keep this run folder and its boot backup: ' + str(self.run))
        if (self.run / 'updates/receipt.json').exists():
            print('Saved firmware update result: ' + read(self.run / 'updates/receipt.json')['status'])
            print('Restore the previous settings: python3 onn.py restore-updates --apply')
        elif self.state.get('updates_choice') == 'unchanged':
            print('Automatic firmware update settings were left unchanged.')
        print('Keep the bootloader unlocked. Firmware updates and other firmware remain untested.')


def recovery_message(run, state):
    pending = state.get('pending', '')
    print('\nThe guide has stopped. Preserve the run and USB captures: ' + str(run))
    if state['stage'] in ('updates', 'updates-check'):
        print('Root installation is complete, but the firmware update choice has not been verified.\n'
              'Resume the guide to check the saved result. If a settings backup exists, restore it with:\n'
              '  python3 onn.py restore-updates --apply\n'
              'Keep the updates/ folder within the saved run. Do not rerun the unlock or root installer.')
    elif state['stage'] in ('install', 'verify', 'verify-check') or pending == 'install-root':
        print('If the internal write is unverified, DO NOT REBOOT or power off. Do not retry\n'
              'install-root. Inspect install/receipt.json and install/flash.log first. A\n'
              'timeout does not prove failure or success. A factory reset does not repair\n'
              'a damaged boot image. No recovery from a fully bricked box is demonstrated.')
    else:
        print('Do not repeat a read, unlock, or USB root test after an ambiguous result.\n'
              'Before any internal flash, remove the thumb drive and power-cycle once if Android will\n'
              'not start. When Android/debugging return, restore the affected startup with:')
        kind = 'root' if state['stage'] in ('root-test', 'root-proof') else 'read' if state['stage'] == 'read-state' else 'unlock'
        print('  python3 onn.py restore-startup --kit ' + kind)
        print('That command only restores its known startup value. It does not repeat the test.')


def show_status():
    print('Onn 4K Pro guide progress')
    if not (WORK / 'current.json').exists():
        print('No saved run. Run python3 onn.py to begin.')
        return
    config, run = configuration()
    print('Saved files: ' + str(run))
    if not (run / 'wizard.json').exists():
        print('This is a manual run; no guided progress was recorded.')
        return
    state = read(run / 'wizard.json')
    require(state.get('version') == 1 and state.get('run_id') == config['run_id'],
            'Unexpected saved guide state.')
    stages = {
        'prepare': 'Prepare the thumb drive',
        'read-state': 'Read the lock state',
        'unlock': 'Unlock the Onn 4K Pro',
        'collect': 'Collect the unlock result',
        'reconnect': 'Finish Android setup and reconnect',
        'patch': 'Create the Magisk image',
        'root-test': 'Test temporary root',
        'root-proof': 'Verify temporary root',
        'install': 'Install permanent root',
        'verify': 'Verify permanent root without the thumb drive',
        'verify-check': 'Check root after the saved reboot attempt',
        'updates': 'Choose whether to disable automatic firmware updates',
        'updates-check': 'Verify the saved firmware update choice',
        'complete': 'Complete',
    }
    require(state.get('stage') in stages, 'Unknown saved step; preserve wizard.json and inspect the run.')
    print('Current step: ' + stages[state['stage']])
    if state.get('pending'):
        print('Saved action awaiting verification: ' + discovery.readable(state['pending']))
        print('Its result has not been resolved by the guide. Do not repeat the action.')
    elif state['stage'] == 'complete':
        proof_path = run / 'permanent-root-proof.json'
        proof = read(proof_path) if proof_path.exists() else {}
        require(proof.get('permanent_root_proven') is True, 'The final root proof is missing.')
        print('Permanent root verified: ' + discovery.readable(proof.get('completed_at', '')))
    if state.get('updates_choice'):
        print('Firmware update choice: ' + discovery.readable(state['updates_choice']))
    if (run / 'updates/receipt.json').exists():
        print('Saved firmware update result: ' + discovery.readable(read(run / 'updates/receipt.json')['status']))
    print('Recorded commands:')
    history = state.get('history', [])
    if not history:
        print('  None yet.')
    for index, entry in enumerate(history, 1):
        command = discovery.readable(' '.join(entry['command']))
        result = ('result pending' if entry.get('returncode') is None
                  else 'exit ' + str(entry['returncode']))
        print(f'  {index}. {command} ({result})')
    if history and history[-1].get('log'):
        print('Latest log: ' + discovery.readable(run / history[-1]['log']))


def start(args):
    if getattr(args, 'status', False):
        show_status()
        return
    print(INTRO)
    if getattr(args, 'preview', False):
        print(STEPS)
        print('Preview only. No ADB, network scan, or device commands were run.')
        return
    require(sys.version_info >= (3, 10), 'Python 3.10 or later is required.')
    require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'AMD64'),
            'The guided workflow supports Linux x86_64 only.')
    import fcntl
    adb = ROOT / 'tools/linux/adb'
    if getattr(args, 'discover_only', False):
        for box in discovery.discover_boxes(adb, scan=True):
            print(box['target'], discovery.readable(box['model']), box['reason'])
            if box['eligible']:
                for drive in discovery.discover_tv_drives(adb, box['target']):
                    print('  Thumb drive:', discovery.readable(drive['label']), drive['uuid'],
                          size_label(drive['size']), drive['reason'])
        print('Discovery only. No device setup, reboot, unlock, or flash was requested.')
        return
    require(sys.stdin.isatty(), 'The guide needs an interactive terminal. Use wizard --preview for an offline overview.')
    WORK.mkdir(exist_ok=True)
    with (WORK / 'wizard.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another guide is already running. Do not start a second device action.') from None
        guide = None
        try:
            if (WORK / 'current.json').exists():
                config, run = configuration()
                require((run / 'wizard.json').exists(),
                        'An existing manual run was found. Preserve it and its receipts; the guide will not replace or restart it.')
                state = read(run / 'wizard.json')
                require(state.get('version') == 1 and state.get('run_id') == config['run_id'], 'Unexpected saved guide state.')
                guide = Guide(config, run, state, lock.fileno())
                print('Resuming the saved run: ' + str(run))
            else:
                require(shutil.disk_usage(ROOT).free >= 1024 ** 3, 'Free at least 1 GiB on this computer.')
                confirm('Connect only your own Onn 4K Pro on your trusted network. Continue to discovery.')
                box = select_box(adb, require_locked=True)
                usage = discovery.parse_df(discovery.command([adb, '-s', box['target'], 'shell', 'df -k /data']))
                require(usage['free'] >= 1024 ** 3, 'Free at least 1 GiB on the Onn 4K Pro.')
                drive = choose_drives(lambda: discovery.discover_tv_drives(adb, box['target']),
                                      'Insert the thumb drive into the Onn 4K Pro; select its mounted drive', minimum_free=True)
                confirm('Android identifies a FAT volume but cannot prove FAT32 before root.\n'
                        'Confirm that you prepared this drive as FAT32 and backed it up.\n'
                        'The guide will not format it.', 'FAT32')
                onn.setup(SimpleNamespace(target=box['target'], usb_uuid=drive['uuid'], adb=None, new_run=False))
                config, run = configuration()
                state = {'version': 1, 'run_id': config['run_id'], 'device_identity': box['identity'],
                         'stage': 'prepare', 'created_at': now(), 'history': []}
                guide = Guide(config, run, state, lock.fileno())
                guide.persist()
            guide.execute()
        except Paused:
            print('\nGuide exited. To resume, run python3 onn.py from the repository folder in your terminal.')
            if guide:
                print('Progress and receipts saved in: ' + str(guide.run))
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            if guide:
                recovery_message(guide.run, guide.state)
            raise
