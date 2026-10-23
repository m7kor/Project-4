#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout.py -- 64 KB structural map of a flash image + header dumps."""
import hashlib
import os
import struct
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def rd(p):
    with open(p, "rb") as f:
        return f.read()


def asc(b):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


def mapfile(flash, sibname, label):
    sib = rd(os.path.join(BD, sibname))
    print("=== %s (%d bytes, sha %s) vs flash ===" % (
        label, len(sib), hashlib.sha256(sib).hexdigest()[:16]))
    # try every 0x1000-aligned offset, report best match fraction over 4KB
    best = []
    for off in range(0, len(flash) - 0x1000, 0x1000):
        a = flash[off:off + 0x1000]
        b = sib[:0x1000]
        same = sum(1 for x, y in zip(a, b) if x == y)
        best.append((same, off))
    best.sort(reverse=True)
    print("   best 4KB match fractions:", " ".join(
        "0x%06x:%.3f" % (o, s / 4096.0) for s, o in best[:5]))


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "SCPH-70004_BIOS_V12_PAL_200.BIN"
    flash = rd(os.path.join(BD, name))
    print("flash %s 0x%x sha256=%s" % (name, len(flash), hashlib.sha256(flash).hexdigest()))
    print("  ROMSCRT at:", [hex(i) for i in [flash.find(b"ROMSCRT")]])

    print("\n=== 64 KB block map ===")
    print("off      ent   z%%    ff%%   top byte values")
    for o in range(0, len(flash), 0x10000):
        c = flash[o:o + 0x10000]
        cnt = Counter(c)
        n = len(c)
        ent = -sum((v / float(n)) * (v / float(n)).__rpow__(0.5) * 0 for v in [])
        import math
        ent = -sum((v / float(n)) * math.log(v / float(n), 2) for v in cnt.values())
        z = 100.0 * cnt.get(0, 0) / n
        ff = 100.0 * cnt.get(0xFF, 0) / n
        top = cnt.most_common(3)
        print("0x%06x %.2f %5.1f %5.1f   %s" % (
            o, ent, z, ff, " ".join("%02x:%.0f%%" % (k, 100.0 * v / n) for k, v in top)))

    print("\n=== first 32 bytes of each 64 KB boundary ===")
    for o in range(0, len(flash), 0x10000):
        b = flash[o:o + 32]
        w = struct.unpack(">8I", b)
        print("0x%06x  %s | %s" % (o, " ".join("%08x" % x for x in w), asc(b[:32])))

    for sib, lbl in (("SCPH-70004_BIOS_V12_PAL_200.ROM1", "ROM1"),
                     ("SCPH-70004_BIOS_V12_PAL_200.EROM", "EROM"),
                     ("SCPH-70004_BIOS_V12_PAL_200.NVM", "NVM"),
                     ("rom1.bin", "rom1.bin")):
        if os.path.exists(os.path.join(BD, sib)):
            mapfile(flash, sib, lbl)


if __name__ == "__main__":
    main()
