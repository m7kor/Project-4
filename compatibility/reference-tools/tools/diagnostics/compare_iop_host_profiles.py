"""Compare bounded IOP host timing captures without claiming game compatibility."""
import argparse
import json
import re
from pathlib import Path


PATTERN = re.compile(
    r"window_us=(\d+) run_ee_us=(\d+) calls=(\d+) "
    r"requested_ee_cycles=(\d+) instructions=(\d+)"
)
FIELDS = ("window_us", "run_ee_us", "calls", "requested_ee_cycles", "instructions")


def read_capture(path):
    report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    rows = [dict(zip(FIELDS, map(int, match))) for match in
            PATTERN.findall((path / "stderr.txt").read_text(encoding="utf-8", errors="replace"))]
    if not rows or any(row["window_us"] <= 0 or row["calls"] <= 0 for row in rows):
        raise ValueError(f"Missing or invalid timing windows: {path}")
    first = rows[0]
    initial = rows[:10]
    return {
        "run": path.name,
        "runner_sha256": report["runner_sha256"],
        "elf_sha256": report["elf_sha256"],
        "diagnostics_requested": report["diagnostics_requested"],
        "seconds": report["seconds"],
        "timed_out": report["timed_out"],
        "fault_counts": report["fault_counts"],
        "windows": len(rows),
        "first_window": first,
        "first_window_iop_us_per_call": first["run_ee_us"] / first["calls"],
        "first_ten_iop_percent": 100 * sum(r["run_ee_us"] for r in initial) /
            sum(r["window_us"] for r in initial),
        "first_ten_requested_ee_cycles": sum(r["requested_ee_cycles"] for r in initial),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    before, after = read_capture(args.before), read_capture(args.after)
    if before["elf_sha256"] != after["elf_sha256"]:
        raise ValueError("Captures must use the same ELF")
    if before["diagnostics_requested"] != after["diagnostics_requested"]:
        raise ValueError("Diagnostic capture modes differ")
    result = {
        "before": before,
        "after": after,
        "first_window_iop_us_per_call_reduction_percent": 100 * (
            1 - after["first_window_iop_us_per_call"] / before["first_window_iop_us_per_call"]),
        "scope": "Diagnostic windows only. Replay, save, environment, cache state and "
            "guest workload must be checked separately. This is not a gameplay or whole-game speedup claim.",
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
