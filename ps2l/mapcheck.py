"""Check ELF branch destinations against a function map without changing it.

This is a structural gate, not proof of code/data classification or playability.
The decoder is deliberately independent of the analyzer's control-flow walker.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import csv
import hashlib
import json
from pathlib import Path
import sys

try:
    from .analyze import Elf
except ImportError:
    from analyze import Elf


def destination(pc: int, word: int) -> int | None:
    op = word >> 26
    if op in (2, 3, 29):
        return ((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
    branch = op in (4, 5, 6, 7, 20, 21, 22, 23)
    branch |= op == 1 and ((word >> 16) & 31) in (0, 1, 2, 3, 16, 17, 18, 19)
    branch |= op in (17, 18) and ((word >> 21) & 31) == 8
    if not branch:
        return None
    immediate = word & 0xFFFF
    if immediate & 0x8000:
        immediate -= 0x10000
    return (pc + 4 + immediate * 4) & 0xFFFFFFFF


def audit(words: dict[int, int], ranges: list[tuple[int, int]]) -> dict:
    ranges = sorted(ranges)
    invalid = []
    valid = []
    addresses = sorted(words)
    if not ranges:
        invalid.append(['', '', 'empty function map'])
    for start, end in ranges:
        if start & 3 or end & 3 or end <= start or start not in words or end - 4 not in words:
            invalid.append([hex(start), hex(end), 'invalid extent'])
        elif bisect_left(addresses, end) - bisect_left(addresses, start) != (end - start) // 4:
            invalid.append([hex(start), hex(end), 'extent crosses absent code words'])
        elif valid and start < valid[-1][1]:
            invalid.append([hex(start), hex(end), 'overlap or duplicate'])
        else:
            valid.append((start, end))
    starts = [a for a, _ in valid]

    def owner(address):
        i = bisect_right(starts, address) - 1
        return valid[i][0] if i >= 0 and address < valid[i][1] else None

    missing, external, truncated = [], [], []
    branches = 0
    for pc, word in sorted(words.items()):
        if owner(pc) is None:
            continue
        target = destination(pc, word)
        if target is not None:
            branches += 1
            evidence = {'source':hex(pc), 'target':hex(target), 'word':hex(word)}
            if target not in words:
                external.append(evidence)
            elif owner(target) is None:
                missing.append(evidence)
        op = word >> 26
        has_slot = target is not None or (op == 0 and (word & 63) in (8, 9))
        if has_slot and (pc + 4 not in words or owner(pc + 4) is None):
            truncated.append({'source':hex(pc), 'slot':hex(pc + 4)})
    return {'scope':'static mapped body code', 'game_compatibility':'unverified',
            'functions':len(valid), 'branches_checked':branches,
            'invalid_ranges':invalid, 'unmapped_targets':missing,
            'unmapped_delay_slots':truncated, 'external_targets':external,
            'passed':not (invalid or missing or truncated)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('map', type=Path)
    parser.add_argument('--out', type=Path, default=Path('artifacts/mapcheck/latest.json'))
    args = parser.parse_args(argv)
    elf = Elf(args.elf)
    _, words = elf.code_words()
    with args.map.open(encoding='utf-8-sig', newline='') as source:
        ranges = [(int(r['Start'], 0), int(r['End'], 0)) for r in csv.DictReader(source)]
    report = audit(words, ranges)
    report.update(elf=str(args.elf.resolve()), function_map=str(args.map.resolve()))
    report.update(elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),
                  function_map_sha256=hashlib.sha256(args.map.read_bytes()).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {report['branches_checked']} branches; "
          f"{len(report['unmapped_targets'])} missing targets; "
          f"{len(report['unmapped_delay_slots'])} missing slots; "
          f"{len(report['invalid_ranges'])} invalid ranges")
    print(f'Report: {args.out.resolve()}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
