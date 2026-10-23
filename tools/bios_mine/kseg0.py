#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kseg0.py -- hunt for KSEG0 (0x8000xxxx) pointer tables in any BIOS image."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def runs(data, lo, hi, minrun, show=6, maxshow=40):
    n = len(data) // 4
    ws = struct.unpack(">%dI" % n, data[:n * 4])
    out = []
    i = 0
    while i < n:
        if lo <= ws[i] <= hi:
            j = i
            while j < n and lo <= ws[j] <= hi:
                j += 1
            if (j - i) >= minrun:
                out.append((i * 4, j - i))
            i = j
        else:
            i += 1
    print("  runs>=%d in [0x%08x,0x%08x]: %d" % (minrun, lo, hi, len(out)))
    for o, l in out[:maxshow]:
        print("     off=0x%06x words=%4d : %s" % (
            o, l, " ".join("%08x" % v for v in ws[o // 4:o // 4 + show])))
    return out


def main():
    names = sys.argv[1:] or ["SCPH-70004_BIOS_V12_PAL_200.BIN", "scph10000.bin",
                             "scph39001.bin", "PS2 Bios 30004R V6 Pal.bin"]
    for nm in names:
        p = os.path.join(BD, nm)
        if not os.path.exists(p):
            print("missing", nm)
            continue
        d = open(p, "rb").read()
        print("=== %s (0x%x) ===" % (nm, len(d)))
        runs(d, 0x80000000, 0x80200000, 16)
        # also count how many 0x8000-high words overall
        n = len(d) // 4
        ws = struct.unpack(">%dI" % n, d[:n * 4])
        c = sum(1 for v in ws if 0x80000000 <= v < 0x80200000)
        print("  total 0x8000xxxx words: %d" % c)
        # lui 0x8000
        l = [i * 4 for i, v in enumerate(ws)
             if (v >> 26) == 0x0F and (v & 0xFFFF) == 0x8000]
        print("  lui rt,0x8000 : %d hits %s" % (len(l), " ".join("0x%x" % x for x in l[:20])))
        # lui 0x800f / 0x0008 etc: any lui with imm in 0x8000..0x800f
        l2 = [(i * 4, v & 0xFFFF) for i, v in enumerate(ws)
              if (v >> 26) == 0x0F and 0x8000 <= (v & 0xFFFF) <= 0x800f]
        print("  lui rt,0x800X : %d hits %s" % (len(l2), " ".join("0x%x/%x" % x for x in l2[:20])))


if __name__ == "__main__":
    main()
