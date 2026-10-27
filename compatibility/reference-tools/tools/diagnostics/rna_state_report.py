"""Decode RE4's CRI PS2RNA / SJ-over-DTX state from "[EE words]" dumps.

Structures (found with GhidraMCP, see docs/CURRENT.md):
  RNA handles     16 x 100  at 0x3088D0: +0 used, +0x20 IOP id, +0x2C ring size,
                  +0x50 play, +0x52 channels, +0x58 drain, +0x59 stopped,
                  +0x5A/+0x5B pause sent/wanted
  SJ remote       32 x 0x14 at 0x30EB50: +0 used, +4 SJ, +0xC lane sent to IOP,
                  +0x10 IOP id (t256 target)
  SIF SJ copy     32 x 0x40 at 0x319FF8: +1 run, +2 DMA busy, +4 src SJ, +8 dst SJ
  SJUNI (any SJ)  +4 used, +5 merge, +0x14 free nodes, +0x18 lane heads[4];
                  node = {next, ?, addr, size}

Dump with, e.g.
  PS2X_DUMP_STACKS_AT=11127,11145
  PS2X_DUMP_WORDS=0x3088d0:0x640,0x30eb50:0x280,0x319ff8:0x800
Add SJ addresses printed here to PS2X_DUMP_WORDS (with their node pools) to see
lane totals (--sj).

    python -I tools/diagnostics/rna_state_report.py RUNDIR
"""
import argparse
from pathlib import Path
import re
import struct

LINE = re.compile(rb'^\[EE words\] v=(\d+) 0x([0-9a-f]+):(.*)$')


class Snapshot:
    def __init__(self):
        self.ranges = []

    def add(self, base, data):
        self.ranges.append((base, data))

    def read(self, addr, size):
        for base, data in self.ranges:
            if base <= addr and addr + size <= base + len(data):
                return data[addr - base:addr - base + size]
        return None

    def u32(self, addr):
        b = self.read(addr, 4)
        return None if b is None else struct.unpack('<I', b)[0]

    def u8(self, addr):
        b = self.read(addr, 1)
        return None if b is None else b[0]


def lanes(snap, sj):
    if snap.read(sj, 0x30) is None:
        return None
    out = []
    for lane in range(4):
        node = snap.u32(sj + 0x18 + lane * 4)
        total, count = 0, 0
        while node and count < 256:
            size = snap.u32(node + 0xC)
            nxt = snap.u32(node)
            if size is None or nxt is None:
                return None
            total += size
            count += 1
            node = nxt
        out.append(f'{total:#x}/{count}')
    return ' '.join(out)


def report(v, snap):
    print(f'--- v={v}')
    sjs = set()
    for i in range(16):
        h = 0x3088D0 + i * 100
        if snap.u8(h) != 1:
            continue
        b = snap.read(h, 100)
        ch = b[0x52]
        objs = struct.unpack_from('<4I', b, 8)
        print(f'RNA#{i} iop={struct.unpack_from("<I", b, 0x20)[0]:#x} ring={struct.unpack_from("<I", b, 0x2C)[0]:#x} '
              f'play={b[0x50]}/{b[0x51]} ch={ch} drain={b[0x58]} stopped={b[0x59]} pause={b[0x5B]}/{b[0x5A]} '
              f'chobj={" ".join(hex(o) for o in objs[:max(ch, 1)])} xfer={" ".join(hex(x) for x in struct.unpack_from("<4I", b, 0x10)[:max(ch, 1)])}')
        for o in objs[:ch]:
            sj = snap.u32(o + 8)
            if sj:
                sjs.add(sj)
    for i in range(32):
        h = 0x30EB50 + i * 0x14
        if snap.u8(h) != 1:
            continue
        sj = snap.u32(h + 4)
        if sj is None:
            continue
        sjs.add(sj)
        print(f'SJRMT#{i} @{h:#x} sj={sj:#x} lane={snap.u8(h + 0xC)} iop={snap.u32(h + 0x10):#x}')
    for i in range(32):
        h = 0x319FF8 + i * 0x40
        if snap.u8(h) != 1:
            continue
        src, dst = snap.u32(h + 4), snap.u32(h + 8)
        if src is None or dst is None:
            continue
        sjs.update((src, dst))
        print(f'XFER#{i} @{h:#x} run={snap.u8(h + 1)} dma={snap.u8(h + 2)} src={src:#x} dst={dst:#x} '
              f'moved={snap.u32(h + 0x3C):#x}')
    for sj in sorted(s for s in sjs if s):
        info = lanes(snap, sj)
        print(f'SJ {sj:#x}: ' + (f'lanes(free,data,2,3)={info}' if info else 'not dumped'))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    snaps = {}
    with open(args.run / 'stderr.txt', 'rb') as f:
        for line in f:
            m = LINE.match(line.rstrip())
            if not m:
                continue
            words = [int(w, 16) for w in m[3].split()]
            snaps.setdefault(int(m[1]), Snapshot()).add(int(m[2], 16), struct.pack(f'<{len(words)}I', *words))
    for v in sorted(snaps):
        report(v, snaps[v])


if __name__ == '__main__':
    main()
