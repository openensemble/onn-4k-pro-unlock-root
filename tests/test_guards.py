import copy
import gzip
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import onn
import onnlib as lib
import root_install as install


def properties(state='unlocked'):
    return {
        'ro.build.fingerprint': lib.PROFILE['fingerprint'],
        'ro.bootloader': lib.PROFILE['bootloader'],
        'ro.build.version.security_patch': lib.PROFILE['security_patch'],
        'ro.boot.slot_suffix': '_b', 'ro.product.first_api_level': '31',
        'ro.product.cpu.abi': 'armeabi-v7a', 'sys.boot_completed': '1',
        'ro.boot.flash.locked': '0' if state == 'unlocked' else '1',
        'ro.boot.vbmeta.device_state': state,
        'ro.boot.verifiedbootstate': 'orange' if state == 'unlocked' else 'green',
    }


def partitions():
    return {lib.PROFILE['boot_target']: lib.PROFILE['stock_boot_sha256'],
            '/dev/block/by-name/boot_a': 'a' * 64,
            '/dev/block/by-name/vbmeta_b': 'b' * 64,
            '/dev/block/by-name/vendor_boot_b': 'c' * 64}


class GuardTests(unittest.TestCase):
    def test_exact_firmware_and_every_mismatch(self):
        for state in ['locked', 'unlocked']:
            lib.check_properties(properties(state), state)
            for name in properties(state):
                with self.subTest(state=state, property=name):
                    changed = properties(state)
                    changed[name] = 'wrong'
                    with self.assertRaises(RuntimeError):
                        lib.check_properties(changed, state)

    def test_target_injection_and_bad_ports(self):
        self.assertEqual(lib.target_value('192.0.2.10:5555'), '192.0.2.10:5555')
        for value in ['192.0.2.10;id:5555', 'host:5555', '192.0.2.10:0', '192.0.2.10:65536',
                      '192.0.2.10:5555$(id)', '../target', '256.0.0.1:5555']:
            with self.subTest(value=value), self.assertRaises((RuntimeError, ValueError)):
                lib.target_value(value)

    def test_usb_id_is_not_a_shell_path(self):
        self.assertEqual(lib.usb_value('abcd-1234'), 'ABCD-1234')
        for value in ['/storage/ABCD-1234', 'ABCD-1234;id', '../1234', 'ABCD-1234\n', 'GGGG-1234']:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                lib.usb_value(value)

    def test_temporary_root_proof_bound_to_current_device_and_boot(self):
        proof = {'root_proven': True, 'boot_id': 'boot', 'device_binding': 'binding'}
        marker = 'ONN-MAGISK-26-20261021'
        install.validate_temporary_proof(proof, 'boot', 'binding', marker)
        for changed in [
            ({**proof, 'root_proven': False}, 'boot', 'binding', marker),
            (proof, 'new-boot', 'binding', marker),
            (proof, 'boot', 'other-device', marker),
            (proof, 'boot', 'binding', ''),
        ]:
            with self.assertRaises(RuntimeError):
                install.validate_temporary_proof(*changed)

    def test_partition_readback_and_unrelated_changes(self):
        before = partitions()
        after = {**before, lib.PROFILE['boot_target']: lib.PROFILE['expected_patched_sha256']}
        install.check_partition_result(before, after)
        for name in after:
            with self.subTest(partition=name), self.assertRaises(RuntimeError):
                install.check_partition_result(before, {**after, name: 'bad'})
        with self.assertRaises(RuntimeError):
            install.check_partition_result(before, {lib.PROFILE['boot_target']: lib.PROFILE['expected_patched_sha256']})

    def test_image_rejects_wrong_input_and_wrong_output(self):
        stock = gzip.decompress((lib.ROOT / 'firmware/stock-boot-15051976.img.gz').read_bytes())
        self.assertEqual(len(stock), lib.PROFILE['stock_boot_size'])
        self.assertEqual(hashlib.sha256(stock).hexdigest(), lib.PROFILE['stock_boot_sha256'])
        with self.assertRaisesRegex(RuntimeError, 'Unexpected boot image size'):
            lib.validate_patched_image(stock, stock[:-1])
        with self.assertRaisesRegex(RuntimeError, 'Wrong stock image'):
            lib.validate_patched_image(bytes(len(stock)), stock)
        with self.assertRaisesRegex(RuntimeError, 'differs from the tested layout'):
            lib.validate_patched_image(stock, stock)

    def test_install_template_does_not_accept_shell_injection(self):
        remote = '/data/local/tmp/onn-guide-install-20261021T000000Z-1234abcd'
        boot = '00000000-0000-4000-8000-000000000000'
        for name in ['apply-boot-b.sh.in', 'restore-stock-boot-b.sh.in']:
            result = install.render_template(name, remote, boot)
            self.assertNotIn('@DEVICE_DIR@', result)
            subprocess.run(['sh', '-n'], input=result, text=True, check=True)
            with self.assertRaises(RuntimeError):
                install.render_template(name, remote + ';id', boot)
            with self.assertRaises(RuntimeError):
                install.render_template(name, remote, boot + '$(id)')

    def test_magisk_inputs_from_official_apk(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'environment'
            onn.extract_magisk(dest, complete=True)
            expected = {'magisk', 'magiskboot', 'magiskinit', 'magiskpolicy', 'busybox',
                        'init-ld', 'stub.apk', 'boot_patch.sh', 'util_functions.sh',
                        'app_functions.sh', 'module_installer.sh', 'uninstaller.sh',
                        'addon.d.sh', 'bootctl', 'chromeos/futility', 'chromeos/kernel.keyblock',
                        'chromeos/kernel_data_key.vbprivk'}
            self.assertEqual({str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file()}, expected)

    def test_setup_and_address_change_never_execute_adb(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(onn, 'WORK', Path(directory)), \
                patch.object(onn.subprocess, 'run', side_effect=AssertionError('Unexpected process/device execution')):
            args = SimpleNamespace(target='192.0.2.10:5555', usb_uuid='abcd-1234', adb=None, new_run=False)
            onn.setup(args)
            config = lib.read(Path(directory) / 'current.json')
            run = Path(directory) / 'runs' / config['run_id']
            for kind in ['read', 'unlock', 'root']:
                module = lib.load_transport(run / kind)
                self.assertEqual(module.verify_local()['usb_mount'], '/storage/ABCD-1234/ONN' + {'read':'23','unlock':'24','root':'26'}[kind])
            with self.assertRaises(RuntimeError):
                onn.setup(args)
            sentinel = run / 'unlock/sessions/preserve-me.txt'
            sentinel.write_text('existing capture')
            onn.set_target(SimpleNamespace(target='192.0.2.11:5555'), config, run)
            self.assertEqual(sentinel.read_text(), 'existing capture')
            self.assertEqual(lib.read(Path(directory) / 'current.json')['target'], '192.0.2.11:5555')
            for kind in ['read', 'unlock', 'root']:
                self.assertEqual(lib.load_transport(run / kind).TARGET, '192.0.2.11:5555')
                lib.load_transport(run / kind).verify_local()

    def test_reboot_request_cannot_be_repeated(self):
        device = lib.Device({'target': '192.0.2.10:5555'}, Path('/nonexistent'))
        with patch.object(device, 'call', side_effect=AssertionError('No reboot permitted')):
            with self.assertRaises(RuntimeError):
                device.reboot_wait({'reboot_requested': True}, Path('/unused'))

    def test_root_identity_requires_success_and_uid_zero(self):
        device = SimpleNamespace(root=lambda *args, **kwargs: SimpleNamespace(stdout='uid=2000(shell)'))
        with self.assertRaises(RuntimeError):
            install.root_identity(device)


class FakeDevice:
    config = {'run_id': '20261021T000000Z-1234abcd'}
    marker = ''
    usb = False
    boot = 'new-boot'
    root_ok = True
    calls = None

    def __init__(self):
        self.calls = []
        self.hashes = {**partitions(), lib.PROFILE['boot_target']: lib.PROFILE['expected_patched_sha256']}

    def preflight(self, state):
        lib.check_properties(properties(), state)

    def binding(self):
        return 'binding'

    def usb_present(self):
        return self.usb

    def boot_id(self):
        return self.boot

    def property(self, name):
        assert name == 'ro.boot.onn_rootprobe'
        return self.marker

    def root(self, command, **kwargs):
        self.calls.append(command)
        if command == 'id':
            return SimpleNamespace(stdout='uid=0(root)' if self.root_ok else 'uid=2000(shell)')
        if command == '/debug_ramdisk/magisk -V':
            return SimpleNamespace(stdout='30700')
        assert command == install.ENV_CHECK
        return SimpleNamespace(stdout='MAGISK_ENVIRONMENT_VERIFIED')

    def inspect_startup(self, **kwargs):
        return {'before': lib.PROFILE['stock_startup']}

    def partition_hashes(self):
        return self.hashes

    def reboot_wait(self, *args):
        raise AssertionError('Verification-only command must not reboot')


class PermanentProofTests(unittest.TestCase):
    def run_verification(self, device):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            lib.save(run / 'install/receipt.json', {
                'device_binding': 'binding', 'remote_directory': '/data/local/tmp/onn-guide-install-' + device.config['run_id'],
                'flash_verified': True, 'boot_id_before': 'old-boot',
                'partition_hashes_before': partitions(),
            })
            install.verify(device, run, SimpleNamespace(reboot=False, usb_removed=False))
            return lib.read(run / 'permanent-root-proof.json')

    def test_permanent_root_requires_all_independent_checks(self):
        result = self.run_verification(FakeDevice())
        self.assertTrue(result['permanent_root_proven'])
        for attr, value in [('usb', True), ('marker', 'ONN-MAGISK-26-20261021'),
                            ('boot', 'old-boot'), ('root_ok', False)]:
            with self.subTest(attr=attr), self.assertRaises(RuntimeError):
                device = FakeDevice()
                setattr(device, attr, value)
                self.run_verification(device)
        device = FakeDevice()
        device.hashes['/dev/block/by-name/vbmeta_b'] = 'changed'
        with self.assertRaises(RuntimeError):
            self.run_verification(device)


if __name__ == '__main__':
    unittest.main()
