#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan.py -- raw scanners + disassembly driver for PS2 BIOS mining.

Subcommands
  find    <file> [--lo A] [--hi B] [--run N] [--align 4]
          Scan for runs of >= N consecutive 32-bit words inside [lo,hi].
  u32     <file> --at OFF [--count N]
  dis     <file> --at OFF --va VA [--count N]
  strings <file> [--min N] [--at OFF]
  blocks  <file>   (entropy/emptiness map, 4KB)
  findstr <file> --s STR [--at OFF]
"""

import argparse
import hashlib
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdec import Image, decode, disasm  # noqa: E402


def load(path, off=0, ln=None):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read() if ln is None else f.read(ln)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
def cmd_find(a):
    data = load(a.file, a.start, a.length)
    lo, hi = a.lo, a.hi
    n = len(data) // 4
    words = struct.unpack(">%dI" % n, data[:n * 4])
    runs = []
    i = 0
    while i < n:
        if lo <= words[i] <= hi:
            j = i
            while j < n and (lo <= words[j] <= hi):
                j += 1
            if (j - i) >= a.run:
                runs.append((a.start + i * 4, j - i, words[i:j]))
            i = j
        else:
            i += 1
    for off, ln, ws in runs:
        print("RUN off=0x%06x len=%d words=%d" % (off, ln * 4, ln))
        show = min(ln, a.show)
        for k in range(show):
            print("   [%4d] 0x%03x -> 0x%08x" % (k, k * 4, ws[k]))
        if ln > show:
            print("   ... %d more" % (ln - show))
    if not runs:
        print("no runs >= %d words in [0x%08x,0x%08x]" % (a.run, lo, hi))


def cmd_u32(a):
    data = load(a.file)
    off = a.at
    for k in range(a.count):
        o = off + 4 * k
        if o + 4 > len(data):
            break
        v = struct.unpack_from(">I", data, o)[0]
        print("[%4d] off=0x%06x  0x%08x  %10d" % (k, o, v, v))


def cmd_dis(a):
    data = load(a.file)
    img = Image(data, 0)
    for off, va, hexw, txt in disasm(img, a.at, a.count, va=a.va):
        print("%08x: %08x  %s" % (va, int(hexw, 16), txt))


def cmd_strings(a):
    data = load(a.file, a.at)
    out = []
    cur = b""
    start = a.at
    for i, b in enumerate(data):
        if 0x20 <= b < 0x7F or b == 9 or b == 10 or b == 13:
            if not cur:
                start = a.at + i
            cur += bytes([b])
        else:
            if len(cur) >= a.min:
                out.append((start, cur.decode("latin1")))
            cur = b""
    if len(cur) >= a.min:
        out.append((start, cur.decode("latin1")))
    for o, s in out:
        print("0x%06x  %r" % (o, s))
    print("--- %d strings" % len(out))


def cmd_findstr(a):
    data = load(a.file)
    pat = a.s.encode("latin1")
    i = 0
    n = 0
    while True:
        i = data.find(pat, i)
        if i < 0:
            break
        print("0x%06x  %r" % (i, data[max(0, i - 8):i + len(pat) + 8]))
        i += 1
        n += 1
    print("--- %d hits" % n)


def cmd_blocks(a):
    data = load(a.file)
    bs = a.size
    for o in range(0, len(data), bs):
        chunk = data[o:o + bs]
        if not chunk:
            break
        counts = {}
        for b in chunk:
            counts[b] = counts.get(b, 0) + 1
        n = len(chunk)
        ent = -sum((c / float(n)) * math.log(c / float(n), 2) for c in counts.values())
        zero = counts.get(0, 0) == n
        ff = counts.get(0xFF, 0) == n
        tag = "EMPTY0" if zero else ("EMPTYFF" if ff else "")
        print("0x%06x ent=%.3f %s" % (o, ent, tag))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find")
    f.add_argument("file")
    f.add_argument("--start", type=lambda x: int(x, 0), default=0)
    f.add_argument("--length", type=lambda x: int(x, 0), default=None)
    f.add_argument("--lo", type=lambda x: int(x, 0), default=0x80000000)
    f.add_argument("--hi", type=lambda x: int(x, 0), default=0x80200000)
    f.add_argument("--run", type=int, default=16)
    f.add_argument("--show", type=int, default=16)
    f.set_defaults(fn=cmd_find)

    u = sub.add_parser("u32")
    u.add_argument("file")
    u.add_argument("--at", type=lambda x: int(x, 0), required=True)
    u.add_argument("--count", type=int, default=16)
    u.set_defaults(fn=cmd_u32)

    d = sub.add_parser("dis")
    d.add_argument("file")
    d.add_argument("--at", type=lambda x: int(x, 0), required=True)
    d.add_argument("--va", type=lambda x: int(x, 0), required=True)
    d.add_argument("--count", type=int, default=32)
    d.set_defaults(fn=cmd_dis)

    s = sub.add_parser("strings")
    s.add_argument("file")
    s.add_argument("--min", type=int, default=5)
    s.add_argument("--at", type=lambda x: int(x, 0), default=0)
    s.set_defaults(fn=cmd_strings)

    fs = sub.add_parser("findstr")
    fs.add_argument("file")
    fs.add_argument("--s", required=True)
    fs.set_defaults(fn=cmd_findstr)

    b = sub.add_parser("blocks")
    b.add_argument("file")
    b.add_argument("--size", type=lambda x: int(x, 0), default=0x1000)
    b.set_defaults(fn=cmd_blocks)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
