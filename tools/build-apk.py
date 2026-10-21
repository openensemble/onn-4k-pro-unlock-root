#!/usr/bin/env python3
"""Rebuild a diagnostic APK using an explicitly supplied Android SDK."""
import argparse
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('kind', choices=['read', 'unlock', 'root'])
p.add_argument('--android-jar', type=Path, required=True)
p.add_argument('--build-tools', type=Path, required=True)
args = p.parse_args()
kit = ROOT / 'kits' / args.kind
out = ROOT / 'work' / 'apk-build' / args.kind
out.mkdir(parents=True, exist_ok=False)
(out / 'classes').mkdir()
(out / 'dex').mkdir()
jar, tools = args.android_jar.resolve(), args.build_tools.resolve()
assert jar.is_file()

def run(*command):
    subprocess.run([str(item) for item in command], check=True, cwd=out)

run('javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-classpath', jar,
    '-d', out / 'classes', *sorted((kit / 'src').rglob('*.java')))
run(tools / 'd8', '--lib', jar, '--min-api', '28', '--output', out / 'dex',
    *sorted((out / 'classes').rglob('*.class')))
run(tools / 'aapt2', 'link', '-o', out / 'unsigned.apk', '-I', jar, '--manifest', kit / 'AndroidManifest.xml')
with zipfile.ZipFile(out / 'unsigned.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
    for dex in sorted((out / 'dex').glob('*.dex')):
        archive.write(dex, dex.name)
run(tools / 'zipalign', '-f', '4', out / 'unsigned.apk', out / 'aligned.apk')
run('keytool', '-genkeypair', '-keystore', out / 'diagnostic.jks', '-alias', 'diagnostic',
    '-storepass', 'local-development', '-keypass', 'local-development', '-keyalg', 'RSA',
    '-keysize', '2048', '-validity', '365', '-dname', 'CN=Local Diagnostic Build')
run(tools / 'apksigner', 'sign', '--ks', out / 'diagnostic.jks', '--ks-pass',
    'pass:local-development', '--out', out / 'diagnostic.apk', out / 'aligned.apk')
run(tools / 'apksigner', 'verify', '--verbose', out / 'diagnostic.apk')
# Compare executable source output; signatures differ because the key is new.
with zipfile.ZipFile(out / 'diagnostic.apk') as rebuilt, zipfile.ZipFile(next((kit / 'build').glob('*.apk'))) as tested:
    assert rebuilt.read('classes.dex') == tested.read('classes.dex'), 'DEX differs; review compiler/tool versions and sources'
print('APK built; DEX exactly matches tested artifact. Output:', out / 'diagnostic.apk')
print('New local signing key; APK signatures differ. Nothing was installed.')
