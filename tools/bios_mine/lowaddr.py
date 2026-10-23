#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lowaddr.py -- every distinct 32-bit constant the kernel materialises that
lands in KUSEG (i.e. a physical address below 0x80000000), with the sites that
build it. This enumerates the low-RAM addresses the kernel actually touches."""
import os
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")
B = 0x39E490


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    hi_lim = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x1000000
    lo_lim = int(sys.argv[5], 0) if len(sys.argv) > 5 else 0x1000
    d = open(os.path.join(BD, f), "rb").read()
    n = (hi - lo) // 4
    ws = [struct.unpack_from("<I", d, lo + 4 * i)[0] for i in range(n)]
    sites = defaultdict(list)
    for i, w in enumerate(ws):
        op = w >> 26
        rs = (w >> 21) & 0x1F
        rt = (w >> 16) & 0x1F
        imm = w & 0xFFFF
        if op in (0x09, 0x0D) and rs == 0:
            v = imm
            if imm >= 0x8000:
                v = imm  # keep raw; a bare addiu/ori with rs=0 is 'li'
            if lo_lim <= v < hi_lim:
                sites[v].append((lo + 4 * i, "li"))
            continue
        if op != 0x0F:
            continue
        if not (0 < imm < 0x8000):
            continue
        for k in range(1, 9):
            if i + k >= n:
                break
            w2 = ws[i + k]
            o2 = w2 >> 26
            if o2 not in (0x09, 0x0D):
                continue
            r2s = (w2 >> 21) & 0x1F
            r2t = (w2 >> 16) & 0x1F
            i2 = w2 & 0xFFFF
            s2 = i2 - 0x10000 if i2 >= 0x8000 else i2
            if r2t != rt or (r2s != rt and r2s != 0):
                continue
            v = (imm << 16) + s2
            if lo_lim <= v < hi_lim:
                sites[v].append((lo + 4 * i, "lui+%d" % k))
            break
    print("distinct KUSEG (<0x%08x) constants materialised by the kernel: %d" % (hi_lim, len(sites)))
    for v in sorted(sites):
        ss = sites[v]
        print("  0x%08x  (%2d site(s))  %s" % (
            v, len(ss), " ".join("0x%06x/VA 0x%08x" % (o, 0x80000000 + (o - B)) for o, _ in ss[:5])))


if __name__ == "__main__":
    main()