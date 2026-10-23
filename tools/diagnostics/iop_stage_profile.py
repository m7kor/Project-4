"""Summarize sampled IOP stages; timing includes probe cost, not all execution."""
import argparse
import json
import re
from pathlib import Path

STAGES = ("rpc_ns", "sound_ns", "trace_ns", "interrupts_ns", "timers_ns",
          "scheduler_ns", "work_ns", "final_sound_ns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = []
    for line in args.log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[IOP stage profile]" not in line:
            continue
        row = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)}
        if any(k not in row for k in (*STAGES, "samples", "period", "idle", "ready", "cycles")):
            raise ValueError("Incomplete stage profile row")
        if row["period"] != 1024 or row["samples"] <= 0:
            raise ValueError("Unexpected sampling period or count")
        rows.append(row)
    if not rows:
        raise ValueError("No stage profile rows")
    totals = {k: sum(r[k] for r in rows) for k in STAGES}
    measured = sum(totals.values())
    if not measured:
        raise ValueError("No measured stage duration")
    result = {
        "rows": len(rows), "samples": sum(r["samples"] for r in rows),
        "sampled_idle_iterations": sum(r["idle"] for r in rows),
        "sampled_ready_iterations": sum(r["ready"] for r in rows),
        "sampled_stage_nanoseconds": totals,
        "sampled_stage_percent": {k: 100 * v / measured for k, v in totals.items()},
        "first_row": rows[0],
        "scope": "One call per 1024, bounded rows. Includes timer/probe overhead and "
            "can miss infrequent work. Not a whole-run cost or game compatibility claim.",
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
