"""Contact sheet of a run's captured frames, labelled with guest vsync and time.

diagnostics/frame-<host tick>.png are captured by the runner every 120 host
ticks. This lays out up to --count of them (evenly spread, or only frames
that differ from the previous one with --changes) with the EE vsync from
state.jsonl, so a whole run can be reviewed at a glance.

    python -I tools/diagnostics/frame_contact_sheet.py RUNDIR [--count 48] [--changes] [--out sheet.png]
"""
import argparse
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageStat


def vsync_by_tick(run):
    mapping = {}
    path = run / 'diagnostics' / 'state.jsonl'
    if path.exists():
        for line in path.open(encoding='utf-8', errors='replace'):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if 'tick' in row and 'ee_vsync_tick' in row:
                mapping[row['tick']] = row['ee_vsync_tick']
    return mapping


def nearest(mapping, tick):
    if not mapping:
        return None
    key = min(mapping, key=lambda k: abs(k - tick))
    return mapping[key]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--count', type=int, default=48)
    parser.add_argument('--changes', action='store_true', help='keep only frames that differ from the last kept one')
    parser.add_argument('--columns', type=int, default=8)
    parser.add_argument('--thumb', type=int, default=200, help='thumbnail width')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()

    frames = sorted(((int(re.search(r'frame-(\d+)', p.name)[1]), p)
                     for p in (args.run / 'diagnostics').glob('frame-*.png')))
    if not frames:
        raise SystemExit('no frames captured')
    vsyncs = vsync_by_tick(args.run)
    chosen = []
    if args.changes:
        last = None
        for tick, path in frames:
            image = Image.open(path).convert('RGB').resize((64, 48))
            if last is None or sum(ImageStat.Stat(Image.blend(image, last, 0.5)).var) == 0 or \
                    sum(abs(a - b) for a, b in zip(ImageStat.Stat(image).mean, ImageStat.Stat(last).mean)) > 6:
                chosen.append((tick, path))
                last = image
        step = max(1, len(chosen) // args.count + (len(chosen) % args.count > 0))
        chosen = chosen[::step][:args.count]
    else:
        step = max(1, len(frames) / args.count)
        chosen = [frames[int(i * step)] for i in range(min(args.count, len(frames)))]

    width = args.thumb
    first = Image.open(chosen[0][1])
    height = int(width * first.height / first.width)
    label = 16
    rows = (len(chosen) + args.columns - 1) // args.columns
    sheet = Image.new('RGB', (args.columns * width, rows * (height + label)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (tick, path) in enumerate(chosen):
        image = Image.open(path).convert('RGB')
        black = max(ImageStat.Stat(image).mean) < 8
        x, y = (i % args.columns) * width, (i // args.columns) * (height + label)
        sheet.paste(image.resize((width, height)), (x, y + label))
        vsync = nearest(vsyncs, tick)
        text = f'v{vsync} {tick / 60:.0f}s' + (' BLACK' if black else '')
        draw.text((x + 3, y + 2), text, fill=(255, 90, 90) if black else (230, 230, 230))
    out = args.out or (args.run / 'diagnostics' / 'contact_sheet.png')
    sheet.save(out)
    print(f'{len(chosen)} of {len(frames)} frames -> {out}')


if __name__ == '__main__':
    main()
