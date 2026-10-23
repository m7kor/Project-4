#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ktable.py -- dump a kernel table read as LE words, with index annotations."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    at = int(sys.argv[2], 0)
    cnt = int(sys.argv[3], 0)
    base_va = int(sys.argv[4], 0)
    d = open(os.path.join(BD, f), "rb").read()
    for i in range(cnt):
        o = at + 4 * i
        if o + 4 > len(d):
            break
        v = struct.unpack_from("<I", d, o)[0]
        mark = ""
        if v == 0:
            mark = "   <empty>"
        print("[%3d] 0x%03x  file 0x%06x  VA 0x%08x  0x%08x%s" % (
            i, i * 4, o, base_va + 4 * i, v, mark))


if __name__ == "__main__":
    main()
