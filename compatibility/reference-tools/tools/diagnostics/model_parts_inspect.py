"""Read bounded model-part links and matrix inputs from one pre-call EE RAM capture.

Offsets are derived from RE4's getPartsPtr/partsWorldCalc. This does not identify
Leon, the head bone, visibility, post-call results or scratchpad. Optional VU0
metadata records pre-call register observations, not a complete device state.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import struct


def inspect_vu0(metadata):
    fields = ('vu0_vf_hex', 'vu0_vi', 'vu0_qpi_hex', 'vu0_acc_hex',
              'vu0_status', 'vu0_mac', 'vu0_clip', 'vu0_tpc', 'fbrst', 'vpu_stat')
    present = [name in metadata for name in fields]
    if not any(present):
        return {'captured': False}
    if not all(present):
        raise ValueError('Incomplete optional VU0 register metadata')
    def words(values, count):
        if not isinstance(values, list) or len(values) != count:
            raise ValueError('Invalid VU0 register dimensions')
        if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-fA-F]{1,8}', v) for v in values):
            raise ValueError('Invalid raw VU0 32-bit word')
        return [int(v, 16) for v in values]
    vf = metadata['vu0_vf_hex']
    if not isinstance(vf, list) or len(vf) != 32:
        raise ValueError('Expected 32 VU0 vector registers')
    vectors = [words(row, 4) for row in vf]
    qpi = words(metadata['vu0_qpi_hex'], 3)
    acc = words(metadata['vu0_acc_hex'], 4)
    vi = metadata['vu0_vi']
    if not isinstance(vi, list) or len(vi) != 16:
        raise ValueError('Expected 16 VU0 integer registers')
    integers = vi + [metadata[name] for name in fields[4:]]
    if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in integers):
        raise ValueError('Invalid unsigned VU0 register')
    def decode(row):
        values = struct.unpack('<' + 'f' * len(row), struct.pack('<' + 'I' * len(row), *row))
        return [v if math.isfinite(v) else str(v) for v in values]
    decoded = [decode(row) for row in vectors]
    return {'captured': True, 'vf_raw_u32': vectors, 'vf_float_observations': decoded,
            'vi': vi, 'qpi_raw_u32': qpi, 'acc_raw_u32': acc,
            'vf_nonfinite_observations': sum(isinstance(v, str) for row in decoded for v in row),
            'controls': {name: metadata[name] for name in fields[4:]},
            'limits': 'Raw pre-call observations; nonfinite bit patterns alone do not prove a rendering fault.'}


def inspect(ram, root, limit=256):
    if len(ram) != 32 * 1024 * 1024:
        raise ValueError('Expected complete 32 MiB EE RAM')
    def offset(pointer, size):
        physical = pointer & 0x1FFFFFFF
        if pointer >> 29 not in (0, 4, 5) or physical < 0x1000 or physical + size > len(ram) or physical % 4:
            raise ValueError(f'Pointer outside aligned EE RAM: {pointer:#x}')
        return physical
    def word(pointer):
        return struct.unpack_from('<I', ram, offset(pointer, 4))[0]
    def row(pointer):
        values = struct.unpack_from('<4f', ram, offset(pointer, 16))
        return [value if math.isfinite(value) else str(value) for value in values]
    offset(root, 0x3B8)
    records, problems, seen = [], [], set()
    first = word(root + 0x110)
    pointer = first
    while pointer and len(records) < limit:
        if pointer in seen:
            problems.append({'kind': 'cycle', 'address': hex(pointer)})
            break
        seen.add(pointer)
        try:
            offset(pointer, 0x270)
            record = {'address': hex(pointer), 'parent': hex(word(pointer + 0x100)),
                      'next': hex(word(pointer + 0x110)), 'flags': hex(word(pointer + 0x114)),
                      'world_rows': [row(pointer + n) for n in (0x10, 0x20, 0x30, 0x40)],
                      'local_rows': [row(pointer + n) for n in (0x50, 0x60, 0x70, 0x80)],
                      'local_scale': row(pointer + 0xE0), 'world_scale': row(pointer + 0xF0)}
            record['nonfinite_values'] = sum(isinstance(v, str) for field in ('world_rows', 'local_rows')
                                             for vector in record[field] for v in vector)
            record['nonfinite_values'] += sum(isinstance(v, str) for field in ('local_scale', 'world_scale')
                                              for v in record[field])
            records.append(record)
            pointer = word(pointer + 0x110)
        except ValueError as error:
            problems.append({'kind': 'invalid_pointer', 'address': hex(pointer), 'detail': str(error)})
            break
    if pointer and len(records) == limit:
        problems.append({'kind': 'cap_reached', 'limit': limit})
    # Parent pointers influence transforms independently of the next chain.
    # Validate bounded ancestry, allowing the root as its terminating parent.
    addresses = {int(record['address'], 16) & 0x1FFFFFFF: record for record in records}
    root_physical = root & 0x1FFFFFFF
    for record in records:
        current = record
        ancestry = set()
        while int(current['parent'], 16):
            parent = int(current['parent'], 16)
            try:
                physical = offset(parent, 0x50)
            except ValueError as error:
                problems.append({'kind': 'invalid_parent', 'part': record['address'], 'detail': str(error)})
                break
            if physical == root_physical:
                break
            if physical in ancestry:
                problems.append({'kind': 'parent_cycle', 'part': record['address']})
                break
            ancestry.add(physical)
            if physical not in addresses:
                problems.append({'kind': 'parent_outside_captured_chain', 'part': record['address'], 'parent': hex(parent)})
                break
            current = addresses[physical]
    return {'root': hex(root), 'root_flags': hex(word(root)), 'first_part': hex(first),
            'getPartsPtr_contiguous_storage': bool(word(root) & 0x2000),
            'linked_parts': records, 'link_problems': problems,
            'nonfinite_values': sum(row['nonfinite_values'] for row in records)}


def selftest():
    ram = bytearray(32 * 1024 * 1024)
    struct.pack_into('<I', ram, 0x1110, 0x2000)
    clean = inspect(ram, 0x1000)
    assert len(clean['linked_parts']) == 1 and not clean['link_problems'] and clean['nonfinite_values'] == 0
    struct.pack_into('<I', ram, 0x2110, 0x2000)
    assert inspect(ram, 0x1000)['link_problems'][0]['kind'] == 'cycle'
    struct.pack_into('<I', ram, 0x2110, 0xFFFFFFFC)
    assert inspect(ram, 0x1000)['link_problems'][0]['kind'] == 'invalid_pointer'
    struct.pack_into('<I', ram, 0x2110, 0)
    struct.pack_into('<I', ram, 0x2050, 0x7FC00000)
    assert inspect(ram, 0x1000)['nonfinite_values'] == 1
    assert inspect(ram, 0x80001000)['first_part'] == hex(0x2000)
    struct.pack_into('<I', ram, 0x2100, 0xFFFFFFFC)
    assert any(p['kind'] == 'invalid_parent' for p in inspect(ram, 0x1000)['link_problems'])
    struct.pack_into('<I', ram, 0x2100, 0x2000)
    assert any(p['kind'] == 'parent_cycle' for p in inspect(ram, 0x1000)['link_problems'])
    struct.pack_into('<I', ram, 0x2100, 0x3000)
    assert any(p['kind'] == 'parent_outside_captured_chain' for p in inspect(ram, 0x1000)['link_problems'])
    struct.pack_into('<I', ram, 0x2100, 0x80001000)
    assert not inspect(ram, 0x1000)['link_problems']
    assert inspect_vu0({}) == {'captured': False}
    sample = {'vu0_vf_hex': [['0'] * 4 for _ in range(32)], 'vu0_vi': [0] * 16,
              'vu0_qpi_hex': ['0'] * 3, 'vu0_acc_hex': ['0'] * 4,
              **{name: 0 for name in ('vu0_status', 'vu0_mac', 'vu0_clip', 'vu0_tpc', 'fbrst', 'vpu_stat')}}
    sample['vu0_vf_hex'][1][0] = '7fc00000'
    assert inspect_vu0(sample)['vf_nonfinite_observations'] == 1
    for invalid in ({'vu0_vi': [0] * 16}, {**sample, 'vu0_acc_hex': ['100000000'] * 4},
                    {**sample, 'vu0_vf_hex': [['0'] * 4]}, {**sample, 'vu0_vi': [True] * 16}):
        try:
            inspect_vu0(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid VU0 capture accepted')
    return {'passed': True, 'cases': ['complete-chain', 'cycle', 'bad-pointer', 'nonfinite-matrix',
            'cached-RAM-alias', 'legacy-no-vu', 'raw-vu-nonfinite', 'partial-vu',
            'oversized-vu-word', 'wrong-vu-dimensions', 'boolean-vu-integer',
            'invalid-parent', 'parent-cycle', 'unobserved-parent', 'root-parent-alias']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metadata', type=Path, nargs='?')
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.selftest:
        result = selftest()
    else:
        if args.metadata is None:
            parser.error('Supply call metadata or --selftest')
        metadata = json.loads(args.metadata.read_text(encoding='utf-8'))
        if metadata['schema'] != 1 or metadata['ram_bytes'] != 33554432 or metadata['target'] != 0x22CF28:
            raise ValueError('Expected partsWorldCalc pre-call capture')
        path = args.metadata.with_suffix('.ram.bin')
        ram = path.read_bytes()
        root = int(metadata['gpr_hex'][4][0], 16) & 0xFFFFFFFF
        result = {'scope': __doc__, 'metadata': str(args.metadata.resolve()),
                  'ram_sha256': hashlib.sha256(ram).hexdigest(),
                  'metadata_sha256': hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
                  'ee_vsync': metadata['vsync'], 'requested_ee_vsync': metadata.get('requested_vsync'),
                  'caller': hex(metadata['source']), 'vu0': inspect_vu0(metadata), **inspect(ram, root)}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2, allow_nan=False)
    print(json.dumps({k: v for k, v in result.items() if k not in ('linked_parts', 'scope', 'vu0')}))


if __name__ == '__main__':
    main()
