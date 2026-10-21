# Third-party files and provenance

Original notices are preserved. Inclusion does not transfer ownership or grant additional rights to OEM firmware. Original guide/wrapper code has no separate license grant in this private draft.

## Magisk 30.7

assets/Magisk-v30.7.apk is the unmodified official APK.

- [Official release and binary](https://github.com/topjohnwu/Magisk/releases/tag/v30.7)
- [Corresponding source, build scripts and submodules](https://github.com/topjohnwu/Magisk/tree/v30.7)
- [Source archive](https://github.com/topjohnwu/Magisk/archive/refs/tags/v30.7.tar.gz); obtain the tag and its submodules for builds.
- [Included GNU GPL v3 license](licenses/Magisk-GPL-3.0.txt)

The upstream source location accompanies the binary reference here. Official environment files are extracted from the APK during installation. Its ChromeOS assets include an upstream development signing key, not a device or manufacturer secret.

## ADB

tools/linux/adb is Google's Linux x86_64 platform-tools ADB 37.0.1-15733141. Its [NOTICE](licenses/ADB-NOTICE.txt) is included.

- [Official platform-tools](https://developer.android.com/tools/releases/platform-tools)
- [ADB source](https://android.googlesource.com/platform/packages/modules/adb/)

## Stock boot and emulator fixture

firmware/stock-boot-15051976.img.gz expands to the original 100,663,296-byte stock boot image. Its full hash matched live boot_b and the image extracted from the verified stock OTA. The complete OTA is not included:

[Official OTA package](https://android.googleapis.com/packages/ota-api/package/c8dfd1aaa56643f4c2f86adb72045884a978e31a.zip)

The [firmware profile](firmware/tested-profile.json) records its SHA-256. MANIFEST.json hashes packaged files. Providing that OTA reference does not establish a working rescue method.

Sparse emulator fixtures include only stock instruction ranges needed for the guarded getter/reader and prefix checks. They contain no full bootloader RAM capture or device credentials.

## Optional development dependencies

Capstone, Unicorn, and Keystone are used only for offline validation/building and are not vendored. Tested versions are pinned in requirements-dev.txt. Normal use requires Python's standard library and included runtime artifacts.

## Device identification photo

`assets/images/onn-4k-pro-2024.png` is an unmodified product photo from [Walmart's earlier Onn 4K Pro listing (item 5193222892)](https://www.walmart.com/ip/5193222892), retrieved October 21, 2026. It shows the supported model for identification; the product image and trademarks belong to their respective owners.
