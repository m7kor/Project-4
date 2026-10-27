"""Compare compiled and interpreted VU1 replay results on local snapshots."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

RESULT = re.compile(r'snapshots=(\d+) vu1_cycles=(\d+) best=([\d.]+) s\s+ns/cycle=([\d.]+)\s+result=([0-9a-f]{16})')
COVERAGE = re.compile(r'compiled=(\d+)/(\d+) status_hashed=(yes|no)')
SWITCHES = ('PS2X_VU1_COMPILED', 'PS2X_VU1_DIRECT', 'PS2X_VU1_EXACT_FLAGS', 'PS2X_VU1_CAPTURE',
            'PS2X_VU1_SNAPSHOT', 'PS2X_GS_BACKEND', 'PS2X_GS_THREAD')


def parse_result(output):
    match, coverage = RESULT.search(output), COVERAGE.search(output)
    if not match or not coverage:
        raise ValueError('benchmark output lacks result or compiled coverage')
    count, cycles, seconds, nanos, digest = match.groups()
    compiled, total, status = coverage.groups()
    if int(count) != int(total) or int(compiled) > int(total) or int(count) == 0 or int(cycles) == 0:
        raise ValueError('invalid benchmark counts')
    return {'snapshots': int(count), 'cycles': int(cycles), 'seconds': float(seconds),
            'ns_per_cycle': float(nanos), 'hash': digest, 'compiled': int(compiled),
            'status_hashed': status == 'yes'}


def verify(bench, snapshots, repeat=3, limit=None):
    environment = {k: v for k, v in os.environ.items() if k.upper() not in SWITCHES}
    modes = [
        ('compiled', {}, False),
        ('interpreted', {'PS2X_VU1_COMPILED': '0'}, False),
        ('reference', {'PS2X_VU1_COMPILED': '0', 'PS2X_VU1_DIRECT': '0', 'PS2X_VU1_EXACT_FLAGS': '1'}, False),
        ('exact', {'PS2X_VU1_EXACT_FLAGS': '1'}, True),
        ('exact_reference', {'PS2X_VU1_COMPILED': '0', 'PS2X_VU1_DIRECT': '0', 'PS2X_VU1_EXACT_FLAGS': '1'}, True),
    ]
    results = {}
    for name, switches, hash_status in modes:
        command = [str(bench), str(snapshots), '--repeat', str(repeat)]
        if limit is not None:
            command += ['--limit', str(limit)]
        if not hash_status:
            command += ['--no-status']
        process = subprocess.run(command, env={**environment, **switches}, capture_output=True, text=True, timeout=300)
        if process.returncode:
            raise ValueError(f'{name} failed ({process.returncode}): {process.stderr or process.stdout}')
        results[name] = parse_result(process.stdout)
        if results[name]['status_hashed'] != hash_status:
            raise ValueError(f'{name}: unexpected status hashing mode')
    comparable = lambda name: tuple(results[name][k] for k in ('snapshots', 'cycles', 'hash'))
    optimized_equal = comparable('compiled') == comparable('interpreted') == comparable('reference')
    exact_equal = comparable('exact') == comparable('exact_reference') and results['exact']['compiled'] == 0
    return {'schema': 1, 'snapshots_dir': str(snapshots.resolve()), 'results': results,
            'optimized_equal': optimized_equal, 'exact_equal': exact_equal,
            'passed': optimized_equal and exact_equal,
            'scope': 'isolated MSCAL replay; excludes status only in optimized comparison; does not prove gameplay or MTVU'}


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshots', type=Path)
    parser.add_argument('--bench', type=Path, default=root / 'core/out/build/ps2xTest/ps2x_vu1_bench.exe')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeat <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error('repeat and limit must be positive')
    try:
        report = verify(args.bench.resolve(), args.snapshots, args.repeat, args.limit)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'{error}\n')
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
