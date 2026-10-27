"""Match captured full VU1 image identities to generated table declarations.

Table availability is not a measurement of calls executed by that table.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', type=Path)
    parser.add_argument('--table', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve existing coverage evidence')
    table_data = args.table.read_bytes()
    known = set(re.findall(r'case 0x([0-9a-f]{16})ull: return VU1CompiledPrograms::t_', table_data.decode()))
    images = []
    for path in sorted(args.captures.glob('vu1_*.bin')):
        data = path.read_bytes()
        if len(data) != 16384:
            raise ValueError('Expected full 16 KiB VU1 image')
        value = 0xCBF29CE484222325
        for byte in data:
            value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        identity = f'{value:016x}'
        if path.name != f'vu1_{identity}.bin':
            raise ValueError('Capture name and bytes disagree')
        images.append({'path': str(path.resolve()), 'fnv1a64': identity,
                       'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                       'generated_table_available': identity in known})
    if not images:
        raise ValueError('No captured microcode images')
    result = {'scope': __doc__.strip(), 'table': str(args.table.resolve()),
              'table_sha256': hashlib.sha256(table_data).hexdigest(), 'images': images,
              'captured_images': len(images), 'missing_tables': sum(not row['generated_table_available'] for row in images),
              'limits': ['No call counts, budgets or table-selection events are recorded by this census.',
                         'Only this capture directory is covered; later campaign images remain unknown.']}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps({'captured_images': result['captured_images'], 'missing_tables': result['missing_tables']}))


if __name__ == '__main__':
    main()
