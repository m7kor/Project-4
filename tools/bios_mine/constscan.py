#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""constscan.py -- locate every place the kernel materialises a given 32-bit
constant, either as `ori/addiu rt,$zero,imm` (the `li` idiom) or as a
lui+ori/addiu pair. Used to check the claimed low-RAM addresses."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")
B = 0x39E490


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    targets = set(int(t, 0) for t in sys.argv[4:])
    d = open(os.path.join(BD, f), "rb").read()
    n = (hi - lo) // 4
    ws = [struct.unpack_from("<I", d, lo + 4 * i)[0] for i in range(n)]

    def va(o):
        return 0x80000000 + (o - B)

    for t in sorted(targets):
        print("=== target 0x%08x ===" % t)
        found = False
        for i, w in enumerate(ws):
            op = w >> 26
            rs = (w >> 21) & 0x1F
            rt = (w >> 16) & 0x1F
            imm = w & 0xFFFF
            simm = imm - 0x10000 if imm >= 0x8000 else imm
            hit = False
            how = ""
            if op in (0x09, 0x0D) and rs == 0 and imm == t:
                hit, how = True, ("li/ori" if op == 0x0D else "addiu") + " $zero"
            elif op == 0x0F and (t >> 16) == imm:
                low = t & 0xFFFF
                for k in range(1, 9):
                    if i + k >= n:
                        break
                    w2 = ws[i + k]
                    o2 = w2 >> 26
                    r2s = (w2 >> 21) & 0x1F
                    r2t = (w2 >> 16) & 0x1F
                    i2 = w2 & 0xFFFF
                    s2 = i2 - 0x10000 if i2 >= 0x8000 else i2
                    if o2 in (0x09, 0x0D) and r2s == rt and r2t == rt and s2 == low:
                        hit, how = True, "lui+%d: addiu" % k
                        break
                    if o2 == 0x0D and r2t == rt and i2 == low and (r2s == rt or r2s == 0):
                        hit, how = True, "lui+%d: ori" % k
                        break
            if hit:
                found = True
                site = lo + 4 * i
                print("   file 0x%06x  VA 0x%08x   (%s)  word=%08x" % (site, va(site), how, w))
        if not found:
            print("   not found in [0x%06x,0x%06x)" % (lo, hi))


if __name__ == "__main__":
    main()