"""Read-only discovery for the Linux guide. No reboot, formatting, or flashing."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess

from onnlib import check_properties, require, target_value, usb_value


def readable(value):
    """Device names and disk labels must not inject terminal controls."""
    return ''.join(c if c.isprintable() else ' ' for c in str(value or ''))[:200]


def command(argv, timeout=12):
    result = subprocess.run([str(x) for x in argv], capture_output=True, text=True,
                            errors='replace', timeout=timeout)
    require(result.returncode == 0, readable(result.stderr or result.stdout))
    return result.stdout


def adb_devices(text):
    devices = {}
    for line in text.splitlines():
        words = line.split()
        if len(words) < 2:
            continue
        try:
            target = target_value(words[0])
        except (RuntimeError, ValueError):
            continue  # USB serials/emulators are not the tested network transport.
        devices[target] = words[1]
    return devices


def parse_properties(text):
    return dict(re.findall(r'^\[([^]\n]+)\]: \[([^\n]*)\]$', text, re.MULTILINE))


def device_identity(properties):
    serial = properties.get('ro.serialno') or properties.get('ro.boot.serialno', '')
    require(serial and serial.lower() not in ('unknown', 'null', '0123456789abcdef'),
            'A stable hardware serial is unavailable; cannot bind this guided run safely.')
    return hashlib.sha256(serial.encode()).hexdigest()


def inspect_box(adb, target, state='device'):
    result = {'target': target_value(target), 'eligible': False, 'state': state,
              'model': 'Unidentified ADB device', 'reason': ''}
    if state != 'device':
        result['reason'] = ('Accept the debugging authorization on the Onn 4K Pro, then refresh.'
                            if state == 'unauthorized' else 'ADB is offline; refresh after Android starts.')
        return result
    try:
        props = parse_properties(command([adb, '-s', target, 'shell', 'getprop']))
        result['properties'] = props
        result['model'] = readable(props.get('ro.product.model', 'Unknown model'))
        check_properties(props)
        result['identity'] = device_identity(props)
        result['eligible'] = True
        result['reason'] = 'Exact tested firmware; ' + props.get('ro.boot.vbmeta.device_state', 'unknown lock state')
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        result['reason'] = readable(error)
    return result


def networks_from_addresses(interfaces):
    """Bound discovery to up to four active LAN /24s, never a whole /8 or VPN."""
    networks, own_addresses = set(), set()
    for interface in interfaces:
        name, flags = interface.get('ifname', ''), interface.get('flags', [])
        if ('UP' not in flags or 'LOWER_UP' not in flags or 'POINTOPOINT' in flags
                or name.startswith(('lo', 'docker', 'veth', 'virbr', 'br-', 'tun', 'tap', 'wg', 'tailscale'))):
            continue
        for address in interface.get('addr_info', []):
            if address.get('family') != 'inet' or address.get('scope') != 'global':
                continue
            ip = ipaddress.IPv4Address(address['local'])
            if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                continue
            own_addresses.add(str(ip))
            prefix = max(24, int(address['prefixlen']))
            networks.add(ipaddress.IPv4Network((str(ip), prefix), strict=False))
    return sorted(networks, key=str)[:4], own_addresses


def open_adb_port(address):
    try:
        with socket.create_connection((address, 5555), timeout=0.3):
            return address + ':5555'
    except OSError:
        return None


def discover_boxes(adb, scan=False, emit=print):
    before = adb_devices(command([adb, 'devices', '-l']))
    if scan:
        try:
            interfaces = json.loads(command(['ip', '-j', '-4', 'addr', 'show', 'scope', 'global']))
            networks, own = networks_from_addresses(interfaces)
            if networks:
                emit('Searching TCP port 5555 on ' + ', '.join(map(str, networks)) + ' ...')
                addresses = [str(ip) for network in networks for ip in network.hosts()
                             if str(ip) not in own and str(ip) + ':5555' not in before]
                with ThreadPoolExecutor(max_workers=32) as pool:
                    found = [target for target in pool.map(open_adb_port, addresses) if target]
                # Only open ADB ports are contacted. No pairing, authorization,
                # package installation, or device mutation is attempted here.
                with ThreadPoolExecutor(max_workers=8) as pool:
                    def connect(target):
                        try:
                            command([adb, 'connect', target], timeout=5)
                        except (OSError, RuntimeError, subprocess.SubprocessError):
                            pass
                    list(pool.map(connect, found))
            else:
                emit('No active IPv4 LAN found. Connect to the same network as your Onn 4K Pro or use the address option.')
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            emit('LAN discovery unavailable: ' + readable(error))
    current = adb_devices(command([adb, 'devices', '-l']))
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda item: inspect_box(adb, *item), sorted(current.items())))


def mount_objects(text, kind):
    pattern = r'^\s*' + kind + r'\{([^}\n]+)\}:\s*\n(.*?)(?=^\s*(?:DiskInfo|VolumeInfo)\{|^\S|\Z)'
    objects = {}
    for match in re.finditer(pattern, text, re.MULTILINE | re.DOTALL):
        fields = dict((key, value.strip()) for key, value in re.findall(
            r'(\w+)=([^=]*?)(?=\s+\w+=|\Z)', match.group(2), re.DOTALL))
        objects[match.group(1)] = fields
    return objects


def tv_volumes(text):
    disks, volumes = mount_objects(text, 'DiskInfo'), mount_objects(text, 'VolumeInfo')
    usb_disk_count = sum('USB' in disk.get('flags', '').split('|') for disk in disks.values())
    found = []
    for name, volume in volumes.items():
        if volume.get('type') != 'PUBLIC':
            continue
        disk = disks.get(volume.get('diskId'), {})
        reason = ''
        uuid = volume.get('fsUuid', '')
        try:
            uuid = usb_value(uuid)
        except RuntimeError:
            reason = 'Not a portable FAT volume.'
        path = volume.get('path', '')
        if not reason and path != '/storage/' + uuid:
            reason = 'Unexpected Android mount path.'
        if 'USB' not in disk.get('flags', '').split('|'):
            reason = 'Cannot confirm that this is a USB disk.'
        if volume.get('state') != 'MOUNTED':
            reason = 'Not mounted read/write on the Onn 4K Pro.'
        if volume.get('fsType') not in ('vfat', 'fat', 'msdos'):
            reason = 'FAT32 is required; this filesystem is unsupported.'
        part = re.fullmatch(r'public:(\d+),(\d+)', name)
        parent = re.fullmatch(r'disk:(\d+),(\d+)', volume.get('diskId', ''))
        if not part or not parent or part[1] != parent[1] or int(part[2]) != int(parent[2]) + 1:
            reason = 'Only the USB disk\'s first partition is supported.'
        found.append({'uuid': uuid, 'path': path, 'label': readable(volume.get('fsLabel', '')),
                      'disk_id': volume.get('diskId'), 'usb_disk_count': usb_disk_count,
                      'size': int(disk.get('size', '0')) if disk.get('size', '').isdigit() else 0,
                      'filesystem': volume.get('fsType', 'unknown'), 'eligible': not reason,
                      'reason': reason or 'Portable FAT volume; confirm it was formatted FAT32.'})
    return found


def parse_df(text):
    for line in reversed(text.splitlines()):
        words = line.split()
        if len(words) >= 6 and all(x.isdecimal() for x in words[1:4]):
            return {'size': int(words[1]) * 1024, 'free': int(words[3]) * 1024}
    raise RuntimeError('Could not read storage capacity; no disk will be selected.')


def discover_tv_drives(adb, target):
    target = target_value(target)
    drives = tv_volumes(command([adb, '-s', target, 'shell', 'dumpsys mount']))
    for drive in drives:
        if drive['eligible']:
            try:
                usage = parse_df(command([adb, '-s', target, 'shell',
                                          'df -k /storage/' + usb_value(drive['uuid'])]))
                drive.update(usage)
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                drive.update(eligible=False, reason=readable(error))
    return drives


def host_volumes(data, expected_uuid):
    expected_uuid = usb_value(expected_uuid)
    found = []

    def visit(node, is_usb=False):
        is_usb = is_usb or node.get('tran') == 'usb'
        if is_usb and node.get('type') in ('disk', 'part'):
            mounts = node.get('mountpoints') or []
            uuid = (node.get('uuid') or '').upper()
            reason = ''
            if uuid != expected_uuid:
                reason = 'Different volume; use the same drive selected on the Onn 4K Pro.'
            elif node.get('fstype') != 'vfat' or node.get('fsver') != 'FAT32':
                reason = 'The selected volume is not FAT32.'
            paths = [str(x) for x in mounts if x and Path(x).is_absolute()]
            if not paths:
                reason = 'Not mounted. Open this thumb drive in your file manager, then refresh.'
            # Show physical USB disks without a mount too, so an unmounted drive
            # does not misleadingly disappear from the list.
            if node.get('type') == 'part' or not node.get('children'):
                for mount in paths or ['']:
                    found.append({'uuid': uuid, 'path': mount, 'label': readable(node.get('label')),
                                  'device': readable(node.get('path')), 'size': int(node.get('size') or 0),
                                  'filesystem': node.get('fstype') or 'unknown',
                                  'eligible': not reason, 'reason': reason or 'Matches the thumb drive volume selected on the Onn 4K Pro.'})
        for child in node.get('children', []):
            visit(child, is_usb)

    for node in data.get('blockdevices', []):
        visit(node)
    return found


def discover_host_drives(expected_uuid):
    data = json.loads(command(['lsblk', '--json', '--bytes', '--output',
                              'NAME,PATH,TYPE,TRAN,SIZE,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS']))
    return host_volumes(data, expected_uuid)
