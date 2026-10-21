# Building and offline validation

**These artifacts target the earlier onn. 4K Pro (jarvis / SNA), not the new 2026 model. Rebuilding them does not add support for the 2026 model or other firmware.**

The prebuilt artifacts are included for normal use. Rebuilding is optional developer work and does not authorize hardware tests. All commands here operate on local files.

The native payloads and prebuilt APKs come from the successful single-unit experiment. Portable wrappers are new packaging code and have no end-to-end hardware validation.

## Offline checks

Use Python 3.10+ and a virtual environment:

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python tools/validate-package.py

The validator checks package hashes, version/input/receipt guards, modeled native execution and TEE failure cases, result collectors, boot-flow ordering/fallbacks, native rebuild reproducibility, and local setup isolation. It also checks the interactive guide's discovery, drive selection, device binding, interrupted-action handling, and read-only progress display with simulated responses. It never invokes the ADB binary or contacts a box. Models do not establish real hardware acceptance.

Unlock handoff tests check that no device calls occur after the reboot request, that failures before reboot still perform cleanup, and that the guide waits for setup confirmation before reconnecting, including after quitting and resuming.

Firmware update tests cover explicit opt-in, skipping without device contact, preserving and restoring previous settings, active-update refusal, module integrity, and interrupted attempts without replay. The actual boot shell scripts also run against stub Android commands to check component handling and failure behavior. These checks do not establish persistence across a real hardware reboot.

## Native payloads

    .venv/bin/python tools/build-native.py read
    .venv/bin/python tools/build-native.py unlock

Keystone assembles the included source and the builder constructs the legacy image header/CRC. Each output must be byte-for-byte identical to its tested payload. Outputs go to ignored work/native-build/.

## Diagnostic APKs

Use a JDK with javac/keytool, Android SDK platform 34 android.jar, and build-tools 34.0.0. Supply paths to your installation:

    python3 tools/build-apk.py read --android-jar /YOUR_SDK/platforms/android-34/android.jar --build-tools /YOUR_SDK/build-tools/34.0.0

Repeat with unlock and root. Each command creates a new ignored work/apk-build/<kind>/ directory. It compiles Java, creates DEX, packages, aligns, and signs using a newly generated local development key.

DEX is compared with the tested APK. Signatures differ because the original signing keys are not distributed. The builder never installs or replaces packaged APKs. A different key cannot update an already installed package with the old signature; changing signing/install state is outside the normal guide. Keep generated private keys local.

## Integrity and maintainer changes

MANIFEST.json records SHA-256 for curated files; ordinary user commands verify it before proceeding. Local configuration is copied into work/ and receives its own checksums. This detects accidental changes; it is not an independent publisher signature.

Maintainers modifying curated files must inspect the diff, regenerate the manifest with tools/make-manifest.py, and rerun offline validation. Never regenerate checksums merely to bypass a failed firmware or payload guard.

The local report goes under work/. A sanitized summary can be saved in evidence/ after review. Raw USB environment captures, personal addresses, device IDs and original full RAM dumps must remain outside the repository.
