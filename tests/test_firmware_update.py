import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
import zlib

import firmware_update as update
import onn
import onnlib as lib
import wizard
from test_guards import properties


class FirmwareProfileTests(unittest.TestCase):
    def test_original_workflow_still_rejects_new_build(self):
        values=properties()
        values.update({'ro.build.fingerprint':lib.NEW_PROFILE['fingerprint'],
                       'ro.build.version.security_patch':'2026-09-01','ro.boot.slot_suffix':'_a'})
        with self.assertRaises(RuntimeError): lib.check_properties(values)
        lib.check_properties(values,'unlocked',lib.NEW_PROFILE)
        for name in values:
            with self.subTest(name=name),self.assertRaises(RuntimeError):
                lib.check_properties({**values,name:'wrong'},'unlocked',lib.NEW_PROFILE)

    def test_slots_are_explicit_and_update_only_covers_b_to_a(self):
        for slot in ('_a','_b'):
            config={'firmware_mode':'experimental-unlock-16202347','active_slot':slot}
            self.assertEqual(lib.run_profile(config)['active_slot'],slot)
        for config in ({'firmware_mode':'unknown'},
                       {'firmware_mode':'updated-16202347','active_slot':'_b'},
                       {'firmware_mode':'experimental-unlock-16202347','active_slot':'_c'}):
            with self.assertRaises(RuntimeError): lib.run_profile(config)

    def test_new_stock_archive_is_exact_pinned_image(self):
        import gzip
        archive=lib.ROOT/'firmware/stock-boot-16202347.img.gz'
        self.assertEqual(lib.digest(archive),lib.NEW_PROFILE['stock_boot_gzip_sha256'])
        stock=gzip.decompress(archive.read_bytes())
        self.assertEqual(len(stock),lib.NEW_PROFILE['stock_boot_size'])
        self.assertEqual(hashlib.sha256(stock).hexdigest(),lib.NEW_PROFILE['stock_boot_sha256'])
        with self.assertRaises(RuntimeError): lib.validate_patched_image(stock,stock,lib.NEW_PROFILE)


class BackupAndInputTests(unittest.TestCase):
    def archive(self,path):
        with tarfile.open(path,'w') as tar:
            for root in update.BACKUP_TREES:
                item=tarfile.TarInfo(root+'/test')
                item.size=4
                tar.addfile(item,io.BytesIO(b'data'))

    def test_backup_requires_all_trees_and_complete_end_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'backup.tar'
            self.archive(path)
            valid=path.read_bytes()
            self.assertTrue(update.validate_backup(path)['complete_archive_verified'])
            for malformed in (valid[:512],valid[:-1],valid[:9*1024]+bytes(512),valid+b'bad'):
                path.write_bytes(malformed)
                with self.assertRaises((RuntimeError,tarfile.TarError)): update.validate_backup(path)
            with tarfile.open(path,'w') as tar:
                item=tarfile.TarInfo('data/test'); item.size=1; tar.addfile(item,io.BytesIO(b'x'))
            with self.assertRaisesRegex(RuntimeError,'trees'): update.validate_backup(path)

    def test_only_known_live_socket_omissions_are_accepted(self):
        self.assertEqual(update.verify_tar_diagnostics('0','')['omitted_runtime_sockets'],0)
        self.assertEqual(update.verify_tar_diagnostics('1',"tar: unknown file type '140000'\ntar: had errors\n")['omitted_runtime_sockets'],1)
        for code,text in [('0','failed'),('1',''),('1','tar: Permission denied'),('137',"tar: unknown file type '140000'")]:
            with self.assertRaises(RuntimeError): update.verify_tar_diagnostics(code,text)

    def test_boot_control_crc_and_expected_slot_count(self):
        data=bytearray(32)
        data[:4]=b'_a\0\0'; struct.pack_into('<I',data,4,0x42414342)
        data[8:10]=bytes([1,2]); data[12]=15+(6<<4); data[14]=14+128
        struct.pack_into('<I',data,28,zlib.crc32(data[:28]))
        slots=update.boot_control(data)
        self.assertEqual(slots[0]['tries'],6); self.assertTrue(slots[1]['successful'])
        data[12]^=1
        with self.assertRaises(RuntimeError): update.boot_control(data)

    def test_pinned_ota_layout_and_hash_reject_other_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source.zip'; run=root/'run'; run.mkdir()
            payload=b'CrAU'+bytes(100)
            props={'FILE_HASH':'fixture','FILE_SIZE':str(len(payload))}
            with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('payload.bin',payload)
                archive.writestr('payload_properties.txt','\n'.join(k+'='+v for k,v in props.items()))
            profile={**lib.NEW_PROFILE,'ota_size':source.stat().st_size,'ota_sha256':lib.digest(source),
                     'payload_properties':props,'payload_size':len(payload),'payload_offset':30+len('payload.bin'),
                     'payload_metadata_size':24}
            with patch.object(update,'NEW_PROFILE',profile):
                update.prepare_ota(run,source)
                self.assertEqual((run/'payload-metadata.bin').read_bytes(),payload[:24])
                source.write_bytes(source.read_bytes()[:-1]+b'X')
                other=root/'other'; other.mkdir()
                with self.assertRaisesRegex(RuntimeError,'pinned'): update.prepare_ota(other,source)

    def test_status_parser_requires_real_callback(self):
        device=Mock()
        device.root.return_value=SimpleNamespace(returncode=124,stdout='[INFO] onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 0)\n',stderr='')
        self.assertEqual(update.engine_status(device),6)
        for code,text in [(0,''),(1,'onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)'),(124,'not a callback')]:
            device.root.return_value=SimpleNamespace(returncode=code,stdout=text,stderr='')
            with self.assertRaises(RuntimeError): update.engine_status(device)


class UpdateStateTests(unittest.TestCase):
    def device(self,directory):
        device=Mock()
        device.run=Path(directory)
        device.remote='/data/local/tmp/onn-firmware-20261106T000000Z-1234abcd'
        device.config={'run_id':'20261106T000000Z-1234abcd','target':'192.0.2.10:5555'}
        device.guard.return_value=properties()
        device.root.return_value=SimpleNamespace(stdout=lib.PROFILE['expected_patched_sha256']+'  /dev/block/by-name/boot_b\n',stderr='',returncode=0)
        return device

    def test_apply_never_replays_attempt_or_ambiguous_write(self):
        for stage in ('ota-attempted','root-write-attempted','ready-to-reboot','complete','preparing'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                device=self.device(directory)
                with self.assertRaises(RuntimeError): update.apply(device,{'stage':stage})
                device.guard.assert_not_called(); device.root.assert_not_called()

    def test_apply_rejects_missing_backup_before_engine_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            device=self.device(directory)
            with self.assertRaisesRegex(RuntimeError,'backup'):
                update.apply(device,{'stage':'prepared','backup_verified':False})
            device.root.assert_not_called()

    def test_wrong_stock_slot_hash_blocks_patch_before_marker_or_upload(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(update,'engine_status',return_value=6):
            device=self.device(directory)
            with self.assertRaisesRegex(RuntimeError,'partition verification'):
                update.install_new_root(device,{'stage':'ota-verified'})
            device.call.assert_not_called()
            self.assertTrue(all('head -c' in c.args[0] for c in device.root.call_args_list))

    def test_reboot_requires_verified_flash_and_no_previous_request(self):
        for report in ({'stage':'ota-attempted'},
                       {'stage':'ready-to-reboot','root_flash_verified':False},
                       {'stage':'ready-to-reboot','root_flash_verified':True,'reboot_requested':True}):
            with tempfile.TemporaryDirectory() as directory:
                device=self.device(directory)
                with self.assertRaises(RuntimeError): update.reboot(device,report)
                device.call.assert_not_called()

    def test_lost_ota_client_ack_is_reconciled_without_replaying_apply(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(update,'engine_start'), \
                patch.object(update,'engine_status',return_value=6),patch.object(update,'verify_new_slot') as verified:
            device=self.device(directory)
            device.property.return_value=lib.PROFILE['fingerprint']
            device.root.return_value=SimpleNamespace(stdout=lib.NEW_PROFILE['stock_boot_sha256']+'  boot_a')
            report={'stage':'ota-attempted','flash_attempted':True}
            update.verify(device,report)
            self.assertEqual(report['stage'],'ota-verified')
            verified.assert_called_once(); device.call.assert_not_called()

    def test_merge_finishes_before_restoring_pause_and_preserves_setup(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(update,'engine_start'), \
                patch.object(update,'engine_status',return_value=0),patch.object(update,'read_boot_control',return_value=[{'successful':True,'corrupt':False},{}]), \
                patch.object(update.time,'sleep'),patch.object(update,'associate_original_run'):
            device=self.device(directory)
            device.property.return_value=lib.NEW_PROFILE['fingerprint']
            device.boot_id.return_value='new-boot'
            before={'home':'fixture/.Home','packages':['a','b'],'android_id_hash':'binding'}
            report={'stage':'ready-to-reboot','root_flash_attempted':True,'device_binding':'binding','setup_before':before}
            states=iter(['Update state: merging\nMerge completion: 50%\n','Update state: none\n'])
            seen=[]
            def snapshot(d):
                value=next(states); seen.append(value); return value
            def restore(d,r):
                self.assertIn('Update state: none',seen[-1]); r['ota_policy_restored']=True
            with patch.object(update,'snapshot_state',side_effect=snapshot),patch.object(update,'setup_state',return_value=before), \
                    patch.object(update,'restore_policy',side_effect=restore) as policy:
                update.verify(device,report)
            self.assertEqual(report['stage'],'complete'); self.assertTrue(report['setup_preserved'])
            self.assertFalse(report['fresh_unlock_tested']); policy.assert_called_once()

    def test_pending_merge_never_restores_pause(self):
        device=Mock()
        with patch.object(update,'snapshot_state',return_value='Update state: merging\n'):
            with self.assertRaisesRegex(RuntimeError,'merge'): update.restore_policy(device,{})
        device.root.assert_not_called()

    def test_finished_verification_does_not_reapply_update_or_reboot(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(update,'read_boot_control',return_value=[{'successful':True,'corrupt':False},{}]), \
                patch.object(update,'engine_start') as start:
            device=self.device(directory); device.property.return_value=lib.NEW_PROFILE['fingerprint']
            update.verify(device,{'stage':'complete','root_flash_attempted':True})
            start.assert_not_called(); device.call.assert_not_called()
            self.assertEqual(len(device.root.call_args_list),1)

    def test_native_flash_template_targets_only_new_a_and_has_no_reboot(self):
        with tempfile.TemporaryDirectory() as directory:
            device=self.device(directory)
            text=update.render_boot_installer(device,{'boot_id_before':'00000000-0000-4000-8000-000000000000'})
            subprocess.run(['sh','-n'],input=text,text=True,check=True)
            self.assertIn('TARGET=/dev/block/by-name/boot_a',text)
            self.assertIn('NEW_STOCK_BOOT_A_RESTORED_AND_VERIFIED',text)
            self.assertNotIn('init_boot',text)
            self.assertFalse(any(line.strip()=='reboot' for line in text.splitlines()))
            with self.assertRaises(RuntimeError): update.render_boot_installer(device,{'boot_id_before':'bad; reboot'})

    def test_progress_reports_distinct_install_verify_and_finalize_phases(self):
        self.assertEqual(update.update_progress('onStatusUpdate(UPDATE_STATUS_DOWNLOADING (3), 0.42)'), 'Installing firmware: 42%')
        self.assertEqual(update.update_progress('onStatusUpdate(UPDATE_STATUS_VERIFYING (4), 0.6)'), 'Verifying firmware: 60%')
        self.assertIn('reboot has not been requested',update.update_progress('onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 0)'))


class ExperimentalUnlockTests(unittest.TestCase):
    def test_separate_apks_have_exact_new_guard_and_package(self):
        for kind in ('read','unlock'):
            kit=lib.ROOT/'kits'/('experimental-'+kind)
            plan=lib.read(kit/'experiment-plan.json')
            self.assertTrue(plan['experimental']); self.assertFalse(plan['fresh_unlock_hardware_tested'])
            with zipfile.ZipFile(next((kit/'build').glob('*.apk'))) as archive: dex=archive.read('classes.dex')
            self.assertIn(lib.NEW_PROFILE['fingerprint'].encode(),dex)
            self.assertNotIn(lib.PROFILE['fingerprint'].encode(),dex)
            self.assertIn(('local.onn.experimental'+kind).encode(),dex)
            self.assertEqual(lib.digest(kit/plan['payload_file']),plan['payload_sha256'])

    def test_setup_requires_both_risk_acknowledgments(self):
        for brick,responsibility in ((False,False),(True,False),(False,True)):
            args=SimpleNamespace(target='192.0.2.10:5555',usb_uuid='ABCD-1234',experimental_16202347=True,
                                 accept_untested_brick_risk=brick,accept_sole_responsibility=responsibility)
            with patch.object(onn.subprocess,'run',side_effect=AssertionError('No device calls')),self.assertRaisesRegex(RuntimeError,'solely responsible'):
                onn.setup(args)

    def test_manual_unlock_cannot_skip_experimental_risk_flags(self):
        config={'firmware_mode':'experimental-unlock-16202347'}
        for command in (['read-state','--accept-risk'],['unlock','--accept-data-loss'],
                        ['unlock','--accept-data-loss','--accept-untested-brick-risk']):
            with patch.object(sys,'argv',['onn.py',*command]),patch.object(onn,'verify_files',return_value=0), \
                    patch.object(onn,'configuration',return_value=(config,Path('/unused'))), \
                    patch.object(onn,'Device',side_effect=AssertionError('No device object permitted')), \
                    self.assertRaisesRegex(RuntimeError,'both --accept'):
                onn.main()

    def test_root_commands_require_separate_root_choice_even_with_general_risk_flags(self):
        for command in ('patch','root-test','install-root','restore-stock'):
            flags=[] if command=='patch' else ['--accept-risk','--accept-untested-brick-risk','--accept-sole-responsibility']
            with tempfile.TemporaryDirectory() as directory,patch.object(sys,'argv',['onn.py',command,*flags]),patch.object(onn,'verify_files',return_value=0), \
                    patch.object(onn,'configuration',return_value=({'firmware_mode':'experimental-unlock-16202347','target':'192.0.2.10:5555'},Path(directory))), \
                    patch.object(lib.subprocess,'run',side_effect=AssertionError('No device action without root consent')), \
                    self.assertRaisesRegex(RuntimeError,'root has not been accepted'):
                onn.main()

    def test_declined_root_choice_ends_without_device_or_root_action(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            lib.save(run/'unlocked-proof.json',{'properties':{'ro.boot.flash.locked':'0'}})
            guide=wizard.Guide({'firmware_mode':'experimental-unlock-16202347','active_slot':'_b'},run,{'stage':'complete','root_choice':'declined'})
            with patch.object(guide,'action',side_effect=AssertionError('No root/install action')),patch.object(guide,'connection',side_effect=AssertionError('No device contact')):
                guide.execute()


if __name__=='__main__': unittest.main()
