"""Diff two per-vsync guest call profiles (PS2X_CALL_PROFILE_AT).

Prints the functions called in frame A but not in frame B (and the reverse),
with call counts and, where the RE4 name table knows one, a nearby name.

    python -I tools/diagnostics/call_profile_diff.py RUNDIR A B [--names names.json]

A and B are a vsync or an inclusive range "first-last"; profiles inside a
range are summed.
"""
import argparse
import bisect
import json
from pathlib import Path
import re

LINE = re.compile(rb'^\[call profile\] v=(\d+) functions=\d+(.*)$')


def profiles(run):
    out = {}
    with open(run / 'stderr.txt', 'rb') as f:
        for line in f:
            m = LINE.match(line.rstrip())
            if m:
                counts = {}
                for item in m[2].split():
                    address, count = item.split(b':')
                    counts[int(address, 16)] = int(count)
                out[int(m[1])] = counts
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('a')
    parser.add_argument('b')
    parser.add_argument('--names', type=Path, default=Path('artifacts/research/20261011/re4-names.json'))
    parser.add_argument('--limit', type=int, default=80)
    args = parser.parse_args()
    data = profiles(args.run)
    print('profiles at vsyncs:', sorted(data))
    names = {}
    if args.names.exists():
        names = {int(k, 16): v for k, v in json.loads(args.names.read_text(encoding='utf-8')).items()}
    starts = sorted(names)

    def label(address):
        if address in names:
            return names[address]
        i = bisect.bisect_right(starts, address) - 1
        return f'near {names[starts[i]]}+{address - starts[i]:#x}' if i >= 0 and address - starts[i] < 0x400 else ''

    def window(spec):
        first, _, last = spec.partition('-')
        first, last = int(first), int(last or first)
        merged = {}
        for vsync, counts in data.items():
            if first <= vsync <= last:
                for address, count in counts.items():
                    merged[address] = merged.get(address, 0) + count
        return merged

    a, b = window(args.a), window(args.b)
    for title, x, y in ((f'only in {args.a}', a, b), (f'only in {args.b}', b, a)):
        rows = sorted(((count, address) for address, count in x.items() if address not in y), reverse=True)
        print(f'== {title}: {len(rows)} functions')
        for count, address in rows[:args.limit]:
            print(f'  {address:#08x} x{count:<6d} {label(address)}')


if __name__ == '__main__':
    main()
