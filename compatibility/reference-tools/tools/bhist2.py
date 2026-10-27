#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bhist2.py -- recover the kernel image base offset B from lui/addiu code
references: the correct B makes every referenced KSEG0 address land on the first
byte of a real ASCII string in the flash."""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    # string starts
    starts = {}
    o = 0
    while o < len(d):
        if 32 <= d[o] < 127:
            j = o
            while j < len(d) and (32 <= d[j] < 127 or d[j] in (9, 10, 13)):
                j += 1
            if j - o >= 8:
                starts[o] = j - o
            o = j
        else:
            o += 1
    ws = [struct.unpack_from("<I", d, o)[0] for o in range(lo, hi, 4)]
    refs = []
    for i in range(len(ws)):
        w = ws[i]
        if (w >> 26) != 0x0F:
            continue
        imm = w & 0xFFFF
        if not (0x8000 <= imm <= 0x8020):
            continue
        rt = (w >> 16) & 0x1F
        for k in (1, 2, 3, 4):
            if i + k >= len(ws):
                break
            w2 = ws[i + k]
            if (w2 >> 26) != 0x09:
                continue
            if ((w2 >> 21) & 0x1F) != rt or ((w2 >> 16) & 0x1F) != rt:
                continue
            simm = w2 & 0xFFFF
            if simm >= 0x8000:
                simm -= 0x10000
            val = (imm << 16) + simm
            if 0x80000000 <= val < 0x80200000:
                refs.append((lo + 4 * i, val - 0x80000000))
                break
    print("lui/addiu sites: %d" % len(refs))
    hist = Counter()
    detail = {}
    for site, off in refs:
        for rs in starts:
            B = rs - off
            if 0x390000 <= B <= 0x3b0000:
                hist[B] += 1
                detail.setdefault(B, []).append((site, off, rs))
    for B, c in hist.most_common(10):
        print("B=0x%06x hits=%d" % (B, c))
        for (site, off, rs) in detail[B][:14]:
            s = "".join(chr(c) if 32 <= c < 127 else "" for c in d[rs:rs + 46])
            print("     site 0x%06x  VA 0x%08x -> file 0x%06x  %r" % (
                site, off + 0x80000000, rs, s))


if __name__ == "__main__":
    main()
