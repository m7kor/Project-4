#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""base.py -- locate the kernel image base by testing the 32-entry exception
vector table signature at candidate offsets."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def le(d, o):
    return struct.unpack_from("<I", d, o)[0]


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    print("candidates for a 32-word LE KSEG0 pointer run inside [0x%06x,0x%06x]" % (lo, hi))
    for o in range(lo, hi, 4):
        n = 32
        vals = [le(d, o + 4 * k) for k in range(n)]
        if not all(0x80000000 <= v < 0x80200000 for v in vals):
            continue
        # preceding/following blocks must not extend the run far
        uniq = len(set(vals))
        print("  vector table candidate file=0x%06x  ->  VA 0x%08x  uniq=%d" % (
            o, 0x80000000 + 0x80 - (o and 0) if False else 0, uniq))
        print("     ", " ".join("%08x" % v for v in vals[:16]))
        print("     ", " ".join("%08x" % v for v in vals[16:]))

    print("\n--- 16-word runs (for reference) ---")
    for o in range(lo, hi, 4):
        vals = [le(d, o + 4 * k) for k in range(16)]
        if all(0x80000000 <= v < 0x80200000 for v in vals):
            print("  file=0x%06x uniq=%d : %s" % (
                o, len(set(vals)), " ".join("%08x" % v for v in vals[:8])))


if __name__ == "__main__":
    main()
