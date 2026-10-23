#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledump.py -- dump a window showing both BE and LE word reads + ascii."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(ROOT, "bios")


def main():
    f = sys.argv[1]
    at = int(sys.argv[2], 0)
    cnt = int(sys.argv[3], 0)
    d = open(os.path.join(BD, f), "rb").read()
    for i in range(cnt):
        o = at + 4 * i
        if o + 4 > len(d):
            break
        be = struct.unpack_from(">I", d, o)[0]
        le = struct.unpack_from("<I", d, o)[0]
        asc = "".join(chr(c) if 32 <= c < 127 else "." for c in d[o:o + 4])
        tag = ""
        if 0x80000000 <= le < 0x80200000:
            tag = " KSEG0"
        elif 0x80000000 <= be < 0x80200000:
            tag = " kseg0-BE"
        print("0x%06x  be=%08x le=%08x |%s| %s" % (o, be, le, asc, tag))


if __name__ == "__main__":
    main()
