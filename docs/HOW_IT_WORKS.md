# How the tested method works

This describes the **earlier onn. 4K Pro (jarvis / SNA), firmware URO4.260304.011.B1 / 15051976 only**. The new 2026 hardware model is unsupported and untested. Fixed addresses, code prefixes, and memory layout make it specific to the tested bootloader. It can brick a device; guards do not eliminate the risk.

## AVB unlock

The diagnostic APK reads/changes ubootenv.var.storeboot through the vendor SystemControl interface. Temporary startup consumes a one-use FAT USB gate before loading an unsigned legacy native payload. The payload runs in the measured AArch64 EL2 context, guarded by register state and stock code prefixes.

The read payload calls the unmodified stock secure-state getter. The unlock payload requires state 1, opens AVB trusted service UUID 023f8f1a-292a-432b-8fc4-de8471358067, and issues command 3 with one VALUE_INPUT parameter (attribute 1, values 0/0/0). It then reads state again. Our capture recorded exactly one write, transport and TA success, and state 0.

Normal startup "run storeboot_base;" is restored and reread through a fresh vendor service. Android required a factory reset on our box; unlocked/orange state persisted afterward and through another ordinary reboot.

No manufacturer private key was recovered or signature forged. This proves a persistent Android AVB lock-state change, not disablement of earlier hardware secure boot or support for arbitrary first-stage bootloader replacement.

## Temporary root

Official Magisk 30.7 patches the exact stock image on the target. The kernel remains unchanged. A trimmed 14,434,304-byte image is loaded at 0x3000000, ending at 0x3dc4000. The full 96 MiB partition image would exceed that tested RAM range.

The fixed USB candidate consumes its gate, initializes vendor boot data using stock imgread, checks address/code/init_boot state/header, replaces the in-memory generic boot image, and invokes normal bootm. A saved header and Android marker identify this path; separate uid=0(root) proof establishes root.

## Permanent root

With temporary root working, the installer backs up live stock boot_b, checks its hash, stages official Magisk files, and verifies the patched image. It writes boot_b with full readback and compares boot_a, vbmeta_b, and vendor_boot_b before/after.

The measured upgraded device has its generic ramdisk in boot_b despite blank init_boot partitions. Magisk's automatic selection can choose init_boot on this Android 14 kernel. The guide uses the measured boot_b target; see [versioned Magisk source](https://github.com/topjohnwu/Magisk/blob/v30.7/scripts/util_functions.sh) and our recorded results.

Final proof requires normal startup, a new boot ID, physically removed thumb drive, no temporary marker, the expected partition hash, Magisk version/environment, and root identity.

Emulation models trusted-service replies and selected stock behavior. It checks guard logic; it does not establish live TEE acceptance or safety on another device.
