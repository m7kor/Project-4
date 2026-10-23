"""Measure changes in captured images against recorded host time.

Sparse captures prove sampled changes/freezes; they cannot measure every-frame FPS.
Existing image hashes are consumed without altering images or game state.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def inspect(run, first_tick, maximum_streak, first_ee_tick=None):
    audit_path = run / 'diagnostics/frame-audit.json'
    state_path = run / 'diagnostics/state.jsonl'
    audit = json.loads(audit_path.read_text())
    states = {}
    for line in state_path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row['tick'] in states:
                raise ValueError('Duplicate state tick')
            states[row['tick']] = row
    samples = []
    for image in audit['frames']:
        match = re.fullmatch(r'frame-(\d+)\.png', image['file'])
        if not match:
            raise ValueError('Unexpected image filename')
        tick = int(match[1])
        if tick < first_tick:
            continue
        if tick not in states:
            raise ValueError(f'Missing timestamp for image tick {tick}')
        if first_ee_tick is not None and states[tick]['ee_vsync_tick'] < first_ee_tick:
            continue
        if not re.fullmatch(r'[0-9a-f]{64}', image['rgb_sha256']):
            raise ValueError('Invalid decoded RGB hash')
        samples.append({'tick': tick, 'seconds': states[tick]['elapsed_seconds'],
                        'hash': image['rgb_sha256'], 'black': image['all_black']})
    samples.sort(key=lambda sample: sample['tick'])
    if len(samples) < 3 or samples[-1]['seconds'] - samples[0]['seconds'] < 10:
        raise ValueError('Require at least three timestamped images spanning ten seconds')
    longest = 0.0
    changes = 0
    streak_start = samples[0]['seconds']
    for previous, current in zip(samples, samples[1:]):
        if current['tick'] == previous['tick'] or current['seconds'] <= previous['seconds']:
            raise ValueError('Image timestamps must increase')
        if current['hash'] == previous['hash']:
            longest = max(longest, current['seconds'] - streak_start)
        else:
            changes += 1
            streak_start = current['seconds']
    black = sum(sample['black'] for sample in samples)
    issues = []
    if not changes:
        issues.append('All sampled images are identical')
    if longest >= maximum_streak:
        issues.append('Identical image streak exceeds the allowed window for this active scene')
    if black == len(samples):
        issues.append('All sampled images are black')
    return {'schema': 1, 'scope': 'timestamped sparse image samples, not every-frame cadence or game speed',
            'run': str(run.resolve()), 'first_tick': first_tick, 'first_ee_vsync': first_ee_tick,
            'audit_sha256': hashlib.sha256(audit_path.read_bytes()).hexdigest(),
            'state_sha256': hashlib.sha256(state_path.read_bytes()).hexdigest(),
            'samples': len(samples), 'duration_seconds': samples[-1]['seconds'] - samples[0]['seconds'],
            'sampled_image_changes': changes, 'distinct_sampled_images': len({s['hash'] for s in samples}),
            'black_samples': black, 'longest_identical_sample_streak_seconds': longest,
            'maximum_identical_streak_seconds': maximum_streak,
            'issues': issues, 'passed': not issues,
            'natural_game_speed_models_audio_save': 'unverified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--from-tick', type=int, default=0, help='Host capture tick')
    parser.add_argument('--from-ee-vsync', type=int, help='Guest EE checkpoint matched through state samples')
    parser.add_argument('--max-identical-seconds', type=float, default=10,
                        help='Scene-specific limit; do not apply an active-scene limit to a stationary menu')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if (args.out.exists() or args.from_tick < 0 or args.max_identical_seconds <= 0
            or (args.from_ee_vsync is not None and args.from_ee_vsync < 0)):
        parser.error('Use a new report path and nonnegative first tick')
    try:
        result = inspect(args.run, args.from_tick, args.max_identical_seconds, args.from_ee_vsync)
    except (OSError, ValueError, KeyError) as error:
        result = {'schema': 1, 'passed': False, 'issues': [str(error)]}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
