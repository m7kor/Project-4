#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""match.py -- find where a sibling image sits inside the 4 MB flash (relaxed)."""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def rd(p):
    with open(p, "rb") as f:
        return f.read()


def relaxed(flash, sub, label, probe=64):
    print("=== %s (%d bytes) ===" % (label, len(sub)))
    print("   sub[:16] = %s" % " ".join("%02x" % b for b in sub[:16]))
    head = sub[:probe]
    i = flash.find(head)
    if i < 0:
        print("   head not found in flash")
        return
    print("   head(%dB) found at flash 0x%06x" % (probe, i))
    # walk forward in 4KB steps, report first mismatch
    off = i
    good = 0
    while off + 0x1000 <= len(flash) and good + 0x1000 <= len(sub):
        a = flash[off:off + 0x1000]
        b = sub[good:good + 0x1000]
        if a == b:
            good += 0x1000
            off += 0x1000
        else:
            bad = sum(1 for x, y in zip(a, b) if x != y)
            print("   diverges at sub+0x%06x (flash 0x%06x): %d/4096 bytes differ"
                  % (good, off, bad))
            break
    else:
        print("   matched %d bytes contiguously" % good)
    return i, good


def main():
    flash = rd(os.path.join(BD, "SCPH-70004_BIOS_V12_PAL_200.BIN"))
    for sib, probe in (("SCPH-70004_BIOS_V12_PAL_200.EROM", 64),
                       ("SCPH-70004_BIOS_V12_PAL_200.ROM1", 64),
                       ("SCPH-70004_BIOS_V12_PAL_200.NVM", 16),
                       ("rom1.bin", 64)):
        p = os.path.join(BD, sib)
        if os.path.exists(p):
            relaxed(flash, rd(p), sib, probe)
    # Also: the EROM may map at flash+offset; brute force over 0x1000 grid
    er = rd(os.path.join(BD, "SCPH-70004_BIOS_V12_PAL_200.EROM"))
    print("\n=== EROM: does any 4KB of its head appear? ===")
    for k in range(0, min(len(er), 0x40000), 0x1000):
        chunk = er[k:k + 64]
        if all(b == 0 for b in chunk):
            continue
        j = flash.find(chunk)
        if j >= 0:
            print("   erom+0x%06x -> flash 0x%06x  (delta %+d)" % (k, j, j - k))


if __name__ == "__main__":
    main()
