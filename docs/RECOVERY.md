# Recovery and stopping conditions

**Earlier onn. 4K Pro (jarvis / SNA) only. The new 2026 hardware model is unsupported and untested; do not use these files on it.**

**Only tested on firmware URO4.260304.011.B1 / 15051976, Android TV 14, security patch 2026-03-01, bootloader 01.01.260304.175641, slot _b. It can erase data or permanently brick the device. Recovery is not guaranteed.**

Preserve work/ and thumb drive captures. Do not delete guards or create a fresh run to force a retry.

## Before internal flashing

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

Keep backups and receipts. Do not relock with a modified image, use automatic Magisk installation, or switch slots based on this guide. OTA behavior and other firmware are untested.
