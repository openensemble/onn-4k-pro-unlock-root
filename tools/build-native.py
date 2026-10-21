#!/usr/bin/env python3
"""Rebuild fixed native payloads locally; never contacts a device."""
import argparse
import hashlib
from pathlib import Path
import struct
import zlib
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('kind', choices=['read', 'unlock'])
args = parser.parse_args()
kit = ROOT / 'kits' / args.kind
number = 23 if args.kind == 'read' else 24
code_size, result_size = (0x600, 0x200) if number == 23 else (0x1000, 0x400)
source = next(kit.glob('*.S')).read_text()
code, _ = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN).asm(source)
assert len(code) == code_size
payload = bytes(code) + b'ZZZZ' + bytes(result_size - 4)
name = b'ONN secure state read 23' if number == 23 else b'ONN one use state change 24'
fields = [0x27051956, 0, 0, len(payload), 0x3000040, 0x3000040,
          zlib.crc32(payload), 17, 22, 1, 0, name.ljust(32, b'\0')]
fields[1] = zlib.crc32(struct.pack('>7I4B32s', *fields))
image = struct.pack('>7I4B32s', *fields) + payload
expected = kit / f'ONNPRO{number}.IMG'
assert image == expected.read_bytes(), 'Rebuilt payload differs from the tested artifact'
output = ROOT / 'work' / 'native-build' / expected.name
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(image)
print(args.kind, 'exact payload reproduced:', hashlib.sha256(image).hexdigest())
