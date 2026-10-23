#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""luipairs.py -- in the LE-coded kernel region, list every lui/addiu pair that
materialises a KSEG0 address. This is how we recover code that builds the
syscall-table base and code that references the kernel's string literals."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    lohi = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x8010
    d = open(os.path.join(BD, f), "rb").read()
    ws = []
    for o in range(lo, hi, 4):
        ws.append(struct.unpack_from("<I", d, o)[0])
    n = len(ws)
    out = []
    for i in range(n):
        w = ws[i]
        if (w >> 26) != 0x0F:
            continue
        imm = w & 0xFFFF
        if not (0x8000 <= imm <= lohi):
            continue
        rt = (w >> 16) & 0x1F
        for k in (1, 2, 3):
            if i + k >= n:
                break
            w2 = ws[i + k]
            if (w2 >> 26) != 0x09:
                continue
            rs2 = (w2 >> 21) & 0x1F
            rt2 = (w2 >> 16) & 0x1F
            if rs2 != rt or rt2 != rt:
                continue
            simm = w2 & 0xFFFF
            if simm >= 0x8000:
                simm -= 0x10000
            val = (imm << 16) + simm
            if 0x80000000 <= val < 0x80200000:
                out.append((lo + 4 * i, rt, val, k))
                break
    print("lui/addiu pairs materialising KSEG0 addrs in [0x%06x,0x%06x): %d" % (lo, hi, len(out)))
    seen = {}
    for o, rt, v, k in out:
        seen.setdefault(v, []).append(o)
    for v in sorted(seen):
        print("   0x%08x  (%d sites: %s)" % (
            v, len(seen[v]), " ".join("0x%x" % x for x in seen[v][:6])))
    return out


if __name__ == "__main__":
    main()
