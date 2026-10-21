#!/usr/bin/env python3
"""Offline package validation; no ADB or device calls."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onnlib import digest, now, PROFILE, read, require, save, verify_files

count = verify_files()
for name, key in [('tools/linux/adb', 'adb_sha256'), ('assets/Magisk-v30.7.apk', 'magisk_apk_sha256'),
                  ('firmware/stock-boot-15051976.img.gz', 'stock_boot_gzip_sha256')]:
    require(digest(ROOT / name) == PROFILE[key], 'Wrong binary: ' + name)
manifest = read(ROOT / 'MANIFEST.json')['files']
for name in manifest:
    relative = Path(name)
    require(not {'work', '.venv', '__pycache__', '.git'}.intersection(relative.parts), 'Private/generated path packaged')
    require(relative.suffix not in {'.pem', '.jks', '.keystore'}, 'Signing material packaged')
    require((ROOT / relative).stat().st_size < 50 * 1024 * 1024, 'Unexpected large file')
    if relative.suffix in {'.py', '.json', '.md', '.java', '.S', '.in', '.sh'}:
        data = (ROOT / relative).read_text()
        require(not re.search(r'/(?:home|Users)/[A-Za-z0-9_.-]+', data), 'Personal host path in ' + name)
        require(not re.search(r'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b', data),
                'Private network address in ' + name)
        require('BEGIN ' + 'PRIVATE KEY' not in data, 'Private key in ' + name)
    if relative.suffix == '.md':
        for link in re.findall(r'\]\(([^)]+)\)', (ROOT / relative).read_text()):
            if not link.startswith(('https://', 'http://', '#')):
                require(((ROOT / relative).parent / link.split('#')[0]).exists(), 'Broken documentation link: ' + link)

suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
stream = io.StringIO()
with redirect_stdout(stream):
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
if not result.wasSuccessful():
    print(stream.getvalue())
    raise SystemExit(1)
report = {'time': now(), 'packaged_files_verified': count, 'unit_tests_passed': result.testsRun,
          'device_contacted': False, 'hardware_validation_of_wrapper': False, 'models': {}}
for kind in ['read', 'unlock', 'root']:
    with tempfile.TemporaryDirectory(prefix='onn-offline-') as directory:
        kit = Path(directory) / kind
        shutil.copytree(ROOT / 'kits' / kind, kit, ignore=shutil.ignore_patterns('__pycache__'))
        script = 'check_boot_flow.py' if kind == 'root' else 'validate_offline.py'
        completed = subprocess.run([sys.executable, str(kit / script)], capture_output=True, text=True, timeout=40)
        require(completed.returncode == 0, kind + ': ' + completed.stdout + completed.stderr)
        report['models'][kind] = json.loads(completed.stdout)
        print(kind, completed.stdout.strip())
for kind in ['read', 'unlock']:
    result = subprocess.run([sys.executable, str(ROOT / 'tools/build-native.py'), kind],
                            capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, result.stdout + result.stderr)
    print(result.stdout.strip())
report['native_rebuilds_byte_identical'] = True
report['all_passed'] = True
report['limitations'] = 'Offline models and mocked device responses only. The new wrapper has no end-to-end hardware validation.'
save(ROOT / 'work/offline-validation.json', report)
print(json.dumps(report, indent=2))
