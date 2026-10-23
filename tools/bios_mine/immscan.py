#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""immscan.py -- find every LE-coded kernel instruction whose immediate equals a
target value, and show the surrounding basic block."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")
B = int(os.environ.get("KBASE", "0x39E490"), 0)


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    target = int(sys.argv[4], 0)
    d = open(os.path.join(BD, f), "rb").read()
    n = (hi - lo) // 4
    ws = [struct.unpack_from("<I", d, lo + 4 * i)[0] for i in range(n)]
    hits = []
    for i, w in enumerate(ws):
        op = w >> 26
        if op in (0x0F,):
            continue
        imm = w & 0xFFFF
        if imm == target:
            dd = decode(w, 0)
            if "?" not in dd["mnem"]:
                hits.append(i)
    print("instructions with imm=0x%x in [0x%06x,0x%06x): %d" % (target, lo, hi, len(hits)))
    for i in hits:
        print("  --- site file 0x%06x  VA 0x%08x ---" % (lo + 4 * i, 0x80000000 + (lo + 4 * i - B)))
        for k in range(max(0, i - 6), min(n, i + 4)):
            w = ws[k]
            pc = 0x80000000 + (lo + 4 * k - B)
            dd = decode(w, pc)
            txt = dd["mnem"] + ((" " + ", ".join(a for a in dd["args"] if a)) if dd["args"] else "")
            print("    %08x: %08x  %s%s" % (pc, w, txt, "  <==" if k == i else ""))


if __name__ == "__main__":
    main()