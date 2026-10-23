#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""explore.py -- ad-hoc probes used while locating the EE kernel."""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import Image, decode  # noqa: E402


def u32s(data):
    n = len(data) // 4
    return struct.unpack(">%dI" % n, data[:n * 4])


def find_word(data, word, name="word"):
    n = len(data) // 4
    ws = u32s(data)
    hits = [i * 4 for i in range(n) if ws[i] == word]
    print("%s == 0x%08x : %d hits" % (name, word, len(hits)))
    for h in hits[:64]:
        print("   0x%06x" % h)
    return hits


def ptr_runs(data, lo, hi, minrun, label):
    n = len(data) // 4
    ws = u32s(data)
    runs = []
    i = 0
    while i < n:
        if lo <= ws[i] <= hi:
            j = i
            while j < n and lo <= ws[j] <= hi:
                j += 1
            if j - i >= minrun:
                runs.append((i * 4, j - i))
            i = j
        else:
            i += 1
    print("ptr runs in [0x%08x,0x%08x] >=%d : %d" % (lo, hi, minrun, len(runs)))
    for o, l in runs[:40]:
        vals = ws[o // 4:o // 4 + min(l, 6)]
        print("   off=0x%06x words=%d : %s" % (
            o, l, " ".join("%08x" % v for v in vals)))
    return runs


def code_score(ws, start, count, base):
    """Fraction of decoded words that are plausible instructions."""
    bad = 0
    tot = 0
    for i in range(count):
        d = decode(ws[start + i], base + 4 * i)
        tot += 1
        if "?" in d["mnem"]:
            bad += 1
    return 1.0 - float(bad) / max(tot, 1)


def main():
    path = sys.argv[1]
    data = open(path, "rb").read()
    ws = u32s(data)
    print("file %s size 0x%x" % (path, len(data)))

    print("\n--- exact word search: syscall (0x0000000c) ---")
    find_word(data, 0x0000000C, "syscall")

    print("\n--- exact word search: nop ---")
    # skip, too many

    print("\n--- pointer runs ---")
    for lo, hi in [(0x80000000, 0x80100000), (0x00000000, 0x00200000),
                   (0xBFC00000, 0xBFFFFFFF), (0x00100000, 0x01FFFFFF),
                   (0x80000000, 0x8FFFFFFF), (0x00000000, 0x000FFFFF)]:
        ptr_runs(data, lo, hi, 16, "x")

    print("\n--- high-byte histogram per 64KB (looking for 0x8? kernel image) ---")
    for o in range(0, len(data), 0x10000):
        chunk = ws[o // 4:(o + 0x10000) // 4]
        if not chunk:
            break
        h = {}
        for v in chunk:
            h[v >> 24] = h.get(v >> 24, 0) + 1
        top = sorted(h.items(), key=lambda kv: -kv[1])[:4]
        print("0x%06x  n=%5d  " % (o, len(chunk)) +
              "  ".join("%02x:%5.1f%%" % (k, 100.0 * v / len(chunk))
                        for k, v in top))


if __name__ == "__main__":
    main()
