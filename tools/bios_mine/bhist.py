#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bhist.py -- histogram of candidate base offsets B derived from data pointers
that must land on the first byte of an ASCII run."""
import os
import struct
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def le(d, o):
    return struct.unpack_from("<I", d, o)[0]


def main():
    f = sys.argv[1]
    dlo = int(sys.argv[2], 0)
    dhi = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    runs = []
    o = 0
    n = len(d)
    while o < n:
        if 32 <= d[o] < 127:
            j = o
            while j < n and (32 <= d[j] < 127 or d[j] in (9, 10, 13)):
                j += 1
            if j - o >= 6:
                runs.append((o, j - o))
            o = j
        else:
            o += 1
    hist = Counter()
    detail = {}
    for o in range(dlo, dhi, 4):
        v = le(d, o)
        if not (0x80000000 <= v < 0x80200000):
            continue
        off = v - 0x80000000
        for (rs, rl) in runs:
            if rs <= 0x3b5400 and rl >= 8 and off > 0:
                B = rs - off
                if 0x390000 <= B <= 0x3b0000:
                    hist[B] += 1
                    detail.setdefault(B, []).append((o, v, rs))
    for B, c in hist.most_common(12):
        print("B=0x%06x  hits=%d" % (B, c))
        for (o, v, rs) in detail[B][:8]:
            s = d[rs:rs + 44]
            print("      ptr@0x%06x VA 0x%08x -> file 0x%06x %r" % (
                o, v, rs, "".join(chr(c) if 32 <= c < 127 else "" for c in s)))


if __name__ == "__main__":
    main()
