"""Summarise a run's screen timeline: PICTURE/BLACK spans by EE vsync tick.

Frames are diagnostics/frame-<host tick>.png and state.jsonl maps host ticks to
EE vsync ticks. Prints each span and, with --expect-picture-after N, exits 0
only when a PICTURE span starts after EE tick N (for example the RE4 car
cutscene after the intro movie, around tick 7600).

    python -I tools/diagnostics/run_milestones.py RUNDIR [--expect-picture-after 7000]
"""
import argparse
import bisect
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--expect-picture-after', type=int)
    parser.add_argument('--black-below', type=float, default=4.0)
    args = parser.parse_args()
    from PIL import Image, ImageStat
    ticks, ee = [], []
    for line in (args.run / 'diagnostics' / 'state.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ticks.append(row['tick'])
        ee.append(row['ee_vsync_tick'])
    frames = sorted((args.run / 'diagnostics').glob('frame-*.png'), key=lambda p: int(p.stem.split('-')[1]))
    spans = []
    for frame in frames:
        tick = int(frame.stem.split('-')[1])
        i = max(0, bisect.bisect_right(ticks, tick) - 1)
        state = 'BLACK' if ImageStat.Stat(Image.open(frame).convert('L')).mean[0] < args.black_below else 'PICTURE'
        if not spans or spans[-1][0] != state:
            spans.append([state, ee[i] if ee else tick, ee[i] if ee else tick])
        else:
            spans[-1][2] = ee[i] if ee else tick
    for state, first, last in spans:
        print(f'{state:7s} ee {first:6d} .. {last:6d}')
    if args.expect_picture_after is not None:
        ok = any(s == 'PICTURE' and first > args.expect_picture_after for s, first, _ in spans)
        print('milestone:', 'PASS' if ok else 'FAIL')
        return 0 if ok else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
