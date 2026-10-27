"""Require consumed FINISH at a scene checkpoint and continued GIF activity.

This checks one captured transition, not whole-game compatibility or frame rate.
No guest memory, executable, or card is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def inspect(run, checkpoint, tail_seconds):
    log = run / 'stderr.txt'
    state = run / 'diagnostics/state.jsonl'
    rows = [json.loads(line) for line in state.read_text().splitlines() if line.strip()]
    fences = []
    for number, line in enumerate(log.read_text(errors='replace').splitlines(), 1):
        if '[GIF fence after]' not in line:
            continue
        fields = dict(re.findall(r'(\w+)=(\d+)', line))
        if not {'index', 'vsync', 'qwc', 'masked', 'csr'} <= fields.keys():
            raise ValueError(f'Malformed fence observation at line {number}')
        fences.append({key: int(value) for key, value in fields.items()} | {'line': number})
    if not rows or not fences:
        raise ValueError('Missing state samples or post-submission FINISH evidence')
    if any(b['elapsed_seconds'] < a['elapsed_seconds'] or b['tick'] < a['tick']
           for a, b in zip(rows, rows[1:])):
        raise ValueError('State samples are not ordered')
    # Runtime fence records use EeScheduler::currentVSyncTick(), not the
    # independently advancing host presentation/capture counter.
    later = [row for row in rows if row['ee_vsync_tick'] >= checkpoint]
    if not later or later[-1]['elapsed_seconds'] - later[0]['elapsed_seconds'] < tail_seconds:
        raise ValueError('Insufficient observation time after the requested checkpoint')
    tail = [row for row in later if row['elapsed_seconds'] >= later[-1]['elapsed_seconds'] - tail_seconds]
    if len(tail) < 3:
        raise ValueError('Insufficient tail samples')
    consumed = [f for f in fences if f['vsync'] >= checkpoint and f['qwc'] == 0 and f['csr'] & 2]
    pending = [f for f in fences if f['vsync'] >= checkpoint and f['qwc'] == 0 and not f['csr'] & 2]
    activity = tail[-1]['gif'] - tail[0]['gif']
    waits = sum(row['pc'] == 0x251908 for row in tail)
    issues = []
    if not consumed:
        issues.append('No consumed FINISH observed at or beyond the checkpoint')
    if activity <= 0:
        issues.append('GIF counter did not advance during the final observation window')
    if waits >= 3 and activity <= 0:
        issues.append('Repeated original FINISH-wait PC with no GIF progress')
    return {'schema': 1, 'scope': 'one traced FINISH checkpoint and subsequent GIF activity only',
            'run': str(run.resolve()), 'checkpoint_ee_vsync': checkpoint,
            'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
            'state_sha256': hashlib.sha256(state.read_bytes()).hexdigest(),
            'consumed_after_checkpoint': len(consumed), 'pending_after_checkpoint': pending,
            'last_consumed': consumed[-1] if consumed else None,
            'tail_seconds_observed': tail[-1]['elapsed_seconds'] - tail[0]['elapsed_seconds'],
            'tail_gif_delta': activity, 'tail_finish_wait_samples': waits,
            'issues': issues, 'passed': not issues,
            'visual_gameplay_audio_save_compatibility': 'unverified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--checkpoint', type=int, default=6130)
    parser.add_argument('--tail-seconds', type=float, default=20)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.checkpoint < 0 or args.tail_seconds < 10:
        parser.error('Use a new report path, nonnegative checkpoint and at least 10 seconds of tail observation')
    try:
        result = inspect(args.run, args.checkpoint, args.tail_seconds)
    except (OSError, ValueError, KeyError) as error:
        result = {'schema': 1, 'scope': 'one traced FINISH checkpoint and subsequent GIF activity only',
                  'run': str(args.run.resolve()), 'passed': False, 'issues': [str(error)]}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
