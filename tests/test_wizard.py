from contextlib import redirect_stdout
import io
import ipaddress
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import discovery
import onnlib as lib
import wizard
from test_guards import properties


MOUNT_DUMP = '''Disks:
  DiskInfo{disk:8,0}:
    flags=USB size=16000000000 label=USB Drive
    sysPath=/devices/platform/usb1/1-1

Volumes:
  VolumeInfo{emulated;0}:
    type=EMULATED diskId=null partGuid= mountFlags=PRIMARY|VISIBLE_FOR_WRITE mountUserId=0 state=MOUNTED
    fsType=null fsUuid=null fsLabel=null
    path=/storage/emulated internalPath=/data/media
  VolumeInfo{public:8,1}:
    type=PUBLIC diskId=disk:8,0 partGuid= mountFlags=VISIBLE_FOR_WRITE mountUserId=0 state=MOUNTED
    fsType=vfat fsUuid=ABCD-1234 fsLabel=MY DRIVE
    path=/storage/ABCD-1234 internalPath=/mnt/media_rw/ABCD-1234

Records:
  VolumeRecord:
    type=PUBLIC fsUuid=DEAD-BEEF partGuid=
    nickname=Old drive
'''


def disk_data():
    return {'blockdevices': [
        {'type': 'disk', 'tran': 'nvme', 'children': [
            {'type': 'part', 'fstype': 'vfat', 'fsver': 'FAT32', 'uuid': 'ABCD-1234',
             'size': 100000000, 'mountpoints': ['/boot/efi']}]},
        {'type': 'disk', 'tran': 'usb', 'children': [
            {'type': 'part', 'path': '/dev/sdb1', 'fstype': 'vfat', 'fsver': 'FAT32',
             'uuid': 'abcd-1234', 'size': 16000000000, 'label': 'MY DRIVE',
             'mountpoints': ['/media/test/MY DRIVE']}]}]}


def box(target='192.0.2.10:5555', identity='original', state='locked'):
    return {'target': target, 'eligible': True, 'identity': identity, 'model': 'onn. 4K Pro',
            'state': 'device', 'properties': properties(state), 'reason': 'Tested firmware'}


def tv_drive():
    return {**discovery.tv_volumes(MOUNT_DUMP)[0], 'free': 8 * 1024 ** 3}


class DiscoveryTests(unittest.TestCase):
    def test_only_network_adb_targets_and_authorization_status_are_parsed(self):
        result = discovery.adb_devices('''List of devices attached
192.0.2.10:5555 device product:jarvis model:onn
192.0.2.11:5555 unauthorized
192.0.2.12:5555 offline
emulator-5554 device
USB-SERIAL device
192.0.2.13;id:5555 device
''')
        self.assertEqual(result, {'192.0.2.10:5555': 'device',
                                  '192.0.2.11:5555': 'unauthorized', '192.0.2.12:5555': 'offline'})

    def test_unauthorized_device_is_not_queried_or_selected(self):
        with patch.object(discovery, 'command', side_effect=AssertionError('No shell on unauthorized device')):
            result = discovery.inspect_box('adb', '192.0.2.10:5555', 'unauthorized')
        self.assertFalse(result['eligible'])
        self.assertIn('authorization', result['reason'])

    def test_exact_identity_and_hardware_binding(self):
        props = {**properties('locked'), 'ro.product.model': 'onn. 4K Pro', 'ro.serialno': 'fixture-device'}
        text = '\n'.join(f'[{k}]: [{v}]' for k, v in props.items())
        with patch.object(discovery, 'command', return_value=text):
            result = discovery.inspect_box('adb', '192.0.2.10:5555')
        self.assertTrue(result['eligible'])
        self.assertEqual(len(result['identity']), 64)
        self.assertNotEqual(discovery.device_identity({**props, 'ro.serialno': 'other-device'}), result['identity'])
        self.assertEqual(discovery.device_identity({**props, 'android_id': 'reset'}), result['identity'])
        with patch.object(discovery, 'command', return_value=text.replace(lib.PROFILE['bootloader'], 'other')):
            self.assertFalse(discovery.inspect_box('adb', '192.0.2.10:5555')['eligible'])
        with self.assertRaises(RuntimeError):
            discovery.device_identity({})

    def test_scan_excludes_vpn_docker_down_interfaces_and_bounds_large_networks(self):
        def interface(name, ip, prefix=24, flags=None):
            return {'ifname': name, 'flags': flags or ['UP', 'LOWER_UP'],
                    'addr_info': [{'family': 'inet', 'local': ip, 'prefixlen': prefix, 'scope': 'global'}]}
        interfaces = [interface('eth0', '198.51.100.25', 8), interface('wlan0', '203.0.113.8'),
                      interface('docker0', '192.0.2.1'), interface('br-container', '192.0.2.1'),
                      interface('tun0', '192.0.2.2'), interface('wg0', '192.0.2.3'),
                      interface('eth1', '192.0.2.4', flags=['UP'])]
        networks, own = discovery.networks_from_addresses(interfaces)
        self.assertEqual(set(map(str, networks)), {'198.51.100.0/24', '203.0.113.0/24'})
        self.assertEqual(own, {'198.51.100.25', '203.0.113.8'})
        self.assertTrue(all(n.num_addresses <= 256 for n in networks))

    def test_discovery_only_connects_open_ports_and_never_runs_a_writer(self):
        calls = []
        def command(argv, **kwargs):
            calls.append(argv)
            if argv[-2:] == ['devices', '-l']:
                return '192.0.2.1:5555 unauthorized\n'
            if argv[0] == 'ip':
                return '[]'
            if argv[1] == 'connect':
                return 'connected'
            raise AssertionError(argv)
        with patch.object(discovery, 'command', side_effect=command), \
                patch.object(discovery, 'networks_from_addresses', return_value=([ipaddress.IPv4Network('192.0.2.0/29')], {'192.0.2.6'})), \
                patch.object(discovery, 'open_adb_port', side_effect=lambda ip: ip + ':5555' if ip == '192.0.2.2' else None), \
                redirect_stdout(io.StringIO()):
            found = discovery.discover_boxes('adb', scan=True)
        self.assertFalse(found[0]['eligible'])
        self.assertEqual([c for c in calls if 'connect' in c], [['adb', 'connect', '192.0.2.2:5555']])

    def test_tv_usb_parser_ignores_internal_storage_and_old_records(self):
        drives = discovery.tv_volumes(MOUNT_DUMP)
        self.assertEqual(len(drives), 1)
        self.assertTrue(drives[0]['eligible'])
        self.assertEqual(drives[0]['label'], 'MY DRIVE')
        self.assertEqual(drives[0]['path'], '/storage/ABCD-1234')
        self.assertEqual(drives[0]['usb_disk_count'], 1)

    def test_multiple_usb_disks_are_counted_even_if_one_has_no_mounted_volume(self):
        text = MOUNT_DUMP.replace('Volumes:', '  DiskInfo{disk:8,16}:\n'
                                 '    flags=USB size=32000000000 label=Other drive\n\nVolumes:')
        self.assertEqual(discovery.tv_volumes(text)[0]['usb_disk_count'], 2)

    def test_tv_rejects_wrong_filesystem_partition_transport_path_and_state(self):
        changes = [('fsType=vfat', 'fsType=exfat'), ('public:8,1', 'public:8,2'),
                   ('flags=USB', 'flags=SD'), ('state=MOUNTED', 'state=UNMOUNTED'),
                   ('path=/storage/ABCD-1234', 'path=/storage/ABCD-1234;id'),
                   ('fsUuid=ABCD-1234', 'fsUuid=ABCD-1234;id')]
        for before, after in changes:
            with self.subTest(after=after):
                self.assertFalse(discovery.tv_volumes(MOUNT_DUMP.replace(before, after))[0]['eligible'])

    def test_host_only_lists_usb_and_accepts_same_mounted_fat32_volume(self):
        drives = discovery.host_volumes(disk_data(), 'ABCD-1234')
        self.assertEqual(len(drives), 1)
        self.assertTrue(drives[0]['eligible'])
        self.assertEqual(drives[0]['path'], '/media/test/MY DRIVE')
        for key, value in [('uuid', 'DEAD-BEEF'), ('fsver', 'FAT16'), ('fstype', 'exfat'), ('mountpoints', [None])]:
            data = disk_data()
            data['blockdevices'][1]['children'][0][key] = value
            with self.subTest(key=key):
                result = discovery.host_volumes(data, 'ABCD-1234')
                self.assertEqual(len(result), 1)
                self.assertFalse(result[0]['eligible'])

    def test_df_and_terminal_text_handling(self):
        self.assertEqual(discovery.parse_df('Filesystem 1K-blocks Used Available Use% Mounted\n'
                                           '/dev/block/test 10000 3000 7000 30% /storage/ABCD-1234'),
                         {'size': 10240000, 'free': 7168000})
        with self.assertRaises(RuntimeError):
            discovery.parse_df('Permission denied')
        self.assertNotIn('\x1b', discovery.readable('USB\x1b[2J'))
        self.assertNotIn('\n', discovery.readable('USB\nAnother prompt'))


class SelectionTests(unittest.TestCase):
    def test_drive_selection_rejects_ineligible_drive_and_accepts_number_not_path(self):
        bad = {**tv_drive(), 'eligible': False, 'reason': 'Wrong filesystem'}
        with patch.object(wizard, 'ask', side_effect=['1', '2']), redirect_stdout(io.StringIO()):
            drive = wizard.choose_drives(lambda: [bad, tv_drive()], 'USB')
        self.assertTrue(drive['eligible'])

    def test_wrong_usb_and_insufficient_free_space_are_not_selectable(self):
        for change in [{'uuid': 'DEAD-BEEF'}, {'free': 1}]:
            with patch.object(wizard, 'ask', side_effect=['1', wizard.Paused()]), redirect_stdout(io.StringIO()):
                with self.assertRaises(wizard.Paused):
                    wizard.choose_drives(lambda: [{**tv_drive(), **change}], 'USB', 'ABCD-1234', True)

    def test_reconnect_requires_same_physical_box_even_if_both_firmware_match(self):
        boxes = [box(identity='different'), box(target='192.0.2.11:5555')]
        with patch.object(discovery, 'discover_boxes', return_value=boxes), \
                patch.object(discovery, 'inspect_box', side_effect=lambda adb, target, state: next(b for b in boxes if b['target'] == target)), \
                patch.object(wizard, 'ask', side_effect=['1', '2']), redirect_stdout(io.StringIO()):
            selected = wizard.select_box('adb', expected_identity='original')
        self.assertEqual(selected['target'], '192.0.2.11:5555')

    def test_unlocked_box_cannot_start_first_install(self):
        unlocked = box(state='unlocked')
        with patch.object(discovery, 'discover_boxes', return_value=[unlocked]), \
                patch.object(discovery, 'inspect_box', return_value=unlocked), \
                patch.object(wizard, 'ask', side_effect=['1', wizard.Paused()]), redirect_stdout(io.StringIO()):
            with self.assertRaises(wizard.Paused):
                wizard.select_box('adb', require_locked=True)

    def test_confirm_does_not_accept_empty_or_generic_yes(self):
        for value in ['', 'yes', 'WRITE BOOT_A']:
            with patch.object(wizard, 'ask', return_value=value), redirect_stdout(io.StringIO()):
                with self.assertRaises(wizard.Paused):
                    wizard.confirm('Write internal flash', 'WRITE BOOT_B')

    def test_preview_never_starts_a_process_or_scan(self):
        with patch.object(subprocess, 'run', side_effect=AssertionError('No process permitted')), \
                patch.object(discovery, 'discover_boxes', side_effect=AssertionError('No scan permitted')), \
                redirect_stdout(io.StringIO()) as output:
            wizard.start(SimpleNamespace(preview=True))
        self.assertIn('Preview only', output.getvalue())


class StatusTests(unittest.TestCase):
    def make_run(self, work):
        config = {'run_id': '20261021T000000Z-1234abcd', 'target': '192.0.2.10:5555', 'usb_uuid': 'ABCD-1234'}
        lib.save(work / 'current.json', config)
        run = work / 'runs' / config['run_id']
        run.mkdir(parents=True)
        return config, run

    def status(self, work):
        before = {str(p): p.read_bytes() for p in work.rglob('*') if p.is_file()}
        with patch.object(wizard, 'WORK', work), patch.object(lib, 'WORK', work), \
                patch.object(wizard.onn, 'verify_files', return_value=63), \
                patch.object(wizard.sys, 'argv', ['onn.py', 'wizard', '--status']), \
                patch.object(subprocess, 'run', side_effect=AssertionError('No process permitted')), \
                patch.object(discovery, 'discover_boxes', side_effect=AssertionError('No scan permitted')), \
                patch.object(wizard, 'run_command', side_effect=AssertionError('No device action permitted')), \
                patch.object(wizard, 'next_after_interruption', side_effect=AssertionError('Do not resolve pending actions')), \
                patch.object(wizard, 'save', side_effect=AssertionError('Status must not save changes')), \
                patch('builtins.input', side_effect=AssertionError('No prompt permitted')), \
                redirect_stdout(io.StringIO()) as output:
            wizard.onn.main()
        self.assertEqual(before, {str(p): p.read_bytes() for p in work.rglob('*') if p.is_file()})
        return output.getvalue()

    def test_status_without_run_does_not_create_one(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'work'
            self.assertIn('No saved run', self.status(work))
            self.assertFalse(work.exists())

    def test_status_does_not_adopt_manual_run(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            _, run = self.make_run(work)
            self.assertIn('manual run', self.status(work))
            self.assertFalse((run / 'wizard.json').exists())

    def test_status_displays_pending_flash_without_resuming_it(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            config, run = self.make_run(work)
            for code in (None, 0, 1):
                with self.subTest(returncode=code):
                    entry = {'command': ['install-root', '--accept-risk'], 'log': 'wizard-009-install-root.log'}
                    if code is not None:
                        entry['returncode'] = code
                    lib.save(run / 'wizard.json', {'version': 1, 'run_id': config['run_id'],
                             'stage': 'install', 'pending': 'install-root', 'history': [entry]})
                    result = self.status(work)
                    self.assertIn('Current step: Install permanent root', result)
                    self.assertIn('Saved action awaiting verification: install-root', result)
                    self.assertIn('result pending' if code is None else 'exit ' + str(code), result)
                    self.assertIn('wizard-009-install-root.log', result)
                    self.assertNotIn('Permanent root verified', result)

    def test_status_requires_saved_proof_before_reporting_verified_root(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            config, run = self.make_run(work)
            lib.save(run / 'wizard.json', {'version': 1, 'run_id': config['run_id'],
                     'stage': 'complete', 'history': []})
            with self.assertRaisesRegex(RuntimeError, 'final root proof is missing'):
                self.status(work)
            lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
            self.assertIn('Permanent root verified: fixture', self.status(work))


class ResumeTests(unittest.TestCase):
    def test_unlock_timeout_advances_only_to_collection_never_to_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            lib.save(run / 'unlock/sessions/one/roundtrip.json', {'action': 'test', 'reboot_requested': True})
            self.assertEqual(wizard.next_after_interruption(run, 'unlock'), 'collect')
            lib.save(run / 'unlock/sessions/two/roundtrip.json', {'action': 'test'})
            with self.assertRaises(RuntimeError):
                wizard.next_after_interruption(run, 'unlock')

    def test_ambiguous_flash_never_advances_to_reboot_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            lib.save(run / 'install/receipt.json', {'flash_attempted': True, 'flash_verified': False})
            with self.assertRaisesRegex(RuntimeError, 'DO NOT REBOOT'):
                wizard.next_after_interruption(run, 'install-root')
            lib.save(run / 'install/receipt.json', {'flash_verified': True})
            self.assertEqual(wizard.next_after_interruption(run, 'install-root'), 'verify')

    def test_reboot_interruption_can_only_resume_without_another_reboot(self):
        self.assertEqual(wizard.next_after_interruption(Path('/unused'), 'verify-root'), 'verify-check')

    def test_missed_root_prompt_does_not_repeat_usb_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            session = run / 'root/sessions/one'
            lib.save(session / 'roundtrip.json', {'action': 'test', 'original_startup_restored_and_verified': True})
            lib.save(session / 'capture-validation.json', {'android_booted_via_candidate': True})
            self.assertEqual(wizard.next_after_interruption(run, 'root-test'), 'root-proof')
            lib.save(session / 'capture-validation.json', {'android_booted_via_candidate': False})
            with self.assertRaises(RuntimeError):
                wizard.next_after_interruption(run, 'root-test')

    def test_read_cannot_advance_without_startup_and_binding_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            session = run / 'read/sessions/one'
            lib.save(session / 'roundtrip.json', {'action': 'test', 'original_startup_restored_and_verified': True})
            lib.save(session / 'capture-validation.json', {'secure_state_read_proven': True, 'lock_state': 1})
            with self.assertRaises(RuntimeError):
                wizard.next_after_interruption(run, 'read-state')
            lib.save(run / 'locked-read-binding.json', {'device_binding': 'fixture'})
            self.assertEqual(wizard.next_after_interruption(run, 'read-state'), 'unlock')


class WorkflowTests(unittest.TestCase):
    def make_guide(self, run, stage='prepare'):
        config = {'run_id': '20261021T000000Z-1234abcd', 'target': '192.0.2.10:5555', 'usb_uuid': 'ABCD-1234'}
        state = {'version': 1, 'run_id': config['run_id'], 'device_identity': 'original',
                 'stage': stage, 'history': []}
        return wizard.Guide(config, run, state)

    def test_complete_guided_flow_with_unlock_recovery_handoff_and_saved_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run)
            commands, phrases = [], []
            def execute(arguments, log, **kwargs):
                self.assertEqual(lib.read(run / 'wizard.json')['pending'], arguments[0])
                commands.append(arguments)
                log.write_text('Simulated response; no device contacted.\n')
                if arguments[0] == 'unlock':
                    lib.save(run / 'unlock/sessions/one/roundtrip.json',
                             {'action': 'test', 'reboot_requested': True, 'awaiting_factory_reset': True})
                if arguments[0] == 'install-root':
                    lib.save(run / 'install/receipt.json', {'flash_verified': True, 'boot_id_before': 'old'})
                if arguments[0] == 'verify-root':
                    lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
                return 0
            host = discovery.host_volumes(disk_data(), 'ABCD-1234')
            with patch.object(guide, 'connection', return_value=SimpleNamespace(boot_id=lambda: 'old')), \
                    patch.object(wizard, 'run_command', side_effect=execute), \
                    patch.object(wizard, 'confirm', side_effect=lambda message, phrase='CONTINUE': phrases.append(phrase)), \
                    patch.object(wizard, 'ask', side_effect=lambda prompt: 'n' if 'Disable automatic' in prompt else '1'), \
                    patch.object(discovery, 'discover_tv_drives', side_effect=lambda *args: [tv_drive()]), \
                    patch.object(discovery, 'discover_host_drives', return_value=host), \
                    patch.object(subprocess, 'run', side_effect=AssertionError('No real process permitted')), \
                    redirect_stdout(io.StringIO()):
                guide.execute()
            actions = [c[0] for c in commands]
            self.assertEqual(actions, ['prepare-usb', 'read-state', 'unlock', 'collect-unlock',
                                      'restore-startup', 'verify-unlock', 'patch', 'root-test',
                                      'root-proof', 'install-root', 'verify-root'])
            self.assertEqual(actions.count('unlock'), 1)
            self.assertEqual(actions.count('install-root'), 1)
            self.assertIn('ERASE AND UNLOCK', phrases)
            self.assertIn('RECOVERY SHOWN', phrases)
            self.assertIn('ANDROID READY', phrases)
            self.assertIn('WRITE BOOT_B', phrases)
            self.assertEqual(commands[-1], ['verify-root', '--reboot', '--usb-removed'])
            state = lib.read(run / 'wizard.json')
            self.assertEqual(state['stage'], 'complete')
            self.assertNotIn('pending', state)
            self.assertEqual(len(state['history']), 11)
            self.assertTrue(all((run / item['log']).exists() for item in state['history']))

    def test_collection_and_resumed_setup_prompt_never_contact_the_box(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run, 'unlock')
            guide.state['pending'] = 'unlock'
            lib.save(run / 'unlock/sessions/one/roundtrip.json',
                     {'action': 'test', 'reboot_requested': True, 'awaiting_factory_reset': True})
            host = discovery.host_volumes(disk_data(), 'ABCD-1234')
            commands = []
            def collect(arguments, log, **kwargs):
                self.assertEqual(arguments[0], 'collect-unlock')
                commands.append(arguments)
                return 0
            with patch.object(wizard.Guide, 'connection', side_effect=AssertionError('No connection before setup confirmation')), \
                    patch.object(discovery, 'command', side_effect=AssertionError('No device calls')), \
                    patch.object(discovery, 'discover_boxes', side_effect=AssertionError('No scan')), \
                    patch.object(discovery, 'discover_host_drives', return_value=host), \
                    patch.object(wizard, 'run_command', side_effect=collect), \
                    patch.object(wizard, 'input', side_effect=['RECOVERY SHOWN', '1', 'CONTINUE', 'q'], create=True), \
                    redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(wizard.Paused):
                    guide.execute()
                state = lib.read(run / 'wizard.json')
                self.assertEqual(state['stage'], 'reconnect')
                self.assertNotIn('pending', state)
                self.assertIn('Come back when you have finished resetting and setting up your device.', output.getvalue())
                resumed = wizard.Guide(guide.config, run, state)
                with patch.object(wizard, 'input', return_value='q', create=True):
                    with self.assertRaises(wizard.Paused):
                        resumed.execute()
            self.assertEqual(len(commands), 1)

    def test_collection_waits_for_recovery_screen_before_listing_drives(self):
        with tempfile.TemporaryDirectory() as directory:
            guide = self.make_guide(Path(directory), 'collect')
            with patch.object(wizard, 'input', return_value='q', create=True), \
                    patch.object(discovery, 'discover_host_drives', side_effect=AssertionError('Wait for the recovery screen')), \
                    patch.object(guide, 'connection', side_effect=AssertionError('No device calls')), \
                    redirect_stdout(io.StringIO()):
                with self.assertRaises(wizard.Paused):
                    guide.execute()
            self.assertEqual(guide.state['stage'], 'collect')

    def test_reconnect_only_starts_after_setup_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            guide = self.make_guide(Path(directory), 'reconnect')
            confirmed = False
            class ReconnectReached(Exception):
                pass
            def answer(prompt):
                nonlocal confirmed
                self.assertIn('ANDROID READY', prompt)
                confirmed = True
                return 'ANDROID READY'
            def connect(**kwargs):
                self.assertTrue(confirmed)
                self.assertTrue(kwargs['rediscover'])
                raise ReconnectReached()
            with patch.object(wizard, 'input', side_effect=answer, create=True), \
                    patch.object(guide, 'connection', side_effect=connect), redirect_stdout(io.StringIO()):
                with self.assertRaises(ReconnectReached):
                    guide.execute()

    def test_failed_flash_and_restart_never_issue_a_second_command(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run, 'install')
            def fail(arguments, log, **kwargs):
                lib.save(run / 'install/receipt.json', {'flash_attempted': True, 'flash_verified': False})
                return 1
            with patch.object(guide, 'connection'), patch.object(wizard, 'confirm'), \
                    patch.object(wizard, 'run_command', side_effect=fail) as child, redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    guide.execute()
                with self.assertRaisesRegex(RuntimeError, 'DO NOT REBOOT'):
                    wizard.Guide(guide.config, run, lib.read(run / 'wizard.json')).execute()
            self.assertEqual(child.call_count, 1)

    def test_saved_reboot_attempt_verifies_without_second_reboot(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run, 'verify')
            guide.state['pending'] = 'verify-root'
            lib.save(run / 'install/receipt.json', {'flash_verified': True, 'boot_id_before': 'old'})
            def complete(arguments, log, **kwargs):
                self.assertEqual(arguments, ['verify-root'])
                lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
                return 0
            with patch.object(guide, 'connection', return_value=SimpleNamespace(boot_id=lambda: 'new')), \
                    patch.object(wizard, 'confirm'), patch.object(wizard, 'run_command', side_effect=complete), \
                    patch.object(wizard, 'ask', return_value='n'), \
                    redirect_stdout(io.StringIO()):
                guide.execute()
            self.assertEqual(guide.state['stage'], 'complete')

    def test_update_option_decline_and_quit_never_contact_device(self):
        for answer in ('n', 'q'):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                guide = self.make_guide(run, 'updates')
                lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
                with patch.object(wizard, 'input', side_effect=['', answer], create=True), \
                        patch.object(guide, 'connection', side_effect=AssertionError('No device contact')), \
                        patch.object(wizard, 'run_command', side_effect=AssertionError('No device action')), \
                        redirect_stdout(io.StringIO()):
                    if answer == 'q':
                        with self.assertRaises(wizard.Paused):
                            guide.execute()
                        self.assertEqual(guide.state['stage'], 'updates')
                    else:
                        guide.execute()
                        self.assertEqual(guide.state['stage'], 'complete')
                        self.assertEqual(guide.state['updates_choice'], 'unchanged')

    def test_update_option_applies_only_after_yes_and_verified_root(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run, 'updates')
            lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': False})
            with patch.object(wizard, 'ask', side_effect=AssertionError('Verify root first')), \
                    redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'Verify permanent root'):
                    guide.execute()
            lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
            def disable(arguments, log, **kwargs):
                self.assertEqual(arguments, ['disable-updates', '--apply'])
                lib.save(run / 'updates/receipt.json', {'status': 'disabled'})
                return 0
            with patch.object(wizard, 'input', return_value='yes', create=True), \
                    patch.object(guide, 'connection'), patch.object(wizard, 'run_command', side_effect=disable) as child, \
                    redirect_stdout(io.StringIO()):
                guide.execute()
            child.assert_called_once()
            self.assertEqual(guide.state['stage'], 'complete')

    def test_interrupted_update_change_checks_status_without_reapplying(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run, 'updates')
            guide.state['pending'] = 'disable-updates'
            lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
            lib.save(run / 'updates/receipt.json', {'status': 'applying'})
            def check(arguments, log, **kwargs):
                self.assertEqual(arguments, ['updates-status'])
                lib.save(run / 'updates/receipt.json', {'status': 'disabled'})
                return 0
            with patch.object(guide, 'connection'), patch.object(wizard, 'run_command', side_effect=check) as child, \
                    patch.object(wizard, 'ask', side_effect=AssertionError('Do not offer another attempt')), \
                    redirect_stdout(io.StringIO()):
                guide.execute()
            child.assert_called_once()
            self.assertEqual(guide.state['updates_choice'], 'disabled')
            self.assertEqual(guide.state['stage'], 'complete')

    def test_older_completed_run_offers_updates_once_without_repeating_root_work(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            guide = self.make_guide(run, 'complete')
            lib.save(run / 'permanent-root-proof.json', {'permanent_root_proven': True, 'completed_at': 'fixture'})
            with patch.object(guide, 'connection', side_effect=AssertionError('No device contact')), \
                    patch.object(wizard, 'input', return_value='n', create=True) as answer, \
                    redirect_stdout(io.StringIO()):
                guide.execute()
                guide.execute()
            answer.assert_called_once()

    def test_canceled_flash_confirmation_never_starts_child(self):
        with tempfile.TemporaryDirectory() as directory:
            guide = self.make_guide(Path(directory), 'install')
            with patch.object(wizard, 'ask', return_value='yes'), \
                    patch.object(wizard, 'run_command', side_effect=AssertionError('No flash authorized')), \
                    redirect_stdout(io.StringIO()):
                with self.assertRaises(wizard.Paused):
                    guide.execute()
            self.assertNotIn('pending', guide.state)

    def test_extra_usb_disk_must_be_removed_before_boot_action(self):
        with tempfile.TemporaryDirectory() as directory:
            guide = self.make_guide(Path(directory), 'read-state')
            with patch.object(guide, 'connection'), patch.object(wizard, 'ask', return_value='1'), \
                    patch.object(discovery, 'discover_tv_drives', side_effect=[
                        [{**tv_drive(), 'usb_disk_count': 2}], [tv_drive()]]), \
                    redirect_stdout(io.StringIO()) as output:
                result = guide.drive_on_tv()
            self.assertEqual(result['usb_disk_count'], 1)
            self.assertIn('Leave only the selected thumb drive', output.getvalue())

    def test_command_child_inherits_run_lock_and_output_is_saved(self):
        # Execute a harmless fixture, never onn.py or ADB. The inherited lock
        # keeps a new guide from starting if the controlling terminal closes.
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = '''import os, sys
from pathlib import Path
fd = int(sys.argv[1])
assert os.path.samefile('/proc/self/fd/' + str(fd), Path(__file__).with_name('lock'))
print('inherited run lock')
'''
            (root / 'onn.py').write_text(script)
            with (root / 'lock').open('a') as lock, patch.object(wizard, 'ROOT', root), \
                    redirect_stdout(io.StringIO()):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                code = wizard.run_command([str(lock.fileno())], root / 'command.log', lock_fd=lock.fileno())
            self.assertEqual(code, 0)
            self.assertIn('inherited run lock', (root / 'command.log').read_text())


if __name__ == '__main__':
    unittest.main()
