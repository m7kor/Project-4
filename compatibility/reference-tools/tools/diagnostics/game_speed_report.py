"""Report real emulation speed from monotonic capture timestamps.

Older captures supply host ratios only. report.json can supply a whole-run
wall-speed lower bound, including startup, but cannot date individual samples.
"""
import argparse
import json
import math
from pathlib import Path


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def summarize(run, window=600, vsync_hz=60000 / 1001):
    if window <= 0 or not number(vsync_hz) or vsync_hz <= 0:
        raise ValueError('window and vsync_hz must be positive')
    samples = []
    malformed = 0
    with open(run / 'diagnostics' / 'state.jsonl', encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(row, dict) or not all(number(row.get(k)) and row[k] >= 0 for k in ('tick', 'ee_vsync_tick')):
                malformed += 1
                continue
            samples.append(row)
    if len(samples) < 2:
        raise ValueError('not enough samples')
    timed = all(number(s.get('elapsed_seconds')) and s['elapsed_seconds'] >= 0 for s in samples)
    for a, b in zip(samples, samples[1:]):
        if b['tick'] <= a['tick'] or b['ee_vsync_tick'] < a['ee_vsync_tick']:
            raise ValueError('capture counters are not monotonic')
        if timed and b['elapsed_seconds'] <= a['elapsed_seconds']:
            raise ValueError('capture elapsed time is not increasing')

    def interval(a, b):
        ticks = b['tick'] - a['tick']
        out = {'tick': b['tick'], 'vsync': b['ee_vsync_tick'],
               'host_ratio': (b['ee_vsync_tick'] - a['ee_vsync_tick']) / ticks}
        if timed:
            seconds = b['elapsed_seconds'] - a['elapsed_seconds']
            out.update(elapsed_seconds=b['elapsed_seconds'],
                       wall_speed=(b['ee_vsync_tick'] - a['ee_vsync_tick']) / (seconds * vsync_hz))
            # The GPU backend leaves this legacy CPU counter at zero. Zero
            # deltas do not certify a frozen presentation stream.
            if all(number(s.get('display_flips')) for s in (a, b)) and b['display_flips'] > a['display_flips']:
                out['display_fps'] = (b['display_flips'] - a['display_flips']) / seconds
        return out

    windows = []
    last = samples[0]
    for row in samples[1:]:
        if row['tick'] - last['tick'] >= window:
            windows.append(interval(last, row))
            last = row
    result = {'clock': 'monotonic' if timed else 'host_ticks', 'samples': len(samples),
              'malformed_rows': malformed, 'vsync_hz': vsync_hz, 'windows': windows,
              'overall': interval(samples[0], samples[-1])}
    if not timed and (run / 'report.json').exists():
        report = json.loads((run / 'report.json').read_text(encoding='utf-8'))
        seconds = report.get('seconds') if isinstance(report, dict) else None
        if number(seconds) and seconds > 0:
            result['whole_run_wall_speed_lower_bound'] = samples[-1]['ee_vsync_tick'] / (seconds * vsync_hz)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--window', type=int, default=600, help='host ticks between window endpoints')
    parser.add_argument('--vsync-hz', type=float, default=60000 / 1001, help='guest field rate (50 for PAL)')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        report = summarize(args.run, args.window, args.vsync_hz)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    if args.json:
        print(json.dumps(report, indent=2))
        return
    if report['clock'] == 'monotonic':
        print(' wall_s   vsync   real speed   display fps')
        for row in report['windows']:
            fps = f"{row['display_fps']:.1f}" if 'display_fps' in row else 'n/a'
            print(f"{row['elapsed_seconds']:7.1f} {row['vsync']:7.0f} {row['wall_speed']:12.2f} {fps:>13}")
        print(f"overall sampled wall speed {report['overall']['wall_speed']:.2f}")
    else:
        print('No elapsed timestamps: host ratios below are not real-time speed.')
        print(' host_tick   vsync   host ratio')
        for row in report['windows']:
            print(f"{row['tick']:10.0f} {row['vsync']:7.0f} {row['host_ratio']:12.2f}")
        if 'whole_run_wall_speed_lower_bound' in report:
            print(f"whole-run wall speed >= {report['whole_run_wall_speed_lower_bound']:.2f} (includes startup)")


if __name__ == '__main__':
    main()
