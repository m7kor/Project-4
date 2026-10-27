"""Watch running ps2l runs live: one line per screen state change, fault or end.

Follows the newest run directory under artifacts/runs, or every --run given
(each line is prefixed with the run's label), classifying the newest
diagnostics frame as BLACK or PICTURE, and reports the EE vsync tick, disc
reads (sceCdRV) and IPU command counters from state.jsonl. Also reports
runtime exceptions and missing native targets, and a STALL line when disc
reads and IPU commands stop for --stall-ticks vsyncs. --newest N follows the
N newest runs. Single process, so it stays usable when the shell cannot fork.

    python -I tools/diagnostics/live_watch.py [--run DIR ...] [--newest N] [--interval 15]
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

FAULT = re.compile(rb'missing-target|runtime exception|Unhandled|fatal|Access violation', re.I)
READ = re.compile(rb'ordinal=63 .*?a0=(0x[0-9a-f]+) a1=(0x[0-9a-f]+)')
LEGACY = re.compile(rb'PS2X_FLOAT_LEGACY=(0x[0-9a-f]+)')


def mean_luma(path):
    from PIL import Image, ImageStat
    return ImageStat.Stat(Image.open(path).convert('L')).mean[0]


def last_line(path):
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().splitlines()
            return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError, IndexError):
        return None


class Watch:
    def __init__(self, run, stall_ticks):
        self.run = run
        self.label = run.name[9:15]
        self.stall_ticks = stall_ticks
        self.state = None
        self.offsets = {'stderr.txt': 0, 'stdout.txt': 0}
        self.last_read = None
        self.reads = 0
        self.progress_key = None
        self.progress_tick = None
        self.stalled = False
        self.done = False

    def say(self, text):
        print(f'[{self.label}] {text}', flush=True)

    def poll(self):
        for name in self.offsets:
            try:
                with open(self.run / name, 'rb') as f:
                    f.seek(self.offsets[name])
                    data = f.read()
                    self.offsets[name] += len(data)
            except OSError:
                continue
            for line in data.splitlines():
                if FAULT.search(line):
                    self.say('FAULT ' + line[:220].decode('latin-1'))
                if m := LEGACY.search(line):
                    self.label += f'/legacy{m[1].decode()}'
                if m := READ.search(line):
                    self.reads += 1
                    self.last_read = (int(m[1], 16), int(m[2], 16))
        frames = sorted((self.run / 'diagnostics').glob('frame-*.png'), key=lambda p: int(p.stem.split('-')[1]))
        snapshot = last_line(self.run / 'diagnostics' / 'state.jsonl')
        tick = snapshot['ee_vsync_tick'] if snapshot else None
        if frames:
            try:
                now = 'BLACK' if mean_luma(frames[-1]) < 4 else 'PICTURE'
            except Exception:
                now = self.state
            if now != self.state:
                extra = f' ipu_cmds={snapshot.get("ipu_cmds")}' if snapshot else ''
                self.say(f'screen={now} ee={tick} reads={self.reads} last_read={self.last_read}{extra}')
                self.state = now
        if snapshot:
            key = (self.reads, snapshot.get('ipu_cmds'))
            if key != self.progress_key:
                self.progress_key, self.progress_tick, self.stalled = key, tick, False
            elif not self.stalled and tick - self.progress_tick >= self.stall_ticks:
                self.say(f'STALL ee={tick}: no disc reads or IPU commands since ee={self.progress_tick} '
                         f'(last_read={self.last_read}, screen={self.state})')
                self.stalled = True
        if (self.run / 'report.json').exists():
            report = json.loads((self.run / 'report.json').read_text(encoding='utf-8'))
            self.say(f'run ended: {report.get("result")} {report.get("seconds")}')
            self.done = True


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', type=Path, action='append')
    parser.add_argument('--newest', type=int, default=1)
    parser.add_argument('--root', type=Path, default=Path('artifacts/runs'))
    parser.add_argument('--interval', type=float, default=15)
    parser.add_argument('--stall-ticks', type=int, default=900)
    args = parser.parse_args()
    runs = args.run
    while not runs:
        found = sorted(p for p in args.root.iterdir() if p.is_dir() and p.name[:4].isdigit())
        runs = found[-args.newest:] if found else None
        if not runs:
            time.sleep(args.interval)
    watches = [Watch(run, args.stall_ticks) for run in runs]
    for watch in watches:
        watch.say(f'watching {watch.run.name}')
    while not all(w.done for w in watches):
        for watch in watches:
            if not watch.done:
                watch.poll()
        time.sleep(args.interval)
    return 0


if __name__ == '__main__':
    sys.exit(main())
