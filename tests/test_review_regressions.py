"""Offline regressions for interrupted updates and changed ADB addresses."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import firmware_update as update
import onn
import onnlib as lib


class AddressTests(unittest.TestCase):
    def setup_run(self, work):
        onn.setup(SimpleNamespace(target='192.0.2.10:5555', usb_uuid='ABCD-1234', adb=None, new_run=False))
        return lib.configuration()

    def check_targets(self, run, target):
        for kind in ('read', 'unlock', 'root'):
            transport=lib.load_transport(run/kind)
            transport.verify_local()
            self.assertEqual(transport.TARGET, target)

    def test_upgrade_address_change_keeps_helpers_and_later_changes_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            with patch.object(onn,'WORK',work), patch.object(lib,'WORK',work), patch.object(update,'WORK',work), \
                    patch.object(lib.subprocess,'run',side_effect=AssertionError('No device contact')):
                config,run=self.setup_run(work)
                lib.save(run/'install/receipt.json',{'device_binding':'fixture','flash_verified':True})
                lib.save(run/'permanent-root-proof.json',{'permanent_root_proven':True})
                device=Mock(config={'target':'192.0.2.20:5555'})
                device.boot_id.return_value='new-boot'
                update.associate_original_run(device,{'device_binding':'fixture',
                    'run_id':'20261106T000000Z-1234abcd','modules':[]})
                config,run=lib.configuration()
                self.assertEqual(config['firmware_mode'],'updated-16202347')
                self.assertEqual(config['target'],'192.0.2.20:5555')
                self.check_targets(run,config['target'])
                onn.set_target(SimpleNamespace(target='192.0.2.30:5555'),config,run)
                self.check_targets(run,'192.0.2.30:5555')
                device.root.assert_not_called(); device.call.assert_not_called()

    def test_interrupted_local_address_change_can_finish_without_device_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            with patch.object(onn,'WORK',work),patch.object(lib,'WORK',work), \
                    patch.object(lib.subprocess,'run',side_effect=AssertionError('No device contact')):
                config,run=self.setup_run(work)
                target='192.0.2.20:5555'
                runner=run/'read/test_later.py'
                runner.write_text(runner.read_text().replace(config['target'],target))
                # Simulate interruption after a helper changed, before resealing
                # its checksum or updating the other helpers/configuration.
                onn.set_target(SimpleNamespace(target=target),config,run)
                self.check_targets(run,target)
                self.assertEqual(lib.read(work/'current.json')['target'],target)

    def test_unknown_helper_target_does_not_partly_change_other_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            with patch.object(onn,'WORK',work),patch.object(lib,'WORK',work):
                config,run=self.setup_run(work)
                runner=run/'root/test_later.py'
                runner.write_text(runner.read_text().replace(config['target'],'192.0.2.99:5555'))
                before={kind:(run/kind/'test_later.py').read_bytes() for kind in ('read','unlock','root')}
                with self.assertRaisesRegex(RuntimeError,'Unexpected saved target'):
                    onn.set_target(SimpleNamespace(target='192.0.2.20:5555'),config,run)
                self.assertEqual(before,{kind:(run/kind/'test_later.py').read_bytes() for kind in before})
                self.assertEqual(lib.read(work/'current.json')['target'],'192.0.2.10:5555')


class ModuleMigrationTests(unittest.TestCase):
    def fixture(self, root):
        """Only local shell commands, with all Android paths mapped to temp dirs."""
        run=root/'run';run.mkdir()
        directory=root/'module';directory.mkdir()
        stage=root/'stage';stage.mkdir()
        device=Mock(run=run,remote='/data/local/tmp/onn-firmware-fixture')
        module={'path':update.MODULES[0],'files':{}}
        for name in ('pause.sh','restore-state.sh'):
            content='# original script\n'+lib.PROFILE['fingerprint']+'\n'
            local=run/name;local.write_text(content)
            (directory/name).write_text(content)
            module['files'][name]={'file':name,'sha256':lib.digest(local)}
        (directory/'owner').write_text('fixture owner')
        checksums=''.join(lib.digest(path)+'  '+path.name+'\n' for path in sorted(directory.iterdir()))
        (directory/'SHA256SUMS').write_text(checksums)
        (run/'SHA256SUMS').write_text(checksums)
        module['files']['SHA256SUMS']={'file':'SHA256SUMS','sha256':lib.digest(run/'SHA256SUMS')}
        device.environment=os.environ.copy()
        def rooted(command,**kwargs):
            command=command.replace(module['path'],str(directory)).replace(device.remote,str(stage))
            self.assertNotIn('/data/',command)
            result=subprocess.run(['sh','-c',command],capture_output=True,text=True,env=device.environment)
            lib.require(result.returncode==0,'Simulated device command failed')
            return result
        def transfer(action,source,destination,**kwargs):
            self.assertEqual(action,'push')
            self.assertTrue(destination.startswith(device.remote+'/'))
            shutil.copyfile(source,stage/Path(destination).name)
        device.root.side_effect=rooted;device.call.side_effect=transfer
        return device,module,directory

    def test_migration_checks_result_and_can_resume_with_already_updated_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            device,module,files=self.fixture(Path(directory))
            update.migrate_pause_module(device,module)
            for name,item in module['files'].items():
                if name != 'SHA256SUMS': self.assertIn(lib.NEW_PROFILE['fingerprint'],(files/name).read_text())
                self.assertEqual(lib.digest(files/name),item['updated_sha256'])
            subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=files,check=True,capture_output=True)
            uploads=device.call.call_count
            update.migrate_pause_module(device,module)
            self.assertEqual(device.call.call_count,uploads)

    def test_failed_copy_never_truncates_installed_script_and_retry_can_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);device,module,files=self.fixture(root)
            before={name:(files/name).read_bytes() for name in module['files']}
            stubs=root/'stubs';stubs.mkdir()
            # Fail during copying for both the former in-place cat and the
            # staged cp implementation, using actual host shell redirection.
            (stubs/'cat').write_text('#!/bin/sh\nprintf partial\nexit 1\n')
            (stubs/'cp').write_text('#!/bin/sh\nprintf partial > "$2"\nexit 1\n')
            for path in stubs.iterdir(): path.chmod(0o755)
            original=device.environment['PATH']
            device.environment['PATH']=str(stubs)+os.pathsep+original
            with self.assertRaisesRegex(RuntimeError,'Simulated device command failed'):
                update.migrate_pause_module(device,module)
            self.assertEqual(before,{name:(files/name).read_bytes() for name in before})
            device.environment['PATH']=original
            update.migrate_pause_module(device,module)
            self.assertIn(lib.NEW_PROFILE['fingerprint'],(files/'pause.sh').read_text())

    def test_corrupt_staged_copy_is_rejected_before_replacing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);device,module,files=self.fixture(root)
            before=(files/'pause.sh').read_bytes()
            stubs=root/'stubs';stubs.mkdir()
            (stubs/'cp').write_text('#!/bin/sh\nprintf corrupted > "$2"\nexit 0\n')
            (stubs/'cp').chmod(0o755)
            device.environment['PATH']=str(stubs)+os.pathsep+device.environment['PATH']
            with self.assertRaisesRegex(RuntimeError,'Simulated device command failed'):
                update.migrate_pause_module(device,module)
            self.assertEqual((files/'pause.sh').read_bytes(),before)


if __name__=='__main__': unittest.main()
