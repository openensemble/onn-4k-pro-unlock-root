# Measured results and limits

One **earlier-generation onn. Streaming Device 4K Pro (jarvis / SNA)** was tested on October 21, 2026: **URO4.260304.011.B1 / 15051976**, Android TV 14, patch **March 1, 2026**, bootloader **01.01.260304.175641**, slot **_b**.

**The new 2026 onn. 4K Pro hardware model was not tested and is unsupported by this guide.** The software patch date and test date do not identify the hardware generation.

| Stage | Recorded result |
| --- | --- |
| Read | Stock getter succeeded, locked state 1 |
| Unlock | One accepted request, readback state 0 |
| Recovery | Android corruption screen; factory reset required |
| Persistence | Unlocked/orange after reset and later normal reboot |
| Temporary root | USB patched boot and successful root identity |
| Installation | Full boot_b readback matched patched image |
| Other partitions | boot_a, vbmeta_b, vendor_boot_b unchanged |
| Permanent root | New normal boot, thumb drive physically removed, marker absent, uid=0(root), Magisk environment verified |
| Reset during root install | None; new setup retained |

Selected original evidence:

- [Locked state](../evidence/locked-state-test23.json)
- [Accepted unlock](../evidence/unlock-test24.json)
- [Unlock after reset](../evidence/unlock-after-reset.json)
- [Root after reboot](../evidence/root-after-reboot.json)

Device addresses, runtime boot IDs and host paths are omitted. Earlier records correctly say later outcomes were not yet proved; subsequent records supply that proof.

Stock boot SHA-256:

    5c5a874dd2e3e5b2ad87903a3d53a6f8b3ebcebe2ad64a28fd837d1a07ceaad8

Observed patched boot SHA-256:

    2447a78a0580a804b3997b3920e9198a437aedf7294ec2907952d2ef751d36a3

The patched image is generated on each target, not shared. The wrapper requires the exact tested output; whether another unit reproduces it is unvalidated.

## November 6, 2026: data-preserving upgrade on the same one device

The already-unlocked, rooted box was updated from **15051976 / slot B** to
**16202347 / slot A**, Android 14 / **September 1, 2026** patch. The native signed
OTA completed, its new boot was patched on the target with Magisk 30.7, and
full readback passed before one ordinary reboot. The new firmware booted with
root, unlocked/orange state, the same Android installation, all 18 user-installed
apps, the same home launcher and retained launcher settings. No factory reset,
relock or unlock writer was used. Debugging needed approval again.

Android marked slot A successful and completed snapshot merge. The prior OTA
pause was restored. See [sanitized update evidence](../evidence/update-16202347.json)
and the [exact new build profile](../firmware/build-16202347.json).

**Fresh unlocking and first-time root on 16202347 were NOT tested.** Its separate experimental option
can erase data or permanently brick a device. The owner is solely responsible
for choosing to take the risk and all resulting loss or damage. Static equality
of inspected bootloader/security components is motivation for the experiment,
not proof of safety or successful unlocking/root. The root option is offered only
after verified experimental unlock, with its own risk confirmation. The project
authors do not take responsibility for resulting damage or data loss.

## Limits

- No second physical device was tested. The later slot A result is an upgrade on the same already-unlocked box; neither a fresh slot A nor slot B unlock on 16202347 was tested.
- The original portable guide, new update wrapper and experimental helpers have offline checks, not an end-to-end hardware run of the packaged workflows.
- No independent post-cold-boot getter capture exists. Subsequent Android state and successful modified boot support persistence.
- Hardware secure-boot disablement and arbitrary bootloader replacement are not proved.
- Bricked-device rescue, fastboot flashing, and signed-OTA recovery are untested.
- Only the specific 15051976/B → 16202347/A upgrade was measured. Later updates, reset after permanent root, other Magisk versions and long-term reliability remain untested.

**This can erase data or brick a device. One-unit success does not guarantee repeatability or recovery.** The offline report describes software checks performed during packaging.
