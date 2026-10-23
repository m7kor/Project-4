#!/usr/bin/env python3
"""Audit bounded GS transfer prefixes without inferring uncaptured payloads."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(trace: str) -> dict:
    events, problems = [], []
    fields = ("dbp", "dbw", "dpsm", "direction", "x", "y", "rrw", "rrh", "copied", "total", "bytes")
    for number, line in enumerate(trace.splitlines(), 1):
        if "[gs:transfer]" not in line:
            continue
        raw = dict(re.findall(r"(\w+)=([^\s]*)", line))
        try:
            event = {name: int(raw[name], 10) for name in fields}
            event["stage"] = raw["stage"]
            if event["stage"] not in ("begin", "input"):
                raise ValueError("unknown stage")
            prefix = bytes.fromhex(raw["prefix"])
            if not 0 <= event["dbp"] <= 16383 or len(prefix) > 512 or event["bytes"] < 0:
                raise ValueError("invalid range")
            limits = {"dbw": 63, "dpsm": 63, "direction": 3, "rrw": 4095, "rrh": 4095}
            if any(not 0 <= event[name] <= maximum for name, maximum in limits.items()):
                raise ValueError("invalid register range")
            if any(event[name] < 0 for name in ("x", "y", "copied", "total")):
                raise ValueError("negative transfer state")
            if event["stage"] == "input" and len(prefix) != min(event["bytes"], 512):
                raise ValueError("incomplete prefix")
            if event["stage"] == "begin" and (event["bytes"] or prefix):
                raise ValueError("unexpected begin payload")
            event.update(line=number, prefix=prefix.hex(), prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                         payload_complete=len(prefix) == event["bytes"])
            events.append(event)
        except (ValueError, KeyError) as error:
            problems.append({"line": number, "error": str(error)})
    return {"schema": 1, "scope": "bounded transfer inputs; no completion or source-address inference",
            "usable": bool(events) and not problems, "potentially_capped": len(events) >= 32,
            "events": events, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.trace.read_text(encoding="utf-8", errors="replace"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"usable": result["usable"], "events": len(result["events"]), "potentially_capped": result["potentially_capped"]}))
    return 0 if result["usable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
