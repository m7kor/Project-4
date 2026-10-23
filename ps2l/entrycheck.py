"""Audit observed fault targets against generated dispatch entries, read-only.

Static map coverage does not imply an interior PC is registered. This checks
current generated sources, not a historical executable or game compatibility.
"""
from __future__ import annotations
import argparse
from bisect import bisect_right
import csv
import hashlib
import json
from pathlib import Path
import re

try:
    from .analyze import Elf
except ImportError:
    from analyze import Elf


def registration(text: str) -> dict[int, str]:
    base_match = re.search(r'g_ps2RecompiledFunctionTableBase\s*=\s*(0x[0-9a-fA-F]+|\d+)u;', text)
    if not base_match:
        raise ValueError('Missing generated table base; unsupported registration format.')
    base = int(base_match[1], 0)
    result = {}
    for match in re.finditer(r'g_ps2RecompiledFunctionTable\[(\d+)\]\s*=\s*([A-Za-z_]\w*)\s*;\s*//\s*(0x[0-9a-fA-F]+)', text):
        address = base + int(match[1]) * 4
        if address != int(match[3], 0) or address > 0xffffffff:
            raise ValueError('Dense slot and address annotation disagree.')
        if address in result:
            raise ValueError('Duplicate dispatch address.')
        result[address] = match[2]
    count_match = re.search(r'g_ps2RecompiledFunctionSparseCount\s*=\s*(\d+)u;', text)
    if not count_match:
        raise ValueError('Missing sparse count; unsupported registration format.')
    count = int(count_match[1])
    if count:
        def array(name):
            match = re.search(name + r'\[\d+u\]\s*=\s*\{([^}]*)\};', text)
            if not match:
                raise ValueError('Missing sparse array.')
            return [part.strip() for part in match[1].split(',')]
        addresses = array('g_ps2RecompiledFunctionSparseAddress')
        names = array('g_ps2RecompiledFunctionSparseTarget')
        if len(addresses) != count or len(names) != count:
            raise ValueError('Sparse array lengths disagree with count.')
        for raw, name in zip(addresses, names):
            if not re.fullmatch(r'(0x[0-9a-fA-F]+|\d+)u', raw) or not re.fullmatch(r'[A-Za-z_]\w*', name):
                raise ValueError('Unsupported sparse entry.')
            address = int(raw[:-1], 0)
            if address & 3 or address > 0xffffffff or address in result:
                raise ValueError('Invalid or duplicate sparse address.')
            result[address] = name
    return result


def audit(words: dict[int, int], ranges: list[tuple[int, int]], entries: dict[int, str],
          trace: str, sources: dict[str, str]) -> dict:
    ranges = sorted(ranges)
    starts = [start for start, _ in ranges]
    targets = {}
    for number, line in enumerate(trace.splitlines(), 1):
        if '[guest-branch:missing-target]' not in line:
            continue
        match = re.search(r'\btarget=(0x[0-9a-fA-F]+)\b', line)
        if match:
            targets.setdefault(int(match[1], 0), []).append(number)
    rows = []
    for address, lines in sorted(targets.items()):
        index = bisect_right(starts, address) - 1
        owner = ranges[index][0] if index >= 0 and address < ranges[index][1] else None
        name = entries.get(address)
        status = 'registered'
        if address & 3:
            status = 'unaligned-target'
        elif address not in words:
            status = 'target-not-in-elf-code'
        elif not name:
            status = 'unregistered-interior-entry' if owner is not None and owner != address else 'unregistered-entry'
        else:
            source = sources.get(name, '')
            extent = re.search(r'// Address: (0x[0-9a-fA-F]+) - (0x[0-9a-fA-F]+)', source)
            if not extent:
                status = 'generated-body-unavailable'
            else:
                start, end = int(extent[1], 0), int(extent[2], 0)
                if not start <= address < end:
                    status = 'registered-body-does-not-own-target'
                elif address != start:
                    case = re.search(r'case\s+0x0*' + f'{address:x}' + r'u:\s*goto\s+(\w+)\s*;', source, re.I)
                    if not case or not re.search(r'^\s*' + re.escape(case[1]) + r':', source, re.M):
                        status = 'registered-interior-entry-without-resume-case'
        rows.append({'target': hex(address), 'owner': hex(owner) if owner is not None else None,
                     'registered_function': name, 'trace_lines': lines, 'status': status})
    return {'scope': 'observed targets against current generated dispatch sources',
            'game_compatibility': 'unverified', 'targets': rows,
            'passed': bool(rows) and all(row['status'] == 'registered' for row in rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('map', type=Path)
    parser.add_argument('trace', type=Path, help='stderr text or a native capture directory')
    parser.add_argument('generated', type=Path)
    parser.add_argument('--out', type=Path, default=Path('artifacts/entrycheck/latest.json'))
    args = parser.parse_args(argv)
    report = {'passed': False, 'game_compatibility': 'unverified'}
    try:
        elf_hash = hashlib.sha256(args.elf.read_bytes()).hexdigest()
        trace_file = args.trace / 'stderr.txt' if args.trace.is_dir() else args.trace
        if args.trace.is_dir():
            captured = json.loads((args.trace / 'report.json').read_text(encoding='utf-8'))
            if captured.get('elf_sha256') != elf_hash:
                raise ValueError('Capture ELF identity differs from the current ELF.')
        elf = Elf(args.elf)
        _, words = elf.code_words()
        with args.map.open(encoding='utf-8-sig', newline='') as stream:
            ranges = [(int(row['Start'], 0), int(row['End'], 0)) for row in csv.DictReader(stream)]
        table = args.generated / 'register_functions.cpp'
        entries = registration(table.read_text(encoding='utf-8'))
        trace = trace_file.read_text(encoding='utf-8', errors='replace')
        names = {entries[int(m[1], 0)] for m in re.finditer(r'\btarget=(0x[0-9a-fA-F]+)\b', trace)
                 if int(m[1], 0) in entries}
        sources = {name: (args.generated / (name + '.cpp')).read_text(encoding='utf-8')
                   for name in names if (args.generated / (name + '.cpp')).is_file()}
        report = audit(words, ranges, entries, trace, sources)
        report.update(elf_sha256=elf_hash, registration_sha256=hashlib.sha256(table.read_bytes()).hexdigest(),
                      trace_sha256=hashlib.sha256(trace_file.read_bytes()).hexdigest(),
                      map_sha256=hashlib.sha256(args.map.read_bytes()).hexdigest())
    except (OSError, ValueError, KeyError) as exc:
        report['error'] = str(exc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for row in report.get('targets', []):
        print(f"{row['target']}: {row['status']} (owner {row['owner']})")
    print(f"{'PASS' if report['passed'] else 'FAIL'}: current generated sources only; native behavior remains unverified.")
    if report.get('error'):
        print(report['error'])
    print(f'Report: {args.out.resolve()}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
