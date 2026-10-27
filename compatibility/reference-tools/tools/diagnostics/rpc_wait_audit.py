#!/usr/bin/env python3
"""Summarize completed leaf calls and reply flags; yields never count as returns."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

FIELDS = re.compile(r"\b([a-zA-Z0-9_]+)=([^\s]+)")


def summarize(lines, target: int, source: int, return_pc: int, memory: int, offsets: list[int]) -> dict:
    if not offsets or any(i < 0 or i >= 64 for i in offsets):
        raise ValueError("reply offsets must be in the captured 64-byte window")
    counts = Counter()
    values, flags = Counter(), Counter()
    key = f"mem_{memory:x}"
    for line in lines:
        if not line.startswith(("[EE call enter]", "[EE call leave]")):
            continue
        if len(line) > 16384:
            counts["malformed"] += 1
            continue
        fields = dict(FIELDS.findall(line))
        try:
            if int(fields["target"], 0) != target or int(fields["source"], 0) != source:
                continue
            if line.startswith("[EE call enter]"):
                counts["entries"] += 1
                continue
            if int(fields["pc"], 0) != return_pc:
                counts["nonreturn_leaves"] += 1
                continue
            value = int(fields["v0"], 0)
            counts["completed_leaf_returns"] += 1
            values[f"0x{value:x}"] += 1
            payload = bytes.fromhex(fields[key])
            if len(payload) != 64:
                raise ValueError("incomplete memory window")
            flags["/".join(f"{payload[i]:02x}" for i in offsets)] += 1
        except (KeyError, ValueError):
            counts["malformed"] += 1
    return {"schema": 1, "scope": "bounded-leaf-call-observations",
            "target": hex(target), "source": hex(source), "return_pc": hex(return_pc),
            "memory": hex(memory), "byte_offsets": offsets, "counts": dict(counts),
            "return_values": dict(values), "reply_flag_patterns": dict(flags),
            "usable": bool(flags) and not counts["malformed"],
            "limitations": "Caller must establish a leaf and its genuine return PC. Trace caps and missing observations do not prove absence. Flags require game-specific interpretation; no gameplay verdict."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    for name in ("target", "source", "return-pc", "memory"):
        parser.add_argument(f"--{name}", type=lambda v: int(v, 0), required=True)
    parser.add_argument("--offsets", type=lambda v: [int(i, 0) for i in v.split(",")], required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.trace.open(encoding="utf-8", errors="replace") as stream:
            report = summarize(stream, args.target, args.source, args.return_pc, args.memory, args.offsets)
        digest = hashlib.sha256()
        with args.trace.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        report["trace_sha256"] = digest.hexdigest()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("usable", "counts", "return_values", "reply_flag_patterns")}))
    return int(not report["usable"])


if __name__ == "__main__":
    raise SystemExit(main())
