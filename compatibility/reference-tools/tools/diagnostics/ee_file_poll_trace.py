"""Summarize selected RE4 file-poll calls without inferring completion from yield."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

FIELDS = re.compile(r"\b(target|source|pc|v0|a[0-3]|returned)=(0x[0-9a-fA-F]+|[01])\b")
BYTES = re.compile(r"\bbytes([0-3])=([0-9a-fA-F]+)\b")
MEMORY = re.compile(r"\b(mem_[a-zA-Z0-9_]+)=([0-9a-fA-F]+)\b")
POLLS = {0x1B4618, 0x1B3770, 0x1B3BE0, 0x1B4558}


def summarize(path: Path) -> dict:
    raw = path.read_bytes()
    observations = []
    armed = []
    malformed_snapshots = 0
    for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        if line.startswith("[EE trace:armed]"):
            armed.append({"line": number, "message": line})
        if not line.startswith(("[EE call enter]", "[EE call leave]")):
            continue
        fields = {name: int(value, 0) for name, value in FIELDS.findall(line)}
        row = {"line": number, "phase": "enter" if "call enter]" in line else "leave", **fields}
        snapshots = {}
        for index, value in BYTES.findall(line):
            try:
                snapshots[int(index)] = bytes.fromhex(value)
            except ValueError:
                malformed_snapshots += 1
        row["argument_snapshots"] = {str(index): data.hex() for index, data in snapshots.items()}
        row["memory_snapshots"] = {}
        for name, value in MEMORY.findall(line):
            try:
                row["memory_snapshots"][name] = bytes.fromhex(value).hex()
            except ValueError:
                malformed_snapshots += 1
        if fields.get("target") in POLLS and 0 in snapshots and len(snapshots[0]) >= 6:
            data = snapshots[0]
            row["object_header"] = {
                "address": fields.get("a0"),
                "word_0": hex(struct.unpack_from("<I", data)[0]),
                "type_at_4": data[4], "state_at_5": data[5],
                "snapshot_hex": data.hex(),
            }
        observations.append(row)
    return {
        "schema": 1, "log": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "Only selected dispatch entries/leaves. returned=0 is a yield, not a failed read. A later resume need not produce a matching leave. File-state bits are raw observations, not success labels.",
        "arm_events": armed, "observed_entries": sum(x["phase"] == "enter" for x in observations),
        "malformed_snapshots": malformed_snapshots,
        "shared_trace_cap": 256,
        "entries_at_shared_cap": sum(x["phase"] == "enter" for x in observations) >= 256,
        "targets": dict(Counter(hex(x["target"]) for x in observations if x["phase"] == "enter")),
        "observations": observations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.suffix.lower() != ".json" or args.out.resolve() == args.log.resolve():
        parser.error("output must be a separate JSON file")
    report = summarize(args.log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("observed_entries", "targets")}))
    if not report["observed_entries"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
