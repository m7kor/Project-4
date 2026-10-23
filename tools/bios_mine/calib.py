#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib.py -- find the flash base offset B such that VA 0x80000000 + (file - B)
maps kernel .data pointers onto the ASCII strings that live in the same image."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def le(d, o):
    return struct.unpack_from("<I", d, o)[0]


def printable(b):
    return sum(1 for c in b if 32 <= c < 127 or c in (0, 9, 10, 13))


def main():
    f = sys.argv[1]
    dlo = int(sys.argv[2], 0)
    dhi = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    ptrs = []
    for o in range(dlo, dhi, 4):
        v = le(d, o)
        if 0x80000000 <= v < 0x80200000:
            ptrs.append((o, v - 0x80000000))
    # set of file offsets that begin a printable ASCII run of >= 8 chars
    starts = set()
    o = 0
    n = len(d)
    while o < n:
        if 32 <= d[o] < 127:
            j = o
            while j < n and (32 <= d[j] < 127 or d[j] in (9, 10, 13)):
                j += 1
            if j - o >= 8:
                for k in range(o, j - 7):
                    starts.add(k)
            o = j
        else:
            o += 1
    print("KSEG0 pointers in data window: %d ; ascii-run starts: %d" % (len(ptrs), len(starts)))
    best = []
    for B in range(0x390000, 0x3b0000, 4):
        good = 0
        for o, off in ptrs:
            if (B + off) in starts:
                good += 1
        if good:
            best.append((good, B))
    best.sort(reverse=True)
    for g, B in best[:25]:
        print("  B=0x%06x  image=[0x%06x,...)  exact-string-hit=%d/%d" % (B, B, g, len(ptrs)))
    if best:
        g, B = best[0]
        print("\nchosen B=0x%06x; pointer -> file -> ascii" % B)
        for o, off in ptrs:
            fo = B + off
            if 0 <= fo and fo + 12 <= len(d):
                s = "".join(chr(c) if 32 <= c < 127 else "." for c in d[fo:fo + 12])
                if fo in starts:
                    print("   datafile 0x%06x  VA 0x%08x  file 0x%06x  %r" % (
                        o, off + 0x80000000, fo, s))


if __name__ == "__main__":
    main()
