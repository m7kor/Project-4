#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kdat.py -- compact nonzero map of the kernel data window (LE word view)."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    at = int(sys.argv[2], 0)
    cnt = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    gap = 0
    for i in range(cnt):
        o = at + 4 * i
        if o + 4 > len(d):
            break
        le = struct.unpack_from("<I", d, o)[0]
        if le == 0:
            gap += 1
            continue
        if gap:
            print("   ... %d zero words" % gap)
            gap = 0
        asc = "".join(chr(c) if 32 <= c < 127 else "." for c in d[o:o + 4])
        tag = " KSEG0" if 0x80000000 <= le < 0x80200000 else ""
        print("0x%06x [%4d] le=%08x |%s|%s" % (o, i, le, asc, tag))
    if gap:
        print("   ... %d zero words" % gap)


if __name__ == "__main__":
    main()
