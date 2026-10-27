"""Inventory complete VU1 call inputs; does not prove rendered model identity."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def inventory(directory):
    rows = []
    groups = {}
    for path in sorted(directory.glob('vu1snap_*.bin')):
        payload = path.read_bytes()
        if len(payload) < 40:
            raise ValueError(f'Truncated header: {path}')
        magic, version, pc, top, itop, state_size, code_size, data_size, vsync = struct.unpack_from('<8IQ', payload)
        if (magic != 0x53315556 or version != 1 or code_size != 16384 or data_size != 16384
                or not 0 < state_size <= 65536 or pc >= 16384 or pc % 8
                or len(payload) != 40 + state_size + code_size + data_size):
            raise ValueError(f'Invalid complete snapshot: {path}')
        code = payload[40 + state_size:40 + state_size + code_size]
        identity = hashlib.sha256(code).hexdigest()
        group = groups.setdefault(identity, {'count': 0, 'first_ee_vsync': vsync,
                                            'last_ee_vsync': vsync, 'start_pcs': Counter()})
        group['count'] += 1
        group['first_ee_vsync'] = min(vsync, group['first_ee_vsync'])
        group['last_ee_vsync'] = max(vsync, group['last_ee_vsync'])
        group['start_pcs'][str(pc)] += 1
        rows.append({'file': path.name, 'sha256': hashlib.sha256(payload).hexdigest(),
                     'code_sha256': identity, 'ee_vsync': vsync, 'start_pc': pc})
    if not rows:
        raise ValueError('No complete call snapshots')
    return {'scope': __doc__, 'directory': str(directory.resolve()), 'snapshots': len(rows),
            'code_images': groups, 'files': rows,
            'limits': ['Pre-call inputs only; compiled-path selection is checked by replay.',
                       'Snapshot cap and start threshold exclude other calls and campaign scenes.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.directory)
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({k: report[k] for k in ('snapshots', 'code_images')}))


if __name__ == '__main__':
    main()
