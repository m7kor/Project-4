#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe.py -- targeted MIPS pattern probes over a raw image."""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import decode  # noqa: E402


def u32s(data):
    n = len(data) // 4
    return struct.unpack(">%dI" % n, data[:n * 4])


def hits(ws, pred):
    return [i * 4 for i in range(len(ws)) if pred(ws[i], i)]


def ctx(data, off, before=6, after=10, base=0xBFC00000, tag=""):
    print("--- %s @ file 0x%06x ---" % (tag, off))
    n = len(data) // 4
    lo = max(0, (off // 4) - before)
    hi = min(n, (off // 4) + after)
    for i in range(lo, hi):
        o = i * 4
        w = struct.unpack_from(">I", data, o)[0]
        d = decode(w, base + o)
        mark = ">>" if o == off else "  "
        txt = d["mnem"] + ((" " + ", ".join(a for a in d["args"] if a)) if d["args"] else "")
        print("%s 0x%06x  %08x  %s" % (mark, o, w, txt))


def main():
    path = sys.argv[1]
    data = open(path, "rb").read()
    ws = u32s(data)
    print("image 0x%x" % len(data))

    print("\n### lui reg,0x8000  (lui rt,8000)")
    h = hits(ws, lambda w, i: (w >> 26) == 0x0F and (w & 0xFFFF) == 0x8000)
    print("count=%d  offsets: %s" % (len(h), " ".join("0x%x" % x for x in h[:40])))

    print("\n### lui reg,0x8001 / 0x0000 (li-like)")
    for imm in (0x8001, 0x0000, 0x0001):
        h = hits(ws, lambda w, i, imm=imm: (w >> 26) == 0x0F and (w & 0xFFFF) == imm)
        print("  lui 0x%04x : %d hits  %s" % (imm, len(h), " ".join("0x%x" % x for x in h[:24])))

    print("\n### addiu rt,zero / lui+addiu pairs forming 0x8000xxxx (not in this pass)")

    print("\n### j / jal targets (top 40 most common)")
    from collections import Counter
    c = Counter()
    for i in range(len(ws)):
        w = ws[i]
        op = (w >> 26) & 0x3F
        if op in (0x02, 0x03) and (w & 0x03FFFFFF):
            d = decode(w, 0)
            c[d["target"]] += 1
    for t, k in c.most_common(25):
        print("   0x%08x  x%d" % (t, k))

    print("\n### 4KB blocks that decode with >=95%% known opcodes (code density)")
    for o in range(0, len(data), 0x1000):
        b = ws[o // 4:(o + 0x1000) // 4]
        if len(b) < 1024:
            continue
        bad = sum(1 for w in b if "?" in decode(w, 0)["mnem"])
        nz = sum(1 for w in b if w != 0)
        if bad / 1024.0 < 0.03 and nz > 700:
            print("  0x%06x bad=%.3f nonzero=%d" % (o, bad / 1024.0, nz))


if __name__ == "__main__":
    main()
