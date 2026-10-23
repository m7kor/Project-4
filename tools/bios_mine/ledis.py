#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledis.py -- disassemble treating the flash image as little-endian 32-bit words."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def leword(d, o):
    return struct.unpack_from("<I", d, o)[0]


def main():
    f = sys.argv[1]
    at = int(sys.argv[2], 0)
    cnt = int(sys.argv[3], 0)
    va = int(sys.argv[4], 0)
    d = open(os.path.join(BD, f), "rb").read()
    for i in range(cnt):
        o = at + 4 * i
        if o + 4 > len(d):
            break
        w = leword(d, o)
        pc = va + 4 * i
        dd = decode(w, pc)
        txt = dd["mnem"] + ((" " + ", ".join(a for a in dd["args"] if a)) if dd["args"] else "")
        mark = ""
        if dd["has_delay"]:
            mark = " ;"
        print("%08x: %08x  %s%s" % (pc, w, txt, mark))


if __name__ == "__main__":
    main()
