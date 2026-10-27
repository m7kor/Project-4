#!/usr/bin/env python3
"""Audit bounded original LIBSD import observations; never infer completion."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def summarize(lines) -> dict:
    events, problems, handlers = [], [], {}
    segment, previous_cycle = 0, None
    counts = {"registrations": 0, "transfers": 0, "initializations": 0, "quits": 0}
    for number, line in enumerate(lines, 1):
        if "[IOP sound import]" not in line:
            continue
        try:
            fields = dict(re.findall(r"(\w+)=(0x[0-9a-fA-F]+|[0-9]+)(?=\s|$)", line))
            keys = ("ordinal", "cycles", "pc", "ra", "target", "gp",
                    "a0", "a1", "a2", "a3", "a4", "a4_valid", "control")
            data = {key: int(fields[key], 0) for key in keys}
            if any(value < 0 or value > (0xFFFFFFFFFFFFFFFF if key == "cycles" else 0xFFFFFFFF)
                   for key, value in data.items()):
                raise ValueError("numeric field outside guest range")
            if data["a4_valid"] not in (0, 1) or data["control"] not in (0, 1):
                raise ValueError("invalid boolean or interrupt control")
            ordinal, cycle = data["ordinal"], data["cycles"]
            if ordinal not in (2, 4, 17, 18, 26, 27):
                raise ValueError("unsupported traced ordinal")
            if ordinal == 26 and data["a0"] not in (0, 1):
                raise ValueError("invalid transfer handler core")
            if ordinal == 17 and not data["a4_valid"]:
                raise ValueError("voice transfer size was not captured")
            if previous_cycle is not None and cycle < previous_cycle:
                segment += 1
                handlers.clear()
            previous_cycle = cycle
            event = {"line": number, "segment": segment, **data}
            if ordinal in (2, 4):
                # Entry alone cannot prove completion of reinitialization.
                # Invalidate old candidates rather than claim known zero slots.
                handlers.clear()
                event.update(kind="library-init" if ordinal == 4 else "library-quit")
                counts["initializations" if ordinal == 4 else "quits"] += 1
            elif ordinal == 26:
                core = data["a0"]
                event.update(kind="transfer-handler-registration", core=core,
                             previous_observed_handler=handlers.get(core))
                handlers[core] = {"function": data["a1"], "argument": data["a2"], "line": number}
                counts["registrations"] += 1
            elif ordinal == 27:
                event.update(kind="spu-irq-handler-registration")
                counts["registrations"] += 1
            else:
                core = data["a0"] & 1
                event.update(kind="voice-transfer" if ordinal == 17 else "block-transfer",
                             core=core, last_observed_transfer_handler=handlers.get(core))
                counts["transfers"] += 1
            events.append(event)
        except (KeyError, ValueError) as exc:
            problems.append({"line": number, "reason": str(exc)})
    return {"schema": 1, "scope": "bounded-original-libsd-import-observations",
            "usable": bool(events) and not problems, "counts": counts,
            "potentially_capped": (counts["registrations"] + counts["initializations"] + counts["quits"] >= 64
                                   or counts["transfers"] >= 128),
            "events": events, "problems": problems,
            "limitations": "Import entry is not proof of return, DMA completion, or successful registration. Last observed handler is a candidate from captured calls, not verified live RAM. Direct calls and capped events can be missing; cycle regressions begin new segments."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.trace.open(encoding="utf-8", errors="replace") as stream:
        report = summarize(stream)
    report["trace_sha256"] = hashlib.sha256(args.trace.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("usable", "counts", "potentially_capped", "problems")}))
    return int(not report["usable"])


if __name__ == "__main__":
    raise SystemExit(main())
