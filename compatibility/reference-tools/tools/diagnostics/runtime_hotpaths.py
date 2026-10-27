"""Compare two procedural runtime benchmark executables, never game FPS."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def measure(executable: Path, mode: str) -> dict:
    result = subprocess.run([str(executable), mode], capture_output=True,
                            text=True, timeout=60, check=True)
    record = json.loads(result.stdout.strip().splitlines()[-1])
    if (record["mode"] != mode or record["operations"] <= 0
            or not math.isfinite(record["milliseconds"])
            or record["milliseconds"] <= 0):
        raise ValueError(f"invalid benchmark output from {executable}: {record}")
    return record


def fingerprint(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 3:
        parser.error("at least three rounds are required")
    executables = {name: getattr(args, name).absolute() for name in ("before", "after")}
    output = args.out.resolve()
    if output in executables.values():
        parser.error("report must not overwrite a benchmark executable")
    identities = {name: fingerprint(path) for name, path in executables.items()}
    samples, comparison = [], []
    for mode in ("xgkick", "vif1", "timers"):
        # Warm both processes and alternate order to reduce temporal bias.
        for path in executables.values():
            measure(path, mode)
        groups = {"before": [], "after": []}
        for round_index in range(args.rounds):
            order = ("before", "after") if round_index % 2 == 0 else ("after", "before")
            for name in order:
                record = measure(executables[name], mode)
                groups[name].append(record)
                samples.append({"variant": name, "round": round_index, **record})
        all_records = groups["before"] + groups["after"]
        if len({(r["operations"], r["checksum"]) for r in all_records}) != 1:
            raise ValueError(f"operation count or correctness checksum differs in {mode}")
        before = statistics.median(r["milliseconds"] for r in groups["before"])
        after = statistics.median(r["milliseconds"] for r in groups["after"])
        comparison.append({"mode": mode, "before_median_ms": before, "after_median_ms": after,
                           "cost_reduction_percent": 100 * (1 - after / before),
                           "operations": all_records[0]["operations"],
                           "checksum": all_records[0]["checksum"], "checksums_match": True})
    if identities != {name: fingerprint(path) for name, path in executables.items()}:
        raise ValueError("benchmark executable changed during measurement")
    report = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(),
              "scope": "procedural-runtime-operations", "game_fps_measured": False,
              "rounds": args.rounds, "executables": identities,
              "comparison": comparison, "samples": samples}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in comparison:
        print(f"{row['mode']}: {row['before_median_ms']:.3f} -> "
              f"{row['after_median_ms']:.3f} ms ({row['cost_reduction_percent']:.2f}% lower cost)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
