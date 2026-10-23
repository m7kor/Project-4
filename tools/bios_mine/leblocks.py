#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""leblocks.py -- 4 KB code-density map under both BE and 32-bit-swapped (LE) decode."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")

BAD = set()


def score(ws, base):
    bad = 0
    for i, w in enumerate(ws):
        d = decode(w, base + 4 * i)
        if "?" in d["mnem"]:
            bad += 1
        elif d["op"] in (0x00,) and d["rs"] == 0 and d["rt"] == 0 and d["rd"] == 0 and d["word"] != 0:
            pass
    return 1.0 - bad / float(len(ws))


def main():
    f = sys.argv[1] if len(sys.argv) > 1 else "SCPH-70004_BIOS_V12_PAL_200.BIN"
    lo = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
    hi = int(sys.argv[3], 0) if len(sys.argv) > 3 else len(open(os.path.join(BD, f), "rb").read())
    d = open(os.path.join(BD, f), "rb").read()
    print("off      BE-score  LE-score   (fraction of words decoding to a named opcode)")
    for o in range(lo, hi, 0x1000):
        n = 0x1000 // 4
        be = struct.unpack_from(">%dI" % n, d, o)
        le = struct.unpack_from("<%dI" % n, d, o)
        nz = sum(1 for w in be if w)
        sb = score(be, o)
        sl = score(le, o)
        bar = ""
        if sl > 0.90 and sb < sl - 0.05:
            bar = "  <== LE-CODE"
        elif sb > 0.90:
            bar = "  <== BE-CODE"
        print("0x%06x  %.3f     %.3f   nz=%4d%s" % (o, sb, sl, nz, bar))


if __name__ == "__main__":
    main()
