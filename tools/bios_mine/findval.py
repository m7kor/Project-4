#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""findval.py -- find every occurrence of a 32-bit value, read both BE and LE,
anywhere in an image. Used to locate constants inside data tables as well as code."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    n = len(d)
    for arg in sys.argv[4:]:
        t = int(arg, 0)
        hits = []
        o = 0
        pat_le = struct.pack("<I", t)
        pat_be = struct.pack(">I", t)
        start = 0
        while True:
            k = d.find(pat_le, start)
            if k < 0:
                break
            if k % 4 == 0:
                hits.append((k, "LE"))
            start = k + 1
        start = 0
        while True:
            k = d.find(pat_be, start)
            if k < 0:
                break
            if k % 4 == 0:
                hits.append((k, "BE"))
            start = k + 1
        hits = [h for h in hits if lo <= h[0] < hi]
        print("value 0x%08x : %d hit(s)" % (t, len(hits)))
        for (k, w) in hits[:40]:
            ctx = d[max(0, k - 8):k + 12]
            print("    file 0x%06x  %s   ctx=%s" % (k, w, ctx.hex()))


if __name__ == "__main__":
    main()