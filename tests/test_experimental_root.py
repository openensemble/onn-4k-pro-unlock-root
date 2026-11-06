import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import experimental_root as experimental
import onn
import onnlib as lib
import root_install
import wizard


class ExperimentalRootTests(unittest.TestCase):
    def fixture(self, run, slot='_a'):
        identity=hashlib.sha256(b'EXPERIMENTAL-FIXTURE').hexdigest()
        config={'firmware_mode':'experimental-unlock-16202347','active_slot':slot}
        device=Mock(config=config,profile=lib.run_profile(config))
        device.binding.return_value='fixture-binding'
        device.shell.return_value=SimpleNamespace(stdout='[ro.serialno]: [EXPERIMENTAL-FIXTURE]\n')
        proof={'properties':{'ro.build.fingerprint':lib.NEW_PROFILE['fingerprint'],
                             'ro.boot.flash.locked':'0','ro.boot.vbmeta.device_state':'unlocked',
                             'ro.boot.slot_suffix':slot},'stock_startup':'run storeboot_base;',
               'hardware_identity':identity,'device_binding':'fixture-binding'}
        lib.save(run/'unlocked-proof.json',proof)
        session=run/'unlock/sessions/fixture'
        lib.save(session/'roundtrip.json',{'action':'test'})
        lib.save(session/'capture-validation.json',{'unlock_request_accepted':True,'secure_state_change_observed':True})
        return device,proof

    def test_consent_requires_successful_unlock_and_same_physical_installation(self):
        for failure in ('missing-proof','failed-capture','different-hardware','different-installation','slot-changed'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                run=Path(directory);device,proof=self.fixture(run)
                if failure=='missing-proof': (run/'unlocked-proof.json').unlink()
                elif failure=='failed-capture': lib.save(run/'unlock/sessions/fixture/capture-validation.json',{'unlock_request_accepted':False})
                elif failure=='different-hardware': proof['hardware_identity']='other'
                elif failure=='different-installation': proof['device_binding']='other'
                elif failure=='slot-changed': proof['properties']['ro.boot.slot_suffix']='_b'
                if failure not in ('missing-proof','failed-capture'): lib.save(run/'unlocked-proof.json',proof)
                with self.assertRaises(RuntimeError): experimental.accept(device,run)
                self.assertFalse((run/'experimental-root-consent.json').exists())
                device.root.assert_not_called();device.call.assert_not_called()

    def test_explicit_consent_only_records_bound_choice_and_never_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);device,proof=self.fixture(run)
            experimental.accept(device,run)
            consent=experimental.check(device,run)
            self.assertTrue(consent['experimental_root_accepted'])
            self.assertTrue(consent['sole_responsibility_accepted'])
            self.assertFalse(consent['root_tested_on_hardware'])
            device.root.assert_not_called();device.call.assert_not_called()
            proof['stock_startup']='changed';lib.save(run/'unlocked-proof.json',proof)
            with self.assertRaises(RuntimeError): experimental.check(device,run)

    def test_root_question_follows_proof_and_no_never_runs_a_root_action(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);device,proof=self.fixture(run)
            guide=wizard.Guide(device.config,run,{'stage':'root-choice'})
            events=[]
            def check(d,r): events.append('verified')
            def ask(prompt):
                self.assertEqual(events,['verified'])
                self.assertIn('EXPERIMENTAL root',prompt)
                return 'n'
            with patch.object(guide,'connection',return_value=device),patch.object(experimental,'unlocked_run',side_effect=check), \
                    patch.object(wizard,'ask',side_effect=ask),patch.object(guide,'action',side_effect=AssertionError('Decline must not start root')):
                guide.execute()
            self.assertEqual(guide.state['stage'],'complete')
            self.assertEqual(guide.state['root_choice'],'declined')

    def test_failed_unlock_proof_prevents_even_showing_root_question(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);device,proof=self.fixture(run)
            guide=wizard.Guide(device.config,run,{'stage':'root-choice'})
            with patch.object(guide,'connection',return_value=device),patch.object(experimental,'unlocked_run',side_effect=RuntimeError('Unlock not proved')), \
                    patch.object(wizard,'ask',side_effect=AssertionError('No root question before proof')):
                with self.assertRaisesRegex(RuntimeError,'Unlock not proved'): guide.execute()

    def test_yes_has_separate_confirmation_then_opt_in_before_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);device,proof=self.fixture(run)
            guide=wizard.Guide(device.config,run,{'stage':'root-choice'})
            events=[]
            def confirm(message,phrase):
                self.assertIn('NOT HARDWARE TESTED',message)
                self.assertIn('PERMANENTLY BRICK',message)
                self.assertIn('authors do not take responsibility',message)
                self.assertEqual(phrase,'I ACCEPT SOLE RESPONSIBILITY FOR EXPERIMENTAL ROOT')
                events.append('consent')
            def action(arguments,next_stage=None,**kwargs):
                self.assertEqual(events,['consent'])
                self.assertEqual(arguments,['experimental-root','--accept-untested-brick-risk','--accept-sole-responsibility'])
                self.assertEqual(next_stage,'patch')
                self.assertEqual(lib.read(run/'wizard.json')['root_choice'],'accepted')
                # Stop at this boundary: the following patch/reboot must not be automatic in this test.
                raise wizard.Paused()
            with patch.object(guide,'connection',return_value=device),patch.object(wizard,'ask',return_value='y'), \
                    patch.object(wizard,'confirm',side_effect=confirm),patch.object(guide,'action',side_effect=action):
                with self.assertRaises(wizard.Paused): guide.execute()

    def test_each_slot_renders_new_firmware_target_and_exact_recovery_image(self):
        remote='/data/local/tmp/onn-guide-install-20261106T000000Z-1234abcd'
        boot='00000000-0000-4000-8000-000000000000'
        for slot in ('_a','_b'):
            profile=lib.run_profile({'firmware_mode':'experimental-unlock-16202347','active_slot':slot})
            for name in ('apply-boot-b.sh.in','restore-stock-boot-b.sh.in'):
                with self.subTest(slot=slot,template=name):
                    script=root_install.render_template(name,remote,boot,profile)
                    subprocess.run(['sh','-n'],input=script,text=True,check=True)
                    self.assertIn('TARGET=/dev/block/by-name/boot'+slot,script)
                    self.assertIn(profile['boot_device'],script)
                    self.assertIn(lib.NEW_PROFILE['stock_boot_sha256'],script)
                    self.assertIn(lib.NEW_PROFILE['expected_patched_sha256'],script)
                    self.assertNotIn(lib.PROFILE['stock_boot_sha256'],script)
                    self.assertNotIn(lib.PROFILE['fingerprint'],script)
                    self.assertNotIn('init_boot',script)
                    self.assertNotIn('/dev/block/by-name/boot'+('_b' if slot=='_a' else '_a'),script)

    def test_temporary_root_requires_new_marker_and_bound_same_boot(self):
        proof={'root_proven':True,'boot_id':'boot','device_binding':'binding'}
        marker=lib.NEW_PROFILE['root_marker']
        root_install.validate_temporary_proof(proof,'boot','binding',marker,marker)
        for actual in ('','ONN-MAGISK-26-20261021'):
            with self.assertRaises(RuntimeError): root_install.validate_temporary_proof(proof,'boot','binding',actual,marker)

    def test_root_helper_is_separate_with_new_header_guard_and_no_shared_patch(self):
        kit=lib.ROOT/'kits/experimental-root'
        plan=lib.read(kit/'experiment-plan.json')
        with zipfile.ZipFile(next((kit/'build').glob('*.apk'))) as apk: dex=apk.read('classes.dex')
        self.assertIn(lib.NEW_PROFILE['fingerprint'].encode(),dex)
        self.assertIn(b'local.onn.experimentalmagisk',dex)
        self.assertNotIn(lib.PROFILE['fingerprint'].encode(),dex)
        self.assertIn(b'0x1b93d6',dex)
        self.assertIn(b'dc5000',dex)
        self.assertEqual(plan['payload_size'],0xdc5000)
        self.assertLess(int(plan['payload_load_end'],16),0x4000000)
        self.assertFalse((kit/plan['payload_file']).exists())

    def test_installer_uses_only_bound_slot_and_never_replays_a_write(self):
        for slot in ('_a','_b'):
            with self.subTest(slot=slot),tempfile.TemporaryDirectory() as directory:
                run=Path(directory); device,_=self.fixture(run,slot)
                device.config['run_id']='20261106T000000Z-1234abcd'
                boot='00000000-0000-4000-8000-000000000000'
                profile=device.profile
                device.boot_id.return_value=boot
                device.property.return_value=profile['root_marker']
                lib.save(run/'temporary-root-proof.json',{'root_proven':True,'boot_id':boot,'device_binding':'fixture-binding'})
                (run/'patched-boot.img').write_bytes(b'fake target-created image')
                before={profile['boot_target']:profile['stock_boot_sha256'],
                        '/dev/block/by-name/boot'+('_b' if slot=='_a' else '_a'):'other-boot',
                        '/dev/block/by-name/vbmeta'+slot:'vbmeta',
                        '/dev/block/by-name/vendor_boot'+slot:'vendor-boot'}
                device.partition_hashes.side_effect=[before,{**before,profile['boot_target']:profile['expected_patched_sha256']}]
                device.read_partition.side_effect=lambda name,path:path.write_bytes(b'fake stock backup')
                uploads={}
                def upload(*args,**kwargs):
                    self.assertEqual(args[0],'push')
                    uploads[Path(args[2]).name]=Path(args[1])
                device.call.side_effect=upload
                def rooted(command,**kwargs):
                    if command=='id': output='uid=0(root)'
                    elif command.startswith('sha256sum '): output=lib.digest(uploads[Path(command.split()[1]).name])+'  file'
                    elif command.endswith(' check'): output='ALL_INSTALL_GUARDS_PASSED'
                    elif command.endswith('setup-environment.sh'): output='MAGISK_ENVIRONMENT_VERIFIED'
                    elif command.endswith(' apply-authorized'): output='PATCHED_BOOT'+slot.upper()+'_READBACK_VERIFIED'
                    else: output=''
                    return SimpleNamespace(stdout=output,stderr='',returncode=0)
                device.root.side_effect=rooted
                def environment(path,complete=False):
                    path.mkdir(); (path/'fixture').write_bytes(b'fake environment')
                with patch.object(onn,'check_patch_binding',return_value={'device_binding':'fixture-binding'}), \
                        patch.object(onn,'extract_magisk',side_effect=environment):
                    root_install.install(device,run,device.config)
                    receipt=lib.read(run/'install/receipt.json')
                    self.assertTrue(receipt['flash_verified'])
                    self.assertEqual(receipt['active_slot'],slot)
                    self.assertEqual(device.read_partition.call_args.args[0],'boot'+slot)
                    self.assertEqual(root_install.saved_install(device,run),receipt)
                    with self.assertRaisesRegex(RuntimeError,'attempt exists'):
                        root_install.install(device,run,device.config)
                    writers=[c.args[0] for c in device.root.call_args_list if c.args[0].endswith(' apply-authorized')]
                    self.assertEqual(len(writers),1)
                    self.assertIn('apply-boot-'+slot[-1]+'.sh',writers[0])
                    device.reboot_wait.assert_not_called()
                    receipt['active_slot']='_b' if slot=='_a' else '_a'
                    lib.save(run/'install/receipt.json',receipt)
                    with self.assertRaisesRegex(RuntimeError,'firmware/slot'):
                        root_install.saved_install(device,run)


if __name__=='__main__': unittest.main()
