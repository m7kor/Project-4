"""Compare caller/worker VU1 replay including full status and emitted GIF bytes.

This verifies isolated captured workloads, not concurrent EE execution or game
speed. Both modes use the same binary, sources, budget and resume sequence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from vu1_verify import parse_result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bench', type=Path, default=root / 'core/out/build/ps2xTest/ps2x_vu1_bench.exe')
    parser.add_argument('--snapshots', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-fallback', action='store_true',
                        help='Allow partial/zero compiled coverage; record it, without claiming a compiled-path test')
    parser.add_argument('--baseline', type=Path,
                        help='Also compare against a preserved caller binary; its compiled coverage may differ')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new output path')
    bench = args.bench.resolve()
    binary_hash = digest(bench)
    baseline = args.baseline.resolve() if args.baseline is not None else None
    baseline_hash = digest(baseline) if baseline is not None else None
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PS2X_')}
    env['PATH'] = str(root / 'dependencies/runtime-libraries/ffmpeg/bin') + os.pathsep + env.get('PATH', '')
    report = {'scope': __doc__, 'binary': str(bench), 'sha256': binary_hash,
              'execution_apis': {'caller': 'direct interpreter', 'worker': 'detached control executor'},
              'game_mtvu_enabled': False, 'natural_speed_proven': False, 'sources': [], 'passed': True}
    report['allows_compiled_fallback'] = args.allow_fallback
    report['baseline'] = {'binary': str(baseline), 'sha256': baseline_hash} if baseline is not None else None
    comparisons = 0
    for source in args.snapshots:
        source = source.resolve()
        files = sorted(source.glob('vu1snap_*.bin'))[:400]
        if len(files) != 400:
            raise ValueError('Expected 400 selected snapshots per source')
        identities = [(p.name, digest(p)) for p in files]
        rows = []
        for mode, switches in (('compiled', {}), ('reference', {
                'PS2X_VU1_COMPILED': '0', 'PS2X_VU1_DIRECT': '0', 'PS2X_VU1_EXACT_FLAGS': '1'})):
            for budget, resumes in ((65536, 0), (1, 4), (32, 4), (256, 4), (4096, 4)):
                results = {}
                # Alternate order between cases; timings here are diagnostic only.
                for worker in ((False, True) if len(rows) % 2 == 0 else (True, False)):
                    command = [str(bench), str(source), '--limit', '400', '--repeat', '3',
                               '--budget', str(budget), '--resumes', str(resumes), '--gif-hash']
                    if worker:
                        command += ['--worker', '--executor']
                    process = subprocess.run(command, cwd=root, env={**env, **switches},
                                             capture_output=True, text=True, timeout=180)
                    if process.returncode:
                        raise RuntimeError(process.stderr or process.stdout)
                    result = parse_result(process.stdout)
                    gif = re.search(r'gif_packets=(\d+) gif_result=([0-9a-f]{16})', process.stdout)
                    thread = 'worker' if worker else 'caller'
                    if not gif or f'execution_thread={thread} game_mtvu_enabled=no' not in process.stdout:
                        raise ValueError('Replay did not confirm requested thread and GIF capture')
                    executor = 'detached' if worker else 'direct'
                    if f'executor={executor}' not in process.stdout:
                        raise ValueError('Replay did not confirm requested execution API')
                    result.update(gif_packets=int(gif[1]), gif_hash=gif[2])
                    coverage_ok = (args.allow_fallback or result['compiled'] == 400) if mode == 'compiled' else result['compiled'] == 0
                    if not result['status_hashed'] or not coverage_ok:
                        raise ValueError('Unexpected replay coverage or omitted status')
                    results[thread] = result
                observable = ('snapshots', 'cycles', 'hash', 'compiled', 'status_hashed', 'gif_packets', 'gif_hash')
                if any(results['caller'][key] != results['worker'][key] for key in observable):
                    raise ValueError(f'Worker mismatch: {source.name}/{mode}/{budget}/{resumes}')
                if baseline is not None:
                    baseline_command = [str(baseline), str(source), '--limit', '400', '--repeat', '3',
                                        '--budget', str(budget), '--resumes', str(resumes), '--gif-hash']
                    original = subprocess.run(baseline_command, cwd=root, env={**env, **switches},
                                              capture_output=True, text=True, timeout=180)
                    if original.returncode:
                        raise RuntimeError(original.stderr or original.stdout)
                    previous = parse_result(original.stdout)
                    previous_gif = re.search(r'gif_packets=(\d+) gif_result=([0-9a-f]{16})', original.stdout)
                    if not previous_gif or 'execution_thread=caller game_mtvu_enabled=no' not in original.stdout or 'executor=direct' not in original.stdout:
                        raise ValueError('Baseline lacks caller/GIF evidence')
                    previous.update(gif_packets=int(previous_gif[1]), gif_hash=previous_gif[2])
                    if any(results['caller'][key] != previous[key] for key in observable if key != 'compiled'):
                        raise ValueError(f'Preserved binary mismatch: {source.name}/{mode}/{budget}/{resumes}')
                    results['preserved'] = previous
                rows.append({'mode': mode, 'budget': budget, 'resumes': resumes, 'results': results})
                comparisons += 400
                print(f'{source.name}: {mode} budget={budget} resumes={resumes}: 400 matching', flush=True)
        if identities != [(p.name, digest(p)) for p in files]:
            raise ValueError('Snapshots changed during replay')
        report['sources'].append({'directory': str(source), 'snapshots': identities, 'comparisons': rows})
    if digest(bench) != binary_hash:
        raise ValueError('Replay binary changed during comparison')
    if baseline is not None and digest(baseline) != baseline_hash:
        raise ValueError('Baseline binary changed during comparison')
    report['snapshot_comparisons'] = comparisons
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({'passed': True, 'snapshot_comparisons': comparisons, 'game_mtvu_enabled': False}))


if __name__ == '__main__':
    main()
