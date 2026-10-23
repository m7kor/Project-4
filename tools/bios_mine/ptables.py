#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ptables.py -- list every run of kernel-text pointers in the kernel's data, with
both its kernel VA and its PHYSICAL address (kernel image base = physical 0)."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")
B = 0x39E490


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    minrun = int(sys.argv[4], 0) if len(sys.argv) > 4 else 4
    d = open(os.path.join(BD, f), "rb").read()
    n = (hi - lo) // 4
    vals = [struct.unpack_from("<I", d, lo + 4 * i)[0] for i in range(n)]
    runs = []
    i = 0
    while i < n:
        if 0x80000000 <= vals[i] < 0x80020000:
            j = i
            while j < n and (0x80000000 <= vals[j] < 0x80020000 or vals[j] == 0):
                j += 1
            if j - i >= minrun:
                nz = sum(1 for k in range(i, j) if vals[k])
                runs.append((lo + 4 * i, j - i, nz))
            i = j
        else:
            i += 1
    print("pointer runs (>=%d words, zeros allowed) in [0x%06x,0x%06x): %d" % (
        minrun, lo, hi, len(runs)))
    for (o, ln, nz) in runs:
        va = 0x80000000 + (o - B)
        inlow = "  ** inside physical [0,0x80000)" if (o - B) < 0x80000 else ""
        print("  file 0x%06x  VA 0x%08x  PHYS 0x%08x  words=%3d nonzero=%3d  end VA 0x%08x%s" % (
            o, va, o - B, ln, nz, va + 4 * ln, inlow))


if __name__ == "__main__":
    main()