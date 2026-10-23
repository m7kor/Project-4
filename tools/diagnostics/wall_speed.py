"""Real (wall-clock) emulation speed of the newest run, sampled live.

game_speed_report.py divides by host present ticks, which follow the emulation
and can hide regressions. This samples the last guest vsync of the running
game every --interval seconds against the real clock (1.0 = full speed).

    python -I tools/diagnostics/wall_speed.py [--run RUNDIR] [--interval 10] [--samples 0]
"""
import argparse
import json
import time
from pathlib import Path


def last_vsync(state):
    try:
        with open(state, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)['ee_vsync_tick']
        except (ValueError, KeyError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run', type=Path)
    ap.add_argument('--root', type=Path, default=Path('artifacts/runs'))
    ap.add_argument('--interval', type=float, default=10.0)
    ap.add_argument('--samples', type=int, default=0, help='stop after N rows (0 = until the run stops)')
    args = ap.parse_args()
    run = args.run or max(args.root.iterdir(), key=lambda p: p.name)
    state = run / 'diagnostics' / 'state.jsonl'
    print(f'run {run.name}', flush=True)
    previous = (time.monotonic(), last_vsync(state))
    rows = 0
    while args.samples == 0 or rows < args.samples:
        time.sleep(args.interval)
        now, vsync = time.monotonic(), last_vsync(state)
        if vsync is None or previous[1] is None:
            previous = (now, vsync)
            continue
        if vsync == previous[1] and (run / 'report.json').exists():
            print('run ended', flush=True)
            return
        speed = (vsync - previous[1]) / ((now - previous[0]) * 59.94)
        print(f'vsync {vsync:7d}  real speed {speed:5.2f}', flush=True)
        previous = (now, vsync)
        rows += 1


if __name__ == '__main__':
    main()
