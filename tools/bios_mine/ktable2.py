#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ktable2.py -- locate the syscall-style table: runs of LE (or BE) words that
are either 0 or a KSEG0 pointer."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def ok(v, lo, hi):
    return v == 0 or (lo <= v <= hi)


def find(ws, lo, hi, minrun):
    n = len(ws)
    out = []
    i = 0
    while i < n:
        if ok(ws[i], lo, hi):
            j = i
            while j < n and ok(ws[j], lo, hi):
                j += 1
            if (j - i) >= minrun:
                out.append((i * 4, j - i))
            i = j
        else:
            i += 1
    return out


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "SCPH-70004_BIOS_V12_PAL_200.BIN"
    d = open(os.path.join(BD, name), "rb").read()
    n = len(d) // 4
    be = list(struct.unpack(">%dI" % n, d[:n * 4]))
    le = list(struct.unpack("<%dI" % n, d[:n * 4]))
    lo, hi = 0x80000000, 0x80200000
    for label, ws in (("BE", be), ("LE", le)):
        for minrun in (32, 64, 128, 0x100):
            r = find(ws, lo, hi, minrun)
            print("%s minrun=%d : %d runs" % (label, minrun, len(r)))
            for o, l in r[:25]:
                nz = sum(1 for k in range(o // 4, o // 4 + l) if ws[k])
                print("    off=0x%06x words=%4d nonzero=%4d first=%08x last=%08x" % (
                    o, l, nz, ws[o // 4], ws[o // 4 + l - 1]))


if __name__ == "__main__":
    main()
