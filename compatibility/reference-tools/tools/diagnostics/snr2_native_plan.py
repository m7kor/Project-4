"""Prepare explicit SNR2 native body ranges; never guess code from symbol types."""
import argparse
import json
from pathlib import Path
import struct

from tools.diagnostics.snr2_inventory import parse_snr2
from tools.diagnostics.snr2_relocations import compact_relocations


def build_plan(data, bodies, identifier):
    metadata = parse_snr2(data)
    if not identifier or len(identifier) > 80 or not identifier[0].isascii() or not identifier[0].isalpha() or any(
            not c.isascii() or not (c.isalnum() or c == '_') for c in identifier):
        raise ValueError('Invalid native module identifier')
    ranges = sorted(bodies)
    if not ranges:
        raise ValueError('At least one reviewed body range is required')
    previous_end = 0
    for start, end in ranges:
        if start < previous_end or start < 60 or start % 4 or end % 4 or end <= start or end > len(data):
            raise ValueError('Invalid or overlapping body ranges')
        # Reject a missing delay slot at the end of the declared range.
        word = struct.unpack_from('<I', data, end - 4)[0]
        op, fn = word >> 26, word & 63
        if op in (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23) or op == 0 and fn in (8, 9) or op in (16, 17, 18) and (word >> 21 & 31) == 8:
            raise ValueError('Body range omits a branch delay slot')
        previous_end = end
    sites = {}
    for record in compact_relocations(data) + metadata['relocations']:
        at, kind = record['offset'], record['type']
        if not any(start <= at < end for start, end in ranges):
            continue
        if at % 4 or kind not in (4, 5, 6):
            raise ValueError('Unsupported relocation inside compiled instructions')
        if at in sites:
            raise ValueError('Repeated relocation of one compiled instruction needs explicit analysis')
        word = struct.unpack_from('<I', data, at)[0]
        op = word >> 26
        supported_i = 8 <= op <= 15 or 24 <= op <= 27 or 30 <= op <= 46 or op in (48, 49, 54, 55, 56, 57, 62, 63)
        if kind == 4 and op not in (2, 3) or kind == 5 and op != 15 or kind == 6 and not supported_i:
            raise ValueError('Relocation does not match instruction opcode')
        sites[at] = kind
    return {'schema': 1, 'identifier': identifier, 'identity': metadata['sha256'],
            'bytes': len(data), 'bodies': [{'start': a, 'end': b} for a, b in ranges],
            'instruction_relocations': [{'offset': at, 'type': kind} for at, kind in sorted(sites.items())],
            'constructor_offset': metadata['constructor_offset'],
            'scope': 'Explicit native codegen input only. Code/data boundaries are caller reviewed; imports, full-image binding and guest loader integration remain required.'}


def write_plan(image, bodies, identifier, output):
    if output.resolve() == image.resolve():
        raise ValueError('Cannot replace original module')
    plan = build_plan(image.read_bytes(), bodies, identifier)
    # TOML basic strings use the same escaping as JSON for these ASCII values.
    lines = ['schema = 1', f'identifier = {json.dumps(identifier)}',
             f'identity = {json.dumps(plan["identity"])}',
             f'image = {json.dumps(image.resolve().as_posix())}']
    if not plan['instruction_relocations']:
        lines.append('instruction_relocations = []')
    for body in plan['bodies']:
        lines += ['[[bodies]]', f'start = {body["start"]}', f'end = {body["end"]}', 'entries = []']
    for site in plan['instruction_relocations']:
        lines += ['[[instruction_relocations]]', f'offset = {site["offset"]}', f'type = {site["type"]}']
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', type=Path)
    parser.add_argument('--body', action='append', required=True, help='reviewed start:end offsets, e.g. 0x33870:0x33920')
    parser.add_argument('--identifier', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ranges = [tuple(int(v, 0) for v in item.split(':')) for item in args.body]
    if any(len(item) != 2 for item in ranges):
        parser.error('Each body needs start:end')
    plan = write_plan(args.module, ranges, args.identifier, args.out)
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()
