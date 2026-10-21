#!/usr/bin/env python3
"""Maintainer-only: seal curated files after review and offline validation."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = {}
for path in sorted(root.rglob('*')):
    relative = path.relative_to(root)
    if not path.is_file() or any(p in ('.git', 'work', '.venv', '__pycache__') for p in relative.parts):
        continue
    if relative.as_posix() == 'MANIFEST.json' or path.suffix == '.pyc':
        continue
    assert path.stat().st_size < 50 * 1024 * 1024, str(relative)
    assert path.suffix not in ('.pem', '.jks', '.keystore'), str(relative)
    files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
(root / 'MANIFEST.json').write_text(json.dumps({'algorithm': 'sha256', 'files': files}, indent=2) + '\n')
print('Sealed', len(files), 'files; no device contacted')
