"""Show how IOP thread states change across a run's "[IOP threads]" dumps.

Prints one row per dump with each thread as id:state@pc, and marks threads
whose state or pc differs from the previous dump, so a stall shows which IOP
threads stopped moving.

    python -I tools/diagnostics/iop_thread_timeline.py RUNDIR [--last 15]
"""
import argparse
from pathlib import Path
import re

DUMP = re.compile(rb'\[IOP threads\](.*)')
THREAD = re.compile(rb'\{id=(\d+) state=(\d+) priority=(\d+) pc=(0x[0-9a-f]+)[^}]*?wait=(\d+)')
CYCLES = re.compile(rb'cycles=(\d+)')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--last', type=int, default=15)
    args = parser.parse_args()
    rows = []
    last_cycles = 0
    with open(args.run / 'stderr.txt', 'rb') as f:
        for line in f:
            if m := CYCLES.search(line):
                last_cycles = int(m[1])
            if m := DUMP.search(line):
                threads = {int(t[1]): (int(t[2]), t[4].decode(), int(t[3])) for t in THREAD.finditer(m[1])}
                rows.append((last_cycles, threads))
    previous = {}
    for index, (cycles, threads) in enumerate(rows):
        if index >= len(rows) - args.last:
            cells = []
            for tid, (state, pc, priority) in sorted(threads.items()):
                mark = '*' if previous.get(tid) != (state, pc, priority) else ' '
                cells.append(f'{mark}{tid}:s{state}@{pc}')
            print(f'#{index:3d} iop_frame~{cycles // 614400:6d} ' + ' '.join(cells))
        previous = threads
    print(f'{len(rows)} dumps')


if __name__ == '__main__':
    main()
