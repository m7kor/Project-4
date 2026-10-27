"""Report SIF DMA streams in a run traced with PS2X_TRACE_SIF and when each stopped.

Groups "[SIF EE>IOP]" / "[SIF IOP>EE]" lines by direction, destination and
size, and gives each stream's count, its transfers after the last disc read,
and the EE vsync (from the nearest preceding "[vsync] N" marker, printed by
the scheduler when PS2X_TRACE_SIF is set) of its first and last transfer. A stream whose
last transfer is far before the end of the run is one that stopped, e.g. at a
stall.

    python -I tools/diagnostics/sif_stream_report.py RUNDIR [--min-count 5]
"""
import argparse
from pathlib import Path
import re

SIF = re.compile(rb'\[SIF (EE>IOP|IOP>EE)\] src=0x([0-9a-f]+) dst=0x([0-9a-f]+) size=0x([0-9a-f]+)')
CYCLES = re.compile(rb'^\[vsync\] (\d+)')
IOP_FRAME = 1  # the clock is the EE vsync marker


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--min-count', type=int, default=5)
    args = parser.parse_args()
    streams = {}
    cycles = 0
    lines = (args.run / 'stderr.txt').read_bytes().splitlines()
    last_read = max((i for i, line in enumerate(lines) if b'ordinal=63 ' in line), default=0)
    for i, line in enumerate(lines):
        if m := CYCLES.search(line):
            cycles = int(m[1])
        m = SIF.search(line)
        if not m:
            continue
        key = (m[1].decode(), int(m[3], 16), int(m[4], 16))
        entry = streams.setdefault(key, [0, cycles, cycles, 0])
        entry[0] += 1
        entry[2] = cycles
        if i > last_read:
            entry[3] += 1
    end = max((v[2] for v in streams.values()), default=0)
    print(f'last trace cycle ~ frame {end // IOP_FRAME}')
    for (direction, dst, size), (count, first, last, after) in sorted(streams.items(), key=lambda kv: kv[1][2]):
        if count < args.min_count:
            continue
        print(f'{direction} dst=0x{dst:07x} size=0x{size:05x} n={count:6d} frames {first // IOP_FRAME:6d}..'
              f'{last // IOP_FRAME:6d} after_last_disc_read={after}')


if __name__ == '__main__':
    main()
