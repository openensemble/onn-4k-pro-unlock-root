# Earlier onn. 4K Pro (jarvis / SNA) — unlock and permanent root

<p align="center">
  <img src="assets/images/onn-4k-pro-2024.png" width="460" alt="Earlier Onn 4K Pro with fabric-covered top, four front lights, remote, and blue retail box">
</p>

**Supported device: the earlier Onn 4K Pro (2024, jarvis / SNA), pictured above.** [Photo: Walmart](https://www.walmart.com/ip/5193222892).

> **EARLIER MODEL ONLY. This guide is for the earlier onn. 4K Pro (jarvis / SNA), not the new 2026 hardware model. The [2026 model](https://www.walmart.com/ip/18382213962) is unsupported and untested. Do not use these files on it.**

> **WARNING: This process can erase all user data, cause boot loops, or permanently brick your device. Recovery is not guaranteed. Back up your data first and proceed only if you accept losing the device.**
>
> **Tested on ONE earlier-generation onn. Streaming Device 4K Pro, with ONLY the firmware below. No other firmware, bootloader version, model, or active slot has been tested. Do not bypass the checks.**

| Item | Only tested configuration |
| --- | --- |
| Model | Earlier onn. Streaming Device 4K Pro (jarvis / SNA) |
| Excluded hardware | New 2026 onn. 4K Pro — unsupported and untested |
| Android TV OS | 14 |
| OS build | **URO4.260304.011.B1.15051976** |
| Build ID / incremental | URO4.260304.011.B1 / 15051976 |
| Security patch | **March 1, 2026** (2026-03-01) |
| Bootloader | 01.01.260304.175641 |
| Active slot | _b |
| Root version | Magisk 30.7 (30700) |
| Test date | October 21, 2026 |

The **2026 security-patch and test dates refer to software and testing, not the hardware generation**. Our tested box is the earlier model. Match the product identity and every firmware check; the "4K Pro" name alone is insufficient.

URO4 contains the letter **O**. Exact fingerprint:

    onn/jarvis/SNA:14/URO4.260304.011.B1/15051976:user/release-keys

**Verified on our unit:** the AVB unlock survived a factory reset and normal reboot; Magisk root then survived another reboot with the thumb drive physically removed. Unlocking **required a factory reset**. Installing permanent root afterward preserved its new setup. See [recorded results](docs/RESULTS.md).

**Package status:** the original payloads and installation method worked on that one unit. The portable command wrapper has been checked offline; the complete packaged workflow has **not** been run end to end on the original box or another device. The same firmware string does not guarantee another unit will work. This remains a private experimental guide.

## Before starting

You need a Linux x86_64 computer with Python 3.10+, ADB access to your own box, its normal power supply, and a USB thumb drive with a FAT32 first partition. Keep at least 1 GB free on both computer and device. These commands create folders; they do not format the drive, but back it up if it contains anything you’ll need.

Read [recovery and stopping conditions](docs/RECOVERY.md) first. Know how to navigate your device's stock recovery menu. The tested route uses ADB and a thumb drive. Other host systems and USB connection modes are untested.

Keep firmware unchanged during the process. Start with the original boot image and slot _b. If the box is already modified, has different firmware, or uses slot _a, stop. This guide does not switch slots or downgrade firmware.

The guided setup checks the active slot automatically and only accepts `_b` (slot B). A device using `_a` (slot A) cannot be selected. To check it yourself, use the ADB command in [step 1](#1-connect-and-check-firmware).

Included inputs: three diagnostic APKs and source, native payloads and assembly, the exact compressed stock boot image, official Magisk APK, and Linux ADB. The patched image must be created on **your target device**, following [Magisk's installation guidance](https://topjohnwu.github.io/Magisk/install.html). Do not use another person's patched image.

## Guided setup (recommended)

After cloning run this command:

    python3 onn.py

The terminal guide includes the instructions at each step. It finds network ADB
devices, checks the exact firmware, and lets you select the Onn 4K Pro by number.
If no connected ADB devices are found, it searches port 5555 on the active local
IPv4 networks. You can also refresh, search again, or enter an address as a
fallback. Accept the debugging authorization on the Onn 4K Pro when prompted.
Discovery cannot enable debugging on a device that does not already expose
network ADB.

The guide lists thumb drives connected to the **Onn 4K Pro**, including their
labels, capacity, free space, and filesystem. Select the drive by number.
It checks the thumb drive's identity, a mounted FAT volume, and the first
partition. Android's storage report does not distinguish FAT16 from FAT32,
so you must confirm that you prepared it as FAT32. No drive is formatted.
Before booting from the thumb drive, leave only the selected thumb drive
connected to the Onn 4K Pro: the tested bootloader always uses its first USB disk,
whose ordering cannot be inferred safely from Android when several are attached.

After the unlock attempt, the guide explains when to move the thumb drive to the
**computer** and lists that computer's thumb drives. It accepts only a mounted
FAT32 volume with the UUID selected on the Onn 4K Pro. If the drive is unmounted,
open it in the file manager and refresh. It checks the captured result before
guiding recovery/setup and rediscovers the same physical Onn 4K Pro even if its
IP changed after the reset.

After verifying permanent root, the guide asks whether to disable automatic
firmware updates. Choose **y** to disable them or **n** to leave them unchanged.
The previous settings are saved so you can [restore them later](#7-optional-disable-automatic-firmware-updates).

Each risky action needs a separate typed confirmation. Progress and command logs
are saved in ignored `work/`. To exit, type `q` and press **Enter** at a prompt
inside the running guide. To resume later, run `python3 onn.py` from the
repository folder in your terminal. An interrupted unlock or flash is resolved
from its receipts; it is never blindly repeated. An unverified internal write stops the guide with
instructions to keep power on and inspect the saved result. Existing manual runs
are preserved and cannot be silently replaced by a guided run.

To see the current progress:

    python3 onn.py wizard --status

For discovery only (network ADB and Onn 4K Pro storage inspection; no setup or reboot):

    python3 onn.py wizard --discover-only

## Manual commands

The remaining sections document the individual commands used by the guide and
are available for manual operation and troubleshooting.

### 1. Connect and check firmware

Clone using:

    git clone https://github.com/openensemble/onn-4k-pro-unlock-root.git
    cd onn-4k-pro-unlock-root

Go to **Settings > System > About**, then click **Android TV OS build** **7 times** to enable developer mode. Return to Developer options and enable USB debugging. Menu labels can differ; see [Android's debugging instructions](https://developer.android.com/training/tv/get-started/create#run-on-a-physical-device).

Connect the box to the same trusted network as your computer, find its IP in Network settings, and accept debugging authorization on the Onn 4K Pro. ADB should be using port 5555. If that connection is refused, stop and resolve debugging access first.

Replace YOUR_ONN_IP below with your actual address:

    tools/linux/adb connect YOUR_ONN_IP:5555
    tools/linux/adb -s YOUR_ONN_IP:5555 shell getprop ro.build.fingerprint
    tools/linux/adb -s YOUR_ONN_IP:5555 shell getprop ro.boot.slot_suffix

The last command shows the active slot: `_a` means slot A and `_b` means slot B. This guide requires `_b`. If it returns `_a`, another value, or nothing, stop. Do not switch slots to bypass this requirement.

Plug the thumb drive into the **Onn 4K Pro**, wait for it to mount, then:

    tools/linux/adb -s YOUR_ONN_IP:5555 shell ls /storage

Find the FAT volume name, listed like ABCD-1234. Do not choose emulated or self. Replace both address and volume placeholders:

    python3 onn.py verify-files
    python3 onn.py setup --target YOUR_ONN_IP:5555 --usb-uuid YOUR_USB_UUID
    python3 onn.py doctor

Stop if a firmware check fails or ADB is unauthorized/offline. Inputs and receipts stay in ignored work/. Keep that folder for recovery; it contains device information and must not be uploaded blindly.

### 2. Prepare the thumb drive and read the lock state

Leave the thumb drive in the Onn 4K Pro and Android at its home screen:

    python3 onn.py prepare-usb

This command automatically creates the ONN23, ONN24, and ONN26 folders on the thumb drive if they are missing. If any of these folders already contains files, the command stops without deleting them. Preserve those files for review; do not erase them to force a retry.

    python3 onn.py read-state --accept-risk

This temporarily changes startup, reboots once, runs the stock secure-state getter, and restores normal startup through a fresh vendor service. It does not request an unlock, but experimental boot code still carries risk.

Continue only after success and proved locked state 1. On failure, follow recovery instructions; do not rerun automatically.

### 3. Unlock — expect a factory reset

**This writes the secure AVB lock state. It will erase data or potentially brick the box. The Onn 4K Pro will show “Can't load Android system. Your data may be corrupt” and will require a factory reset.**

    python3 onn.py unlock --accept-data-loss

Android will enter into recovery. After requesting the reboot, the command stops contacting the Onn 4K Pro. Wait for “Can't load Android system. Your data may be corrupt” to appear before removing the thumb drive. **Do not rerun unlock.**

Remove the thumb drive and connect it to your computer. Identify its mount directory, then replace YOUR_USB_MOUNT:

    python3 onn.py collect-unlock --usb-path YOUR_USB_MOUNT

The collector requires an accepted request and measured state change **1 → 0**. It preserves captures and removes an unconsumed one-use gate if present.

When the Onn 4K Pro is at the stock recovery corruption screen, leave the thumb drive removed and use the button on the front of the unit to select the menu's factory data reset:

1. Use quick presses to cycle through the menu to **Factory data reset**.
2. Press and hold the button to select the option. The bar will turn green.
3. Press the button once more to confirm the selection.

**This erases apps, accounts, and settings.** Complete Android setup again.

The guided setup pauses here: **Come back when you have finished resetting and setting up your device.** Re-enable USB debugging, then type `ANDROID READY` at the prompt inside the guide. It will start looking for the Onn 4K Pro only after that confirmation. Accept the debugging authorization on the Onn 4K Pro when prompted. If you exited the guide, run `python3 onn.py` again to return to the saved step.

Re-enable debugging and authorize the computer again. If the IP changed, preserve this run and update its target:

    python3 onn.py set-target --target YOUR_ONN_IP:5555

Restore and verify normal startup:

    python3 onn.py restore-startup --kit unlock
    python3 onn.py verify-unlock

Expected: flash.locked=0, vbmeta.device_state=unlocked, verifiedbootstate=orange, and startup "run storeboot_base;".

### 4. Create and test your own Magisk image

Put the same thumb drive back in the Onn 4K Pro. ONN26 should still be empty. Do not rerun prepare-usb now that earlier folders contain captures.

    python3 onn.py patch

This patches the verified stock image **on your box** with official Magisk 30.7 tools and installs the manager. It writes no firmware partition. The kernel must remain unchanged. Output must match the exact tested hash/layout or it stops. Matching output on another unit is unvalidated; investigate a mismatch instead of bypassing it or using a shared patched image.

    python3 onn.py root-test --accept-risk

This reboots once using the one-use image on the thumb drive, restores normal startup, and requests a root shell. Choose **Grant** for Shell on the Onn 4K Pro's Superuser prompt. If the prompt was missed and the same temporary-root boot is still running:

    python3 onn.py root-proof

The script displays `uid=0(root)` and verifies root automatically. Continue only after this confirmation. Root is still temporary. Do not reboot before installation.

**Do not use Magisk's generic Direct Install or automatic target selection for this build.** The measured init_boot partitions were blank; the tested ramdisk is in **boot_b**. The installer checks that specific target.

### 5. Install root to internal boot_b

**This writes internal flash and can brick the device. Removing the thumb drive cannot undo a failed internal write.**

    python3 onn.py install-root --accept-risk

The installer checks temporary root, device binding, firmware, slot, stock partition hash, and patched image. It saves a fresh boot_b backup, installs official Magisk environment files, writes boot_b once, and verifies readback. It also checks boot_a, vbmeta_b, and vendor_boot_b remain unchanged.

This first-install procedure requires an empty Magisk environment directory, as on our tested unit. Existing environment files, an unfamiliar image, or an earlier attempt cause it to stop for review.

The write script attempts a verified stock restore if writing fails while its shell still works. **Power loss or device failure can prevent restoration. No unbrick method is guaranteed.** It never automatically reboots after flashing.

Continue only after "boot_b written and read back correctly." On an unverified write, keep the box powered on, preserve output and work/, and read recovery instructions.

### 6. Verify permanent root without the thumb drive

Physically remove the thumb drive, then:

    python3 onn.py verify-root --reboot --usb-removed

This requests one normal reboot and checks a new boot ID, root identity, absent thumb drive volume and boot marker, original startup, Magisk version/environment, and partition hashes.

If reboot verification times out but Android later returns, verify without requesting another reboot:

    python3 onn.py verify-root

Success says **Permanent root verified**. The underlying root command is:

    tools/linux/adb -s YOUR_ONN_IP:5555 shell '/debug_ramdisk/su -c id'

The tested shell's PATH omits /debug_ramdisk, so plain su may fail. "Permanent" means root persisted through the verified normal reboot; updates, resets, or later modifications may change it. Keep the bootloader unlocked with a modified image installed.

### 7. Optional: disable automatic firmware updates

The guided script offers this choice at the end. To apply it manually after verifying permanent root:

    python3 onn.py disable-updates --apply

This turns off automatic firmware updates, disables the firmware updater components, and stops the update engine only after confirming it is idle. A Magisk module reapplies the controls after boot. Play Store app update settings stay unchanged. Firmware security fixes are paused too.

The script saves the previous settings in the run's `updates/` folder and checks the result. It refuses to pause an active update or one awaiting reboot. If an attempt is interrupted, the guide checks its result without repeating the change or overwriting the backup.

To check the controls on the Onn 4K Pro:

    python3 onn.py updates-status

To restore the previous update settings:

    python3 onn.py restore-updates --apply

Keep the saved `work/` folder for restoration. Removing the module in Magisk alone does not restore the package and Android settings it changed.

Firmware updates can replace the rooted boot image; [Magisk recommends disabling automatic system updates](https://topjohnwu.github.io/Magisk/ota.html). This option helps preserve root but does not guarantee that root or the unlocked bootloader can never change. Automatic relocking by an Onn update has not been demonstrated. The boot script and portable commands are checked offline; their behavior across reboot has not yet been validated on hardware.

## Reference

- [Recovery](docs/RECOVERY.md)
- [How it works](docs/HOW_IT_WORKS.md)
- [Verified results and limits](docs/RESULTS.md)
- [Build and offline tests](docs/BUILD.md)
- [Third-party files and provenance](THIRD_PARTY.md)
- [Exact firmware profile](firmware/tested-profile.json)
