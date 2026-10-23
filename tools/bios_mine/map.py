#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map.py -- locate sibling files inside the 4 MB flash, and map region structure."""
import hashlib
import os
import sys

BIOS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BD = os.path.join(BIOS, "bios")


def rd(p):
    with open(p, "rb") as f:
        return f.read()


def locate(flash, sub, name):
    """find all offsets in flash where sub occurs"""
    hits = []
    i = flash.find(sub[:0x1000])
    while i >= 0:
        if flash[i:i + len(sub)] == sub:
            hits.append(i)
            i = flash.find(sub[:0x1000], i + 1)
        else:
            i = flash.find(sub[:0x1000], i + 1)
    print("%-34s len=%7d  -> flash offsets %s" % (
        name, len(sub), " ".join("0x%06x" % h for h in hits) or "NOT FOUND"))
    return hits


def mapfile(flash, path):
    sub = rd(path)
    return locate(flash, sub, os.path.basename(path))


def summarise(data, name, granularity=0x1000):
    print("\n=== %s  (0x%x bytes) ===" % (name, len(data)))
    prev = None
    start = 0
    lines = []
    for o in range(0, len(data), granularity):
        chunk = data[o:o + granularity]
        z = chunk.count(0)
        ffr = chunk.count(0xFF)
        if z == len(chunk):
            tag = "ZERO"
        elif ffr == len(chunk):
            tag = "FF  "
        else:
            counts = {}
            for b in chunk:
                counts[b] = counts.get(b, 0) + 1
            import math
            n = len(chunk)
            ent = -sum((c / float(n)) * math.log(c / float(n), 2) for c in counts.values())
            tag = "ent=%.2f" % ent
        if tag != prev:
            lines.append((o, tag))
            prev = tag
    for o, tag in lines:
        print("   0x%06x  %s" % (o, tag))


def main():
    b = sys.argv[1] if len(sys.argv) > 1 else "SCPH-70004_BIOS_V12_PAL_200.BIN"
    flash = rd(os.path.join(BD, b))
    print("flash %s  0x%x  sha256=%s" % (b, len(flash), hashlib.sha256(flash).hexdigest()))
    for sib in ("SCPH-70004_BIOS_V12_PAL_200.ROM1",
                "SCPH-70004_BIOS_V12_PAL_200.ROM2",
                "SCPH-70004_BIOS_V12_PAL_200.EROM",
                "SCPH-70004_BIOS_V12_PAL_200.NVM"):
        p = os.path.join(BD, sib)
        if os.path.exists(p):
            mapfile(flash, p)
    p = os.path.join(BD, "rom1.bin")
    if os.path.exists(p):
        mapfile(flash, p)
    summarise(flash, b)


if __name__ == "__main__":
    main()
