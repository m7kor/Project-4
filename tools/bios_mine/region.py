#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""region.py -- hex+word+disasm dump of an arbitrary window, with candidate
pointer detection (BE and 16-bit-halfword-swapped LE)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    at = int(sys.argv[2], 0)
    cnt = int(sys.argv[3], 0)
    va = int(sys.argv[4], 0) if len(sys.argv) > 4 else None
    d = open(f if os.path.isabs(f) else os.path.join(BD, f), "rb").read()
    if len(sys.argv) > 4 and sys.argv[4].startswith("raw"):
        va = None
    for i in range(cnt):
        o = at + 4 * i
        w = struct.unpack_from(">I", d, o)[0]
        le = struct.unpack_from("<I", d, o)[0]
        pc = (va + 4 * i) if va is not None else 0
        txt = ""
        if va is not None:
            dd = decode(w, pc)
            txt = dd["mnem"] + ((" " + ", ".join(a for a in dd["args"] if a)) if dd["args"] else "")
        flag = ""
        if 0x80000000 <= w < 0x80200000:
            flag = " <-KSEG0"
        elif 0x80000000 <= le < 0x80200000:
            flag = " <-KSEG0(LE)"
        print("0x%06x %08x | %s%s" % (o, w, txt, flag))


if __name__ == "__main__":
    main()
