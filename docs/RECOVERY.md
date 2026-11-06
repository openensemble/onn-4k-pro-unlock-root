# Recovery and stopping conditions

**Earlier onn. 4K Pro (jarvis / SNA) only. The new 2026 hardware model is unsupported and untested; do not use these files on it.**

**The original unlock/reset/root was tested on 15051976, slot B. A later update of that already-unlocked box to 16202347, slot A, retained setup and root. Fresh unlocking and first-time root on 16202347 remain UNTESTED. All device-write paths can erase data or permanently brick the device. Recovery is not guaranteed.**

The reset instructions below describe the original 15051976 unlock measurement. They are not a demonstrated new-firmware unbrick method. Experimental unlock/root users are solely responsible for choosing the risk and resulting loss or damage; the project authors take no responsibility for it.

Preserve work/ and thumb drive captures. Do not delete guards or create a fresh run to force a retry.

## During the reviewed firmware update

Use the [dedicated update guide](FIRMWARE_UPDATE.md). If a flash or native OTA
result is uncertain, keep power on and preserve `work/firmware-updates/`.
Do not repeat `--apply`, reboot, reset or switch slots. `--verify` can reconcile
completed writes from Android status and exact hashes without replaying them.
A missing debugging connection may only require authorizing the computer again.

The new boot_a write has a best-effort verified restore of the **new stock image**
while Android/root remain available. It cannot recover after loss of power,
storage or the running shell. Do not use the original boot_b restore command or
an old boot image after upgrading. Rollback metadata increased; an intact old
boot partition does not establish a working downgrade.

Keep OTA-pause modules disabled until snapshot merge completes. The updater
restores prior controls after merge. A factory reset does not repair an invalid
boot partition and would erase the setup the updater is intended to preserve.

## Before internal flashing in an unlock/root experiment

Let a failed read or USB boot helper finish its timeout. Remove the thumb drive and power-cycle once if needed. The tested candidates fall back to stock startup without their USB gate.

When Android and authorized ADB return, restore the kit involved:

- Read: python3 onn.py restore-startup --kit read
- Unlock: python3 onn.py restore-startup --kit unlock
- Temporary root: python3 onn.py restore-startup --kit root

If the IP changed, use set-target first as in README. Restore only replaces its own known candidate, then verifies original startup through a fresh vendor service. An unfamiliar startup value stops it.

Android returning is not proof of unlocking or root. Inspect captures; do not repeat an ambiguous secure-state write.

## Android cannot load after unlock

The unlock command stops contacting the Onn 4K Pro after requesting the reboot. Wait for “Can't load Android system. Your data may be corrupt” to appear before removing the thumb drive. Collect its result on the computer as described in README. Check for an accepted request and secure-state change 1 → 0.

Our box required stock recovery's factory data reset. Leave the thumb drive removed and use the button on the front of the Onn 4K Pro:

1. Use quick presses to cycle through the menu to **Factory data reset**.
2. Press and hold the button to select the option. The bar will turn green.
3. Press the button once more to confirm the selection.

**This erases apps, accounts, and settings.** Complete Android setup, re-enable and authorize ADB, restore startup, and verify unlocked/orange state. Repeated power cycles did not resolve the corruption screen.

The guided setup waits at the `ANDROID READY` prompt while you reset and set up the Onn 4K Pro. It only starts looking for the device after you enter that confirmation. Accept the debugging authorization on the Onn 4K Pro when prompted. You can quit the guide and run `python3 onn.py` again to return to this step.

If recovery input does not work, stop and obtain working menu controls. Cable recovery mode has not been validated here. Missing proof is not permission to assume success.

## After writing internal boot_b

**Removing the thumb drive cannot restore boot_b. Do not assume a factory reset repairs a damaged boot image.**

If readback is unverified, do not reboot or power off while Android/root still work. Inspect work/runs/<run>/install/flash.log and receipt.json. A timeout may mean a write completed, failed, or is still running. Resolve that before starting any writer.

The apply script attempts a stock restore on write/readback failure, then reports whether restoration was verified. This requires the shell and storage to remain working.

If root still works and the image state is known:

    python3 onn.py restore-stock --accept-risk

This explicitly restores the saved, hash-checked stock boot_b when the current partition is the exact tested patched image or already stock. It refuses unknown or partially written images for manual review. It keeps the AVB bootloader unlocked, changes no other partition, and does not reboot.

Without Android/root, this command cannot help. The firmware profile includes the signed OTA URL/checksum for reference, but **a working recovery installation path for that OTA was not demonstrated**. Fastboot rescue, hardware flashing, and recovery from a fully bricked device remain untested.

## After success

Keep backups and receipts. Do not relock with a modified image, use automatic Magisk installation, or switch slots based on this guide. Only the specifically documented upgrade has been measured. Fresh new-firmware unlocking, other update paths and recovery remain untested.

For an experimental 16202347 root installation, the saved run binds recovery to
the actual active slot A or B and the **16202347** stock boot backup. Do not use
the original 15051976 image or switch slots as a rescue attempt. If ADB and root
still work, the guarded `restore-stock` command also requires
`--accept-risk --accept-untested-brick-risk --accept-sole-responsibility`.
It attempts only this run's same-build active-slot restore and does not reboot.
This is not a demonstrated recovery method on a newly unlocked 16202347 device.
