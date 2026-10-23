"""Recover mangled export names embedded in the RE4 ELF.

Records are {name_pointer, value, hash16, kind8, reserved8}; the value
FOLLOWS the name pointer. Do not infer it from preceding words. Both code and
data live in the RWX load segment, so these are export addresses, not proven
function starts. recover() chooses the first alias; export_records() keeps all.

    python -m tools.diagnostics.re4_name_table ELF --out names.json [ADDR...]
"""
import argparse
import bisect
import json
import re
import struct

MANGLED = re.compile(rb'[A-Za-z_][A-Za-z0-9_]*__(?:F|[0-9]+[A-Za-z_]|C?[0-9])[A-Za-z0-9_]*\0')


def segments(elf):
    if len(elf) < 52 or elf[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', elf, 18)[0] != 8:
        raise ValueError('Expected a 32-bit little-endian MIPS ELF')
    ph = struct.unpack_from('<I', elf, 28)[0]
    size = struct.unpack_from('<H', elf, 42)[0]
    count = struct.unpack_from('<H', elf, 44)[0]
    if size < 32 or ph + size * count > len(elf):
        raise ValueError('Invalid program header table')
    result = [struct.unpack_from('<8I', elf, ph + size * i) for i in range(count)]
    for kind, offset, va, _, file_size, memory_size, _, _ in result:
        if kind == 1 and (file_size > memory_size or offset + file_size > len(elf) or va + memory_size > 0x100000000):
            raise ValueError('Invalid load segment bounds')
    return result


def export_records(elf):
    segs = [s for s in segments(elf) if s[0] == 1]

    def to_va(o):
        found = [va + o - at for _, at, va, _, fs, _, _, _ in segs if at <= o < at + fs]
        return found[0] if len(found) == 1 else None

    memory = [(s[2], s[2] + s[5]) for s in segs]
    strings = {}
    for m in MANGLED.finditer(elf):
        va = to_va(m.start())
        if (va is not None and (m.start() == 0 or elf[m.start() - 1] == 0)
                and to_va(m.end() - 1) == va + m.end() - m.start() - 1):
            strings[va] = m.group()[:-1].decode('latin-1')
    records = []
    for o in range(0, len(elf) - 11, 4):
        p, value, hash16, kind, reserved = struct.unpack_from('<IIHBB', elf, o)
        if p not in strings or kind not in (2, 3) or reserved:
            continue
        record_address = to_va(o)
        if (record_address is not None and to_va(o + 11) == record_address + 11
                and any(lo <= value < hi for lo, hi in memory)):
            records.append({'name': strings[p], 'address': value, 'hash16': hash16,
                            'kind': kind, 'export_record': record_address})
    return records, len(strings)


def recover(elf):
    records, total = export_records(elf)
    names = {}
    for row in records:
        names.setdefault(row['address'], row['name'])
    return names, total


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('elf')
    parser.add_argument('addresses', nargs='*')
    parser.add_argument('--out')
    args = parser.parse_args()
    names, total = recover(open(args.elf, 'rb').read())
    print(f'{len(names)} named export addresses from {total} mangled strings; function boundaries unverified')
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump({f'{a:#x}': n for a, n in sorted(names.items())}, f, indent=0)
    starts = sorted(names)
    for text in args.addresses:
        a = int(text, 0)
        i = bisect.bisect_right(starts, a) - 1
        print(f'{a:#08x} ' + (f'{names[starts[i]]}+{a - starts[i]:#x} (nearest export only)' if i >= 0 else '?'))


if __name__ == '__main__':
    main()
