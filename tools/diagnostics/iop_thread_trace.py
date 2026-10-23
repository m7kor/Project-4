"""Summarize observed IOP thread snapshots; absence is not proof of execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


THREAD = re.compile(r"\{id=(\d+) ([^}]+)\}")
FIELD = re.compile(r"(\w+)=(0x[0-9a-fA-F]+|\d+)")


def summarize(path: Path, thread_id: int) -> dict:
    digest = hashlib.sha256()
    rows = []
    previous = None
    snapshots = 0
    with path.open("rb") as source:
        for number, raw in enumerate(source, 1):
            digest.update(raw)
            line = raw.decode("utf-8", errors="replace")
            if "[IOP threads]" not in line:
                continue
            for match in THREAD.finditer(line):
                if int(match[1]) != thread_id:
                    continue
                snapshots += 1
                fields = {key: int(value, 16 if value.startswith("0x") else 10)
                          for key, value in FIELD.findall(match[2])}
                if fields != previous:
                    rows.append({"line": number, "fields": fields})
                    previous = fields
    return {"schema": 1, "log": str(path.resolve()), "log_sha256": digest.hexdigest(),
            "thread_id": thread_id, "observed_snapshots": snapshots, "changes": rows,
            "scope": "sampled thread states only; repeated PC does not establish a loop or deadlock",
            "game_compatibility": "unverified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--thread", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.thread <= 0 or args.out.suffix.lower() != ".json" or args.out.resolve() == args.log.resolve():
        parser.error("positive thread id and a separate .json output are required")
    report = summarize(args.log, args.thread)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Snapshots: {report['observed_snapshots']}; changes: {len(report['changes'])}")
    if report["changes"]:
        print("Last observed state:", report["changes"][-1]["fields"])
    return 0 if report["observed_snapshots"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
