#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quick.py -- ad-hoc helpers used while mining (kept small on purpose)."""
import hashlib
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def rd(p):
    with open(p, "rb") as f:
        return f.read()


def hx(b, n=32):
    return " ".join("%02x" % x for x in b[:n])


def main():
    flash = rd(os.path.join(BD, "SCPH-70004_BIOS_V12_PAL_200.BIN"))
    print("flash sha256", hashlib.sha256(flash).hexdigest())
    for name, ln in (("ROM1", 0x80000), ("ROM2", 0x80000)):
        sib = rd(os.path.join(BD, "SCPH-70004_BIOS_V12_PAL_200." + name))
        for off in (0, 0x80000):
            a = flash[off:off + 16]
            b = sib[:16]
            x = bytes(p ^ q for p, q in zip(a, b))
            same = (a == b)
            print("flash@0x%06x %s first16: %s" % (off, name, hx(a)))
            print("            sib      first16: %s  same=%s xor=%s" % (hx(b), same, hx(x)))
    er = rd(os.path.join(BD, "SCPH-70004_BIOS_V12_PAL_200.EROM"))
    for off in (0x100000, 0, 0x20000):
        a = flash[off:off + 16]
        b = er[:16]
        print("flash@0x%06x erom first16: %s same=%s" % (off, hx(a), a == b))

    print("\n--- 4KB region tags: first nonzero 0xFF run / structure ---")
    # report where 0xFF fills start (end of a chip region)
    i = 0
    n = len(flash)
    while i < n:
        if flash[i] == 0xFF:
            j = i
            while j < n and flash[j] == 0xFF:
                j += 1
            if j - i >= 0x2000:
                print("  0x%06x..0x%06x  all-0xFF  (%d bytes)" % (i, j, j - i))
            i = j
        else:
            i += 1
    print("\n--- all-0x00 runs >= 0x2000 ---")
    i = 0
    while i < n:
        if flash[i] == 0x00:
            j = i
            while j < n and flash[j] == 0x00:
                j += 1
            if j - i >= 0x2000:
                print("  0x%06x..0x%06x  all-0x00  (%d bytes)" % (i, j, j - i))
            i = j
        else:
            i += 1


if __name__ == "__main__":
    main()
