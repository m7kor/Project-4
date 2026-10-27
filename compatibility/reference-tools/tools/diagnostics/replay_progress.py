"""Audit EE-timed input replay coverage without claiming menu/gameplay success."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(capture: Path, fixture: Path) -> dict:
    with fixture.open("rb") as stream:
        payload = stream.read(128 * 1024 + 1)
    if len(payload) > 128 * 1024:
        raise ValueError("replay fixture exceeds runtime size limit")
    lines = payload.decode("ascii").splitlines()
    if not lines or lines[0] != "begin,end,buttons,lx,ly,rx,ry":
        raise ValueError("invalid replay header")
    events = []
    for line in lines[1:]:
        if not line:
            continue
        fields = line.split(",")
        if len(fields) != 7 or any(not re.fullmatch(r"[0-9]+", value) for value in fields):
            raise ValueError("invalid replay row")
        begin, end, buttons, *axes = map(int, fields)
        if (len(events) >= 1024 or not begin < end <= 0xFFFFFFFFFFFFFFFF
                or buttons > 65535 or any(value > 255 for value in axes)
                or events and begin < events[-1]["end"]):
            raise ValueError("invalid replay bounds or overlapping intervals")
        events.append({"begin": begin, "end": end, "buttons": buttons,
                       "button_transition_seen": False})
    if not events:
        raise ValueError("empty replay fixture")
    report_path = capture / "report.json"
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    state = report.get("diagnostics", {}).get("last_state") or {}
    last_tick = state.get("ee_vsync_tick")
    if not isinstance(last_tick, int) or isinstance(last_tick, bool) or last_tick < 0:
        last_tick = None
    log_hash = hashlib.sha256()
    with (capture / "stderr.txt").open("rb") as stream:
        for line in stream:
            log_hash.update(line)
            match = re.search(rb"\[native pad replay\] tick=([0-9]+) buttons=0x([0-9a-fA-F]+)", line)
            if not match:
                continue
            tick, buttons = int(match[1]), int(match[2], 16)
            last_tick = max(last_tick or 0, tick)
            for event in events:
                if event["begin"] <= tick < event["end"] and buttons == event["buttons"]:
                    event["button_transition_seen"] = True
    for event in events:
        event["interval_end_reached"] = last_tick is not None and last_tick >= event["end"]
    return {"schema": 1, "fixture_sha256": hashlib.sha256(payload).hexdigest(),
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "stderr_sha256": log_hash.hexdigest(), "last_observed_ee_tick": last_tick,
            "events": events, "all_interval_ends_reached": all(e["interval_end_reached"] for e in events),
            "scope": "EE ticks and logged button transitions only. Reaching an interval end does not prove it was sampled; a transition does not prove the game accepted the action. Host frame ticks are not replay ticks."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(args.capture, args.fixture)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"last_observed_ee_tick": result["last_observed_ee_tick"],
                      "all_interval_ends_reached": result["all_interval_ends_reached"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
