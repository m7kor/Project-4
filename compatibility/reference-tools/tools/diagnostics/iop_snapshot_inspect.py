#!/usr/bin/env python3
"""Disassemble a bounded window from a captured 2 MiB IOP RAM image."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bios_mine"))
from mipsdec import decode


def inspect(data: bytes, start: int, words: int) -> dict:
    if len(data) != 2 * 1024 * 1024:
        raise ValueError("snapshot must contain exactly 2 MiB of IOP RAM")
    if not 0 <= start <= 0xFFFFFFFF or not 1 <= words <= 512:
        raise ValueError("address must be uint32; words must be 1..512")
    physical = start & 0x1FFFFFFF
    if physical % 4 or physical + words * 4 > len(data):
        raise ValueError("instruction window is unaligned or outside IOP RAM")
    instructions = []
    for offset in range(0, words * 4, 4):
        pc = physical + offset
        word = struct.unpack_from("<I", data, pc)[0]
        decoded = decode(word, pc)
        instructions.append({"pc": hex(pc), "word": hex(word), "decoded": decoded})
    return {"schema": 1, "snapshot_sha256": hashlib.sha256(data).hexdigest(),
            "scope": "bounded-static-disassembly; executable ownership not inferred",
            "instructions": instructions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--start", type=lambda v: int(v, 0), required=True)
    parser.add_argument("--words", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.snapshot.open("rb") as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        report = inspect(data, args.start, args.words)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for row in report["instructions"]:
        decoded = row["decoded"]
        print(f"{int(row['pc'], 0):08x}: {int(row['word'], 0):08x}  {decoded['mnem']} {', '.join(decoded['args'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
