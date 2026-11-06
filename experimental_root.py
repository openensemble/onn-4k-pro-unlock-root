"""Explicit optional root consent, only after this run's experimental unlock proof."""
import discovery
from onnlib import NEW_PROFILE, digest, latest_session, now, read, require, save

WARNING = '''OPTIONAL EXPERIMENTAL ROOT — BUILD 16202347 — NOT HARDWARE TESTED.
Root retention during the upgrade worked on one already-rooted device.
First-time root after a fresh experimental unlock has NOT been tested.
The USB boot experiment and internal boot flash can erase data, cause boot loops,
or PERMANENTLY BRICK your device. Recovery is not guaranteed.
You are solely responsible for choosing to take this risk and all resulting loss,
damage, costs or loss of use. The project authors do not take responsibility for
any resulting damage or data loss. Do not proceed unless you accept losing the device.'''


def unlocked_run(device, run):
    require(device.config.get('firmware_mode') == 'experimental-unlock-16202347', 'Use this option only in the experimental workflow')
    require((run/'unlocked-proof.json').exists(), 'Verify experimental unlock before optional root')
    proof = read(run/'unlocked-proof.json')
    session = latest_session(run/'unlock')
    capture = read(session/'capture-validation.json')
    require(capture.get('unlock_request_accepted') and capture.get('secure_state_change_observed'),
            'This run has no successful experimental unlock capture')
    require(proof.get('properties', {}).get('ro.build.fingerprint') == NEW_PROFILE['fingerprint']
            and proof['properties'].get('ro.boot.flash.locked') == '0'
            and proof['properties'].get('ro.boot.vbmeta.device_state') == 'unlocked'
            and proof.get('stock_startup') == 'run storeboot_base;', 'Verify experimental unlock and restore normal startup first')
    device.preflight('unlocked')
    identity = discovery.device_identity(discovery.parse_properties(device.shell('getprop').stdout))
    require(proof.get('hardware_identity') == identity and proof.get('device_binding') == device.binding(),
            'Unlock proof belongs to a different device or Android installation')
    require(proof['properties']['ro.boot.slot_suffix'] == device.profile['active_slot'], 'Slot changed since unlock verification')
    return proof


def accept(device, run):
    proof = unlocked_run(device,run)
    path = run/'experimental-root-consent.json'
    if path.exists():
        check(device,run)
        print('Existing experimental root choice is bound to this verified unlock. No action repeated.')
        return
    save(path, {'time':now(), 'experimental_root_accepted':True, 'sole_responsibility_accepted':True,
                'hardware_identity':proof['hardware_identity'], 'device_binding':proof['device_binding'],
                'fingerprint':NEW_PROFILE['fingerprint'], 'active_slot':device.profile['active_slot'],
                'unlocked_proof_sha256':digest(run/'unlocked-proof.json'), 'warning':WARNING,
                'root_tested_on_hardware':False})
    print('Optional experimental root accepted after verified unlock. No boot or flash requested.')
    print('Next: python3 onn.py patch; then follow the experimental root instructions.')


def check(device, run):
    require((run/'experimental-root-consent.json').exists(),
            'Optional experimental root has not been accepted; verify unlock, then use experimental-root')
    proof = unlocked_run(device,run)
    consent = read(run/'experimental-root-consent.json')
    require(consent.get('experimental_root_accepted') is True and consent.get('sole_responsibility_accepted') is True
            and consent.get('device_binding') == proof['device_binding']
            and consent.get('hardware_identity') == proof['hardware_identity']
            and consent.get('active_slot') == device.profile['active_slot']
            and consent.get('unlocked_proof_sha256') == digest(run/'unlocked-proof.json'),
            'Missing or changed optional experimental-root consent; use experimental-root after verified unlock')
    return consent
