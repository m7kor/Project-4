#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""leline.py -- precise (64-byte) boundary finder for LE-coded regions."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def run_len(d, o, hi, nbytes=0x400):
    """how far from o does LE decoding stay clean (no '?' mnemonics)"""
    bad = 0
    best = 0
    cur = 0
    i = 0
    while o + 4 * i + 4 <= hi and i * 4 < nbytes:
        w = struct.unpack_from("<I", d, o + 4 * i)[0]
        dd = decode(w, 0x80000000 + 4 * i)
        if "?" in dd["mnem"]:
            bad += 1
            cur = 0
        else:
            cur += 1
            best = max(best, cur)
        i += 1
    return best, i


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    step = 0x40
    prev = False
    for o in range(lo, hi, step):
        n = 0x400 // 4
        if o + 0x400 > len(d):
            break
        ws = struct.unpack_from("<%dI" % n, d, o)
        bad = sum(1 for w in ws if "?" in decode(w, 0)["mnem"])
        nz = sum(1 for w in ws if w)
        clean = bad == 0 and nz > 0x60
        if clean != prev:
            print("%s 0x%06x  bad=%d nz=%d" % ("LE-CODE " if clean else "        ", o, bad, nz))
            prev = clean


if __name__ == "__main__":
    main()
