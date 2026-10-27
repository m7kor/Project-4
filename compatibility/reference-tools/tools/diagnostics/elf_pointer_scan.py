"""Report candidate indirect-call targets; never modify the dispatch/config.

python -m tools.diagnostics.elf_pointer_scan ELF --json NEW_REPORT
Only file-backed, allocated, non-executable sections supply pointers. Targets
must be aligned and inside file-backed executable sections. A plausible first
instruction is evidence, not proof of a function or C++ vtable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def _bounded(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('ELF range exceeds file')
    return data[offset:offset + size]


def _sections(data):
    _bounded(data, 0, 52)
    if data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('Expected ELF32 little-endian version 1')
    if struct.unpack_from('<H', data, 18)[0] != 8:
        raise ValueError('Expected MIPS ELF')
    offset = struct.unpack_from('<I', data, 32)[0]
    width, count = struct.unpack_from('<HH', data, 46)
    if not count or width < 40:
        raise ValueError('Normal ELF section table required')
    _bounded(data, offset, width * count)
    sections = []
    for index in range(count):
        section = struct.unpack_from('<10I', data, offset + index * width)
        _, kind, flags, address, file_offset, size, *_ = section
        if address + size > 0x100000000:
            raise ValueError('Section address wraps')
        if kind != 8:  # NOBITS has no contents on disk
            _bounded(data, file_offset, size)
        if flags & 2 and size and kind != 8:  # SHF_ALLOC
            sections.append((index, flags, address, _bounded(data, file_offset, size)))
    code = [s for s in sections if s[1] & 4]
    if not code:
        raise ValueError('No file-backed executable sections')
    for i, section in enumerate(code):
        for other in code[i + 1:]:
            if max(section[2], other[2]) < min(section[2] + len(section[3]), other[2] + len(other[3])):
                raise ValueError('Overlapping executable sections')
    return sections, code


def _hint(word):
    if word & 0xFFFF0000 == 0x27BD0000 and word & 0x8000:
        return 'negative_stack_adjustment'
    if word & 0xFFFF0000 in (0xFFBF0000, 0xAFBF0000, 0x7FBF0000):
        return 'save_return_address'
    if word == 0x03E00008:
        return 'return_stub'
    if word & 0xFFE00000 == 0x3C000000:
        return 'lui_start_weak'
    return 'unclassified'


def scan(data):
    sections, code = _sections(data)
    candidates = {}
    for index, flags, base, buf in sections:
        if flags & 4:
            continue
        # Align guest address rather than assuming the section starts aligned.
        for offset in range((-base) & 3, len(buf) - 3, 4):
            target = struct.unpack_from('<I', buf, offset)[0]
            if target & 3:
                continue
            for _, _, start, instructions in code:
                relative = target - start
                if 0 <= relative <= len(instructions) - 4:
                    word = struct.unpack_from('<I', instructions, relative)[0]
                    item = candidates.setdefault(target, {
                        'target': target, 'first_instruction': word,
                        'entry_hint': _hint(word), 'references': []})
                    item['references'].append({'section_index': index, 'address': base + offset})
                    break
    return {'schema': 1, 'elf_sha256': hashlib.sha256(data).hexdigest(),
            'scope': 'static pointer candidates; not verified functions, vtables, or overlay coverage',
            'executable_ranges': [{'start': s[2], 'end': s[2] + len(s[3])} for s in code],
            'candidates': [candidates[key] for key in sorted(candidates)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('elf', type=Path)
    parser.add_argument('--json', type=Path, required=True)
    parser.add_argument('--registered', type=Path, help='Generated register_functions.cpp for comparison')
    args = parser.parse_args()
    report = scan(args.elf.read_bytes())
    report['elf'] = str(args.elf.resolve())
    if args.registered:
        import re
        registered = {int(m, 16) for m in re.findall(r'// 0x([0-9a-fA-F]+)\s*$',
                      args.registered.read_text(encoding='utf-8'), re.MULTILINE)}
        if not registered:
            raise ValueError('No recognizable dispatch entries; cannot compare')
        for item in report['candidates']:
            item['registered'] = item['target'] in registered
        report['dispatch_file_sha256'] = hashlib.sha256(args.registered.read_bytes()).hexdigest()
    with args.json.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    missing = (sum(item.get('registered') is False for item in report['candidates'])
               if args.registered else None)
    print(json.dumps({'candidates': len(report['candidates']), 'unregistered_candidates': missing,
                      'report': str(args.json.resolve())}))


if __name__ == '__main__':
    main()
