"""Alternate two VU1 replay binaries and compare full architectural hashes.

Timing covers captured VU1 workloads only, never whole-game speed.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import statistics
import subprocess
from vu1_verify import parse_result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--snapshots', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--budget', type=int, default=65536)
    parser.add_argument('--resumes', type=int, default=0)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--candidate-env', action='append', default=[], metavar='PS2X_NAME=VALUE',
                        help='Explicit opt-in switches for candidate only; timings must disable tracing')
    args = parser.parse_args()
    if args.out.exists() or args.rounds < 1:
        parser.error('Use a new output and positive round count')
    root = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PS2X_')}
    env['PATH'] = str(root / 'dependencies/runtime-libraries/ffmpeg/bin') + os.pathsep + env.get('PATH', '')
    candidate_env = {}
    for assignment in args.candidate_env:
        key, separator, value = assignment.partition('=')
        if not separator or not key.startswith('PS2X_') or not key.replace('_', '').isalnum():
            parser.error('Candidate switches must use PS2X_NAME=VALUE')
        candidate_env[key] = value
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    hashes = {name: digest(path) for name, path in binaries.items()}
    report = {'scope': 'captured VU1 register/status/data/cycle replay and local timings; game speed unverified',
              'binary_sha256': hashes, 'budget': args.budget, 'resumes': args.resumes,
              'rounds': args.rounds, 'candidate_environment': candidate_env, 'sources': [], 'matching': True}
    for source in args.snapshots:
        snapshots = sorted(source.glob('vu1snap_*.bin'))[:400]
        if len(snapshots) != 400:
            raise ValueError('Expected exactly 400 selected snapshots')
        identity = [(p.name, digest(p)) for p in snapshots]
        results = {name: [] for name in binaries}
        for trial in range(args.rounds):
            for name in (('baseline', 'candidate') if trial % 2 == 0 else ('candidate', 'baseline')):
                process = subprocess.run([str(binaries[name]), str(source.resolve()), '--limit', '400',
                                          '--repeat', '30', '--budget', str(args.budget), '--resumes', str(args.resumes)],
                                         cwd=root, env={**env, **(candidate_env if name == 'candidate' else {})},
                                         capture_output=True, text=True, timeout=120)
                if process.returncode:
                    raise RuntimeError(process.stderr or process.stdout)
                block_trace = re.search(r'compiled_block_entries=(\d+) compiled_block_steps=(\d+)', process.stdout)
                if block_trace and any(int(value) for value in block_trace.groups()):
                    raise ValueError('Block tracing must be disabled for timing comparison')
                parsed = parse_result(process.stdout)
                if not parsed['status_hashed'] or parsed['compiled'] != 400:
                    raise ValueError('Expected complete compiled replay with status included')
                results[name].append(parsed)
        expected = tuple(results['baseline'][0][k] for k in ('snapshots', 'cycles', 'hash'))
        if any(tuple(item[k] for k in ('snapshots', 'cycles', 'hash')) != expected
               for values in results.values() for item in values):
            raise ValueError('Candidate changed architectural replay results')
        if identity != [(p.name, digest(p)) for p in snapshots]:
            raise ValueError('Snapshots changed during comparison')
        medians = {name: statistics.median(item['ns_per_cycle'] for item in values) for name, values in results.items()}
        report['sources'].append({'directory': str(source.resolve()), 'snapshots': identity,
                                  'results': results, 'median_ns_per_cycle': medians,
                                  'relative_speed_gain_percent': (medians['baseline'] / medians['candidate'] - 1) * 100})
    if hashes != {name: digest(path) for name, path in binaries.items()}:
        raise ValueError('Binary changed during comparison')
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({'matching': True, 'sources': [
        {k: row[k] for k in ('directory', 'median_ns_per_cycle', 'relative_speed_gain_percent')}
        for row in report['sources']]}, indent=2))


if __name__ == '__main__':
    main()
