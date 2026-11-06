# Update to reviewed firmware 16202347 while preserving root and setup

The underlying **15051976 slot B → 16202347 slot A** procedure was **tested and
verified on ONE 2024 onn. 4K Pro (jarvis / SNA)** on November 6, 2026. Existing
unlock, Magisk 30.7 root, apps and setup survived. No relock, unlock writer,
factory reset or userdata wipe was performed. Android completed its snapshot
merge and the previous firmware OTA pause was restored.

The newly packaged updater has offline tests; it has **not** been run end to end
on hardware. One-device success is not a guarantee. Firmware flashing can cause
data loss, boot loops or a **permanent brick**. Backups do not guarantee recovery.
Read the [evidence](../evidence/update-16202347.json) and
[recovery conditions](RECOVERY.md) before proceeding.

This does **not** test unlocking a locked device on 16202347. That is a separate
[experimental, untested workflow](EXPERIMENTAL_UNLOCK.md).

## Exact scope

- Original **2024 jarvis / SNA** hardware only. The 2026 model is unsupported.
- Starting firmware: `onn/jarvis/SNA:14/URO4.260304.011.B1/15051976:user/release-keys`.
- Already unlocked/orange, normal startup, active slot **B**, and the original
  measured Magisk **30.7 (30700)** boot image. Root permission for Shell is required.
- Target firmware: `onn/jarvis/SNA:14/URO4.260304.092/16202347:user/release-keys`,
  Android 14, September 1, 2026 security patch, native updater selects slot **A**.
- Bootloader: `01.01.260304.175641`. Both physical boot partitions remain 96 MiB.
- Linux x86_64, Python 3.10+, authorized network ADB, normal uninterrupted power.
  No thumb drive is needed for the update. Remove any boot-test thumb drive.
- At least **4 GiB free on the box**. The host needs **8 GiB or more**, and enough
  for used device storage plus a 4 GiB margin. Preparation checks actual space.

16202347 is the **newest reviewed build** in this package, not a promise that no
later firmware exists. The exact official OTA, size, SHA-256, payload metadata,
new boot image and expected patch are pinned in the
[build profile](../firmware/build-16202347.json). Unknown builds are rejected.
The complete 899 MB OTA is downloaded from Google's firmware host; it is not
bundled. Its pinned bytes were authenticated during the original inspection.
Android also verifies signed payload applicability before installation.

## Guided update and status messages

Run `python3 onn.py` and choose **2**, or run:

    python3 onn.py update-firmware

The guide separates preparation, installation, reboot and verification. It asks
before flashing and again before the single reboot. It displays:

1. Download totals, boot backup names and live setup-backup transfer totals.
2. New boot preparation and Magisk patching **on your own device**.
3. Firmware installation, verification and finalization progress.
4. Periodic messages during long transfers and updater waits.
5. Reboot/reconnection progress, including a reminder to approve USB debugging.
6. Snapshot merge progress and confirmation that the previous OTA policy returned.

Progress percentages apply to the named phase, not an estimated overall time.
Detailed command output is saved alongside the private backups. Do not run two
device workflows at once. Type `q` at guide prompts to leave; retain `work/` to resume.

## Manual stages

Replace `YOUR_ONN_IP` with the box's current address. Preparation inventories
the device, verifies normal startup through the diagnostic helper, saves boot
and live app/settings/media backups, stages the official OTA, and creates the
new Magisk image. It can install the existing diagnostic helper APK. It does not
flash firmware or reboot:

    python3 onn.py update-firmware --prepare --target YOUR_ONN_IP:5555

To use an already downloaded copy, add `--ota-file /PATH/TO/update.zip`. The full
size and pinned hash must still match. A truncated or different OTA is refused.

Review the preparation output and backup receipt before continuing:

    python3 onn.py update-firmware --apply --accept-risk

This uses native Android `update_engine` with `POWERWASH=0`, then checks the
new physical partition images and selected slot. It writes the target-generated
Magisk image only to **boot_a**, verifies full readback, and verifies boot_b is
unchanged. It never selects `init_boot`, relocks or requests a reset. A failed
boot write attempts a verified restore of the **new firmware's stock boot_a**
while the shell still works. Power/storage failure can prevent restoration.
**It does not reboot automatically.**

Continue only after the new slot and root image are verified:

    python3 onn.py update-firmware --reboot --accept-risk

Approve USB debugging again on the TV if asked; this was necessary in the
single-device test. The command requests one normal reboot and waits for Android.

    python3 onn.py update-firmware --verify

This checks the new firmware, new boot ID, successful slot A, unlock properties,
Magisk root, exact boot image, same Android installation, user apps and selected
home launcher. It finishes/observes Android's snapshot merge before restoring
the **previous** OTA policy. Existing firmware pauses stay paused; originally
enabled controls return to their previous state. Play Store settings are preserved.

The matching new stock boot backup is also retained on the device. No shared
patched boot image is supplied: the tool generates and validates your own.

## Pauses, interruptions and changed addresses

For a local-only status report:

    python3 onn.py update-firmware --status

If the device's address changes:

    python3 onn.py update-firmware --set-target NEW_ONN_IP:5555
    python3 onn.py update-firmware --verify

The address change is local; the next check requires the same physical device
and Android installation. An unauthorized/offline connection is not proof that
the device failed. Approve debugging and wait for startup.

**Do not replay an update or flash after a timeout.** `--verify` can reconcile a
completed OTA or boot write from current hashes and Android's status without
repeating it. It will state the permitted next step. An incomplete preparation,
unknown image, changed boot, or unresolved write stops for review. Preserve the
receipt and logs; do not delete them to force a new attempt. Never reset the box
as a response to an unverified firmware write.

If merge is still running, keep power connected and resume `--verify`. Do not
manually re-enable the OTA-pause module before merge is complete.

Receipts and sensitive live backups are in `work/firmware-updates/<run>/`.
The archive includes private app/account data; do not publish it. It is a live,
non-atomic backup. Runtime sockets can be omitted, but any other backup error or
missing/truncated archive prevents installation. Retain this folder after success.

The rollback index increased in the new firmware. An intact old boot_b does
**not** prove an old-slot downgrade or recovery route. Do not use the original
15051976 root/restore commands on 16202347. When the updater recognizes the
original guide's saved installation, it updates that run's OTA-control receipts
so `updates-status` and `restore-updates --apply` remain usable.
