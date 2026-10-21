from contextlib import contextmanager, ExitStack, redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import onnlib as lib


class UnlockHandoffTests(unittest.TestCase):
    @contextmanager
    def prepared_device(self, directory, reboot_result='ok', fail_before_reboot=None):
        kit = lib.ROOT / 'kits/unlock'
        module = lib.load_transport(kit)
        plan = lib.read(kit / 'experiment-plan.json')
        device = module.Device(plan, Path(directory), {
            'action': 'test', 'reboot_requested': False, 'android_returned': False,
            'original_startup_restored_and_verified': False,
        })
        calls = []
        reboot_sent = False

        def adb(*args, **kwargs):
            nonlocal reboot_sent
            self.assertFalse(reboot_sent, 'No device access is allowed after requesting reboot')
            calls.append(args)
            if args == ('reboot',):
                saved = lib.read(Path(directory) / 'roundtrip.json')
                self.assertTrue(saved['reboot_requested'])
                self.assertTrue(saved['awaiting_factory_reset'])
                reboot_sent = True
                if reboot_result == 'timeout':
                    raise subprocess.TimeoutExpired('adb reboot', 10)
                if reboot_result == 'interrupt':
                    raise KeyboardInterrupt()
                if reboot_result == 'oserror':
                    raise OSError('Reboot client interrupted')
                return SimpleNamespace(returncode=1 if reboot_result == 'nonzero' else 0,
                                       stdout='', stderr='')
            if (fail_before_reboot == 'gate' and args[0] == 'push'
                    and args[-1].endswith('ONN24TMP.TXT')):
                raise RuntimeError('Gate upload failed')
            output = ''
            if args[:2] == ('shell', 'sha256sum'):
                output = (plan['payload_sha256'] if args[2].endswith(plan['payload_file'])
                          else plan['input_gate_sha256']) + '  fixture'
            return SimpleNamespace(returncode=0, stdout=output, stderr='')

        with ExitStack() as stack:
            stack.enter_context(patch.object(module.subprocess, 'run', side_effect=AssertionError('No real process permitted')))
            stack.enter_context(patch.object(module.time, 'sleep', side_effect=AssertionError('No polling wait permitted')))
            stack.enter_context(patch.object(device, 'adb', side_effect=adb))
            stack.enter_context(patch.object(device, 'check_device'))
            stack.enter_context(patch.object(device, 'prop', side_effect={
                'ro.boot.flash.locked': '1', 'ro.boot.vbmeta.device_state': 'locked',
                'ro.boot.verifiedbootstate': 'green',
            }.__getitem__))
            stack.enter_context(patch.object(device, 'exists', side_effect=lambda path, directory=False: directory))
            stack.enter_context(patch.object(device, 'fresh', return_value={'service_pid': 42}))
            stack.enter_context(patch.object(device, 'boot_id', return_value='00000000-0000-4000-8000-000000000000'))
            stack.enter_context(patch.object(device, 'action', return_value={'after': plan['candidate']},
                side_effect=RuntimeError('Startup write failed') if fail_before_reboot == 'startup' else None))
            restore = stack.enter_context(patch.object(device, 'restore'))
            cleanup = stack.enter_context(patch.object(device, 'remove_gate'))
            capture = stack.enter_context(patch.object(device, 'capture'))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            yield device, calls, restore, cleanup, capture, output

    def test_reboot_returns_control_without_polling_restoring_or_collecting(self):
        for outcome in ('ok', 'nonzero', 'timeout'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                with self.prepared_device(directory, outcome) as (device, calls, restore, cleanup, capture, output):
                    device.test()
                    self.assertEqual(calls[-1], ('reboot',))
                    self.assertEqual(calls.count(('reboot',)), 1)
                    restore.assert_not_called()
                    cleanup.assert_not_called()
                    capture.assert_not_called()
                    saved = lib.read(Path(directory) / 'roundtrip.json')
                    self.assertTrue(saved['awaiting_factory_reset'])
                    self.assertFalse(saved['android_returned'])
                    self.assertFalse(saved['original_startup_restored_and_verified'])
                    self.assertNotIn('error', saved)
                    if outcome != 'ok':
                        self.assertTrue(saved['reboot_delivery_uncertain'])
                    self.assertIn('Come back when you have finished resetting and setting up your device.', output.getvalue())

    def test_interrupted_reboot_still_never_contacts_device_or_replays_request(self):
        for outcome, error in [('interrupt', KeyboardInterrupt), ('oserror', OSError)]:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                with self.prepared_device(directory, outcome) as (device, calls, restore, cleanup, capture, _):
                    with self.assertRaises(error):
                        device.test()
                    self.assertEqual(calls[-1], ('reboot',))
                    self.assertEqual(calls.count(('reboot',)), 1)
                    restore.assert_not_called()
                    cleanup.assert_not_called()
                    capture.assert_not_called()
                    saved = lib.read(Path(directory) / 'roundtrip.json')
                    self.assertTrue(saved['reboot_requested'])
                    self.assertIn('error', saved)

    def test_startup_write_failure_before_reboot_still_restores_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.prepared_device(directory, fail_before_reboot='startup') as (device, calls, restore, _, _, _):
                with self.assertRaisesRegex(RuntimeError, 'Startup write failed'):
                    device.test()
                restore.assert_called_once()
                self.assertNotIn(('reboot',), calls)
                self.assertFalse(device.report['reboot_requested'])
                self.assertNotIn('awaiting_factory_reset', device.report)

    def test_gate_upload_failure_before_startup_write_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.prepared_device(directory, fail_before_reboot='gate') as (device, calls, restore, cleanup, _, _):
                with self.assertRaisesRegex(RuntimeError, 'Gate upload failed'):
                    device.test()
                cleanup.assert_called_once()
                restore.assert_not_called()
                self.assertNotIn(('reboot',), calls)
                self.assertFalse(device.report['reboot_requested'])


if __name__ == '__main__':
    unittest.main()
