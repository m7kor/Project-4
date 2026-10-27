"""Print the IOP CDVD import calls that follow a given sceCdRV read in a run.

Used to compare a run where a movie stream keeps going with one where it stops
after the prefill: the calls (ordinal, a0, a1, v0, caller ra) right after the
last shared read show where the two diverge. Cycles are printed relative to
the anchor read.

    python -I tools/diagnostics/cdvd_after_read.py RUNDIR --lsn 1064640 [--count 60]
"""
import argparse
from pathlib import Path
import re

CALL = re.compile(rb'\[CDVD import\] cycles=(\d+) ordinal=(\d+) pc=\S+ ra=(0x[0-9a-f]+) a0=(0x[0-9a-f]+) '
                  rb'a1=(0x[0-9a-f]+) a2=(0x[0-9a-f]+) a3=\S+ v0=(0x[0-9a-f]+)')
NAMES = {63: 'sceCdRV', 50: 'sceCdSC', 11: 'sceCdSync', 8: 'sceCdGetError', 4: 'sceCdInit', 75: 'sceCdMmode',
         84: 'sceCdLayerSearchFile', 47: 'sceGetFsvRbuf'}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--lsn', type=lambda v: int(v, 0), required=True)
    parser.add_argument('--count', type=int, default=60)
    parser.add_argument('--skip-polls', action='store_true', help='hide sceCdSync/sceCdGetError polls')
    args = parser.parse_args()
    anchor = None
    shown = 0
    with open(args.run / 'stderr.txt', 'rb') as f:
        for line in f:
            m = CALL.search(line)
            if not m:
                continue
            cycles, ordinal, ra, a0, a1, a2, v0 = int(m[1]), int(m[2]), m[3].decode(), int(m[4], 16), \
                int(m[5], 16), int(m[6], 16), int(m[7], 16)
            if anchor is None:
                if ordinal == 63 and a0 == args.lsn:
                    anchor = cycles
                else:
                    continue
            if args.skip_polls and ordinal in (8, 11):
                continue
            print(f'{cycles - anchor:+12d} {NAMES.get(ordinal, ordinal):>14} a0={a0:#x} a1={a1:#x} a2={a2:#x} '
                  f'v0={v0:#x} ra={ra}')
            shown += 1
            if shown >= args.count:
                break
    if anchor is None:
        print('anchor read not found')


if __name__ == '__main__':
    main()
