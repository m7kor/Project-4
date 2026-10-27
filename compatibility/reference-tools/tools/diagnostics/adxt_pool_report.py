"""Decode RE4's CRI ADXT handle pool from "[EE words]" dumps (PS2X_DUMP_WORDS).

The pool is 16 handles of 0xC4 bytes at 0x3115C0 (adxt_Create, 0x17E668):
+0 used, +1 status (0 stop, 1 decinfo, 2 prep, 3 playing, 4 decend, 5 playend,
6 error), +4 ADX decoder, +8 stream (SJ), +0xC RNA output, +0x48 block size,
+0x70 hold-until-sync, +0x71 prepared, +0x72 no-auto-start. Dump the pool with
PS2X_DUMP_WORDS=0x3115a0:0x1000 at the vsyncs of interest.

    python -I tools/diagnostics/adxt_pool_report.py RUNDIR
"""
import argparse
from pathlib import Path
import re
import struct

POOL = 0x3115C0
SIZE = 0xC4
LINE = re.compile(rb'^\[EE words\] v=(\d+) 0x([0-9a-f]+):(.*)$')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    with open(args.run / 'stderr.txt', 'rb') as f:
        for line in f:
            m = LINE.match(line.rstrip())
            if not m:
                continue
            base = int(m[2], 16)
            words = [int(w, 16) for w in m[3].split()]
            data = struct.pack(f'<{len(words)}I', *words)
            if not (base <= POOL < base + len(data)):
                continue
            rows = []
            for i in range(16):
                o = POOL - base + i * SIZE
                if o + SIZE > len(data):
                    break
                h = data[o:o + SIZE]
                if h[0] == 0:
                    continue
                dec, sj, rna = struct.unpack_from('<III', h, 4)
                block = struct.unpack_from('<I', h, 0x48)[0]
                rows.append(f'#{i} st={h[1]} hold={h[0x70]} prep={h[0x71]} noauto={h[0x72]} '
                            f'dec={dec:#x} sj={sj:#x} rna={rna:#x} blk={block:#x}')
            print(f'v={m[1].decode()}: ' + (' | '.join(rows) if rows else 'no handles in use'))


if __name__ == '__main__':
    main()
