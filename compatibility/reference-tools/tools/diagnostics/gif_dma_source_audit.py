"""Validate bounded DMA source spans; this does not prove transfer completion."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(trace: str) -> dict:
    events, problems, seen = [], [], set()
    for number, line in enumerate(trace.splitlines(), 1):
        if "[GIF DMA source]" not in line:
            continue
        fields = dict(re.findall(r"(\w+)=([^\s]*)", line))
        try:
            event = {key: int(fields[key]) for key in
                     ("index", "tag", "id", "source", "scratch", "bytes", "chain_offset")}
            event["stage"] = fields["stage"]
            if event["stage"] not in ("chain", "linear") or event["scratch"] not in (0, 1):
                raise ValueError("invalid stage or memory kind")
            limit = 16384 if event["scratch"] else 32 * 1024 * 1024
            if not 0 <= event["source"] < limit or not 0 < event["bytes"] <= limit - event["source"]:
                raise ValueError("source span outside selected memory")
            if not 0 <= event["tag"] <= 0xffffffff or not 0 <= event["id"] <= 7:
                raise ValueError("invalid DMA tag")
            if not 0 <= event["index"] < 1024 or event["index"] in seen or event["chain_offset"] < 0:
                raise ValueError("invalid or duplicate record index")
            if event["stage"] == "linear" and (event["tag"] or event["id"] or event["chain_offset"]):
                raise ValueError("unexpected chain metadata on linear span")
            prefix = bytes.fromhex(fields["prefix"])
            if len(prefix) != min(64, event["bytes"]):
                raise ValueError("incomplete prefix")
            event.update(line=number, prefix=prefix.hex(), prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                         captured_whole_span=len(prefix) == event["bytes"])
            events.append(event)
            seen.add(event["index"])
        except (KeyError, ValueError) as error:
            problems.append({"line": number, "error": str(error)})
    return {"schema": 1, "scope": "bounded source spans before copy; no completion or stable later-memory claim",
            "usable": bool(events) and not problems, "potentially_capped": len(events) == 1024 or
            "[GIF DMA source trace capped]" in trace, "events": events, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.trace.read_text(encoding="utf-8", errors="replace"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"usable": result["usable"], "events": len(result["events"]),
                      "potentially_capped": result["potentially_capped"]}))
    return 0 if result["usable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
