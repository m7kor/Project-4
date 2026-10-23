#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ktables.py -- find tables of KSEG0 pointers stored either big- or little-endian."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def runs(ws, lo, hi, minrun, label, show=12, maxshow=60):
    n = len(ws)
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
    print("%s: %d runs >= %d" % (label, len(out), minrun))
    for o, l in out[:maxshow]:
        print("   off=0x%06x words=%4d : %s" % (
            o, l, " ".join("%08x" % v for v in ws[o // 4:o // 4 + show])))
    return out


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "SCPH-70004_BIOS_V12_PAL_200.BIN"
    d = open(os.path.join(BD, name), "rb").read()
    n = len(d) // 4
    be = list(struct.unpack(">%dI" % n, d[:n * 4]))
    le = list(struct.unpack("<%dI" % n, d[:n * 4]))
    lo, hi = 0x80000000, 0x80200000
    runs(be, lo, hi, 8, "BE")
    runs(le, lo, hi, 8, "LE")
    lo2, hi2 = 0x00000000, 0x00200000
    runs(be, lo2, hi2, 32, "BE-low")


if __name__ == "__main__":
    main()
