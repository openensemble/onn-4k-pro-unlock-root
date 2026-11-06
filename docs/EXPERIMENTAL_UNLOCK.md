# Experimental unlock and optional root on firmware 16202347 — UNTESTED

**Fresh unlocking and first-time root on build 16202347 have NOT been tested on hardware.** The
successful firmware upgrade was verified on **one already-unlocked device**;
that does not test a locked-to-unlocked transition on the new firmware.

**This attempt can erase all apps, accounts and settings, cause boot loops, or
PERMANENTLY BRICK your device. Recovery is not guaranteed. You are solely
responsible for choosing to take this risk and for all resulting loss, damage,
costs or loss of use. The project authors do not take responsibility for resulting
damage or data loss. Do not proceed unless you accept losing the device.**

The command line and guide require separate acknowledgments of this untested
brick risk and your sole responsibility. Accepting a prompt does not make the
procedure safe or establish that a recovery method works.

## Why an experimental option exists

The authenticated OTA's complete bootloader image and the inspected
SystemControl interfaces, SELinux policies and vendor trusted applications match
the previous firmware. That is [static compatibility evidence](../evidence/firmware-16202347-offline.json),
not proof that the secure-state write, reset recovery or a fresh unlock works.
Persistent state and live secure-firmware behavior can differ between devices.

The option uses separate new-firmware helper APKs with different Android package
IDs. Their embedded fingerprint guards accept only 16202347. The original
15051976 helpers and checks remain unchanged. The native guarded payloads are
unchanged; one-use gates, initial locked-state read, code-prefix checks, readback
and no automatic writer retry remain required.

## Exact target and prerequisites

- **2024 onn. 4K Pro / jarvis / SNA only.** The 2026 hardware and all other models
  remain unsupported.
- Exact fingerprint: `onn/jarvis/SNA:14/URO4.260304.092/16202347:user/release-keys`.
- Android 14, September 1, 2026 patch; bootloader `01.01.260304.175641`;
  first API 31; `armeabi-v7a` userspace.
- Locked/green, Android fully started, stock firmware. The guide binds the
  device's **existing** slot A or B. **Neither fresh-unlock slot is hardware tested.**
  Do not change slots to qualify or relock an already-rooted device for this test.
- Linux x86_64, Python 3.10+, network ADB, normal power and a USB thumb drive with
  a FAT32 first partition. Enable and authorize debugging. Have at least 1 GiB
  free on host, box and thumb drive. Back up everything you need first.

## Guided attempt

Use a separate checkout for a different device or workflow. Preserve existing
`work/` and USB evidence; do not discard an interrupted run to start another.

    python3 onn.py wizard --experimental-16202347

Or choose **3** from `python3 onn.py`. For an offline preview:

    python3 onn.py wizard --experimental-16202347 --preview

The guide requires `I ACCEPT SOLE RESPONSIBILITY` before starting and
`I ACCEPT SOLE RESPONSIBILITY FOR BRICKING` before the writer, in addition to
the data-loss confirmation. The secure-state read is itself experimental boot
code; it changes startup and reboots, and can also brick the device.

The sequence is: exact identity checks → original thumb drive selection → one
guarded locked-state read → one unlock attempt → offline USB result collection
→ owner-managed recovery/reset if required → same-device reconnection → normal
startup restoration → unlocked/orange verification → optional experimental root
choice. The root question appears **only after this run's successful unlock is
verified on the same device**.

Expect to lose the setup: the original firmware needed a factory reset after
unlock. On 16202347 the recovery behavior is **unverified**. If the expected
recovery screen does not appear, stop and preserve receipts; do not claim success
or rerun the writer. Follow [recovery conditions](RECOVERY.md), which describe
the original measurement and do not guarantee new-firmware rescue.

After successful verification, the guide asks **“Also try EXPERIMENTAL root on
this unlocked device?”** Choose **n** to finish with unlock only. Choose **y** to
see a separate warning and type `I ACCEPT SOLE RESPONSIBILITY FOR EXPERIMENTAL ROOT`.
Declining does not start a root boot or flash. An unsuccessful unlock never
reaches this choice.

If accepted, the guide patches the exact **16202347 stock boot on your device**
with Magisk 30.7, checks the result, and requests one USB root test. Only after
temporary root is proved does it offer the internal installation. That flash
needs another typed confirmation (`WRITE BOOT_A` or `WRITE BOOT_B` for your actual
slot). The guide then verifies root after a normal reboot with the thumb drive
removed and offers the usual optional firmware-update pause.

**The USB root test and internal flash are also experimental and can permanently
brick the device. You are solely responsible for choosing that risk and all
resulting damage or data loss; the project authors take no responsibility for
it.** Root retention during the measured upgrade does not validate first-time
root after a fresh unlock. Keep the bootloader unlocked. Do not use an old
firmware boot image, another person's patched image, or Magisk Direct Install;
the guarded installer targets the existing active `boot` slot, never `init_boot`.

## Manual commands

Read the whole guide first. Replace address and UUID placeholders, and replace
`a` below with the device's actual slot (`getprop ro.boot.slot_suffix` reports
`_a` or `_b`). Setup only creates a local run:

    python3 onn.py setup --target YOUR_ONN_IP:5555 --usb-uuid YOUR_USB_UUID --experimental-16202347 --slot a --accept-untested-brick-risk --accept-sole-responsibility
    python3 onn.py doctor
    python3 onn.py prepare-usb
    python3 onn.py read-state --accept-risk --accept-untested-brick-risk --accept-sole-responsibility

Only after the read reports locked state 1 and verified startup restoration:

    python3 onn.py unlock --accept-data-loss --accept-untested-brick-risk --accept-sole-responsibility

Do not repeat it. Wait for the expected recovery screen, then move the original
thumb drive to the computer and collect the result:

    python3 onn.py collect-unlock --usb-path YOUR_USB_MOUNT

Collection must prove an accepted request and state **1 → 0**. Follow the recovery
instructions, complete setup and reauthorize debugging. If the address changed,
use `set-target --target NEW_ONN_IP:5555` without creating a new run. Then:

    python3 onn.py restore-startup --kit unlock
    python3 onn.py verify-unlock

Stop here if you want unlock only. To accept **optional experimental root**, only
after successful unlock verification and reading the root warning above:

    python3 onn.py experimental-root --accept-untested-brick-risk --accept-sole-responsibility

That command records your choice for this verified device/run; it does not root
or reboot. Safely eject the original thumb drive from the computer and reconnect
it to the Onn. Keep its earlier captures and do not rerun `prepare-usb`. Then:

    python3 onn.py patch
    python3 onn.py root-test --accept-risk --accept-untested-brick-risk --accept-sole-responsibility

Grant Shell's Magisk Superuser request, then verify the same temporary boot:

    python3 onn.py root-proof

Only after that succeeds, install to the guarded active slot once:

    python3 onn.py install-root --accept-risk --accept-untested-brick-risk --accept-sole-responsibility

**Do not reboot if the flash/readback is not verified. Do not retry a writer.**
After verified installation, physically remove the thumb drive, then:

    python3 onn.py verify-root --reboot --usb-removed --accept-untested-brick-risk --accept-sole-responsibility

If a reboot was already requested, reauthorize debugging and run
`python3 onn.py verify-root` without `--reboot` to check its result. Preserve
receipts and follow [recovery conditions](RECOVERY.md) on any failure.

Keep the local receipts and captured result. A user's successful attempt is
evidence about that device, not automatic validation of all units or a reason
to remove the experimental warning.
