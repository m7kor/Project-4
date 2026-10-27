"""Compare real VU1 replay state, cycles and GIF across execution modes.

This is isolated replay acceptance, not native game speed or live MTVU proof.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def parse_result(output):
    expressions = {
        'execution': r'snapshots=(\d+) vu1_cycles=(\d+).*?result=([0-9a-f]+)',
        'compiled': r'compiled=(\d+)/(\d+) status_hashed=(yes|no)',
        'gif': r'gif_packets=(\d+) gif_result=([0-9a-f]+)',
        'publication': r'code_image_updates=(\d+) code_cache_publication=(yes|no)',
    }
    matches = {}
    for key, expression in expressions.items():
        matches[key] = re.findall(expression, output)
        if len(matches[key]) != 1:
            raise ValueError(f'Missing or ambiguous {key} result')
    count, cycles, state = matches['execution'][0]
    compiled, total, status = matches['compiled'][0]
    packets, gif = matches['gif'][0]
    updates, publication = matches['publication'][0]
    if (status != 'yes' or int(count) <= 0 or int(total) != int(count)
            or not 0 <= int(compiled) <= int(count) or publication != 'yes'):
        raise ValueError('Incomplete state or snapshot coverage')
    return {'snapshots': int(count), 'cycles': int(cycles), 'state_hash': state,
            'compiled': int(compiled), 'gif_packets': int(packets), 'gif_hash': gif,
            'code_image_updates': int(updates), 'code_cache_publication': True}


def equivalent(results):
    keys = ('snapshots', 'cycles', 'state_hash', 'gif_packets', 'gif_hash')
    first = results[0]
    return all(all(result[key] == first[key] for key in keys) for result in results[1:])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('bench', type=Path)
    parser.add_argument('snapshots', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='Fresh evidence directory')
    parser.add_argument('--limit', type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.limit <= 4096:
        parser.error('limit must be 1..4096')
    files = sorted(args.snapshots.glob('vu1snap_*.bin'))[:args.limit]
    if not files:
        parser.error('No snapshots')
    args.out.mkdir(parents=True, exist_ok=False)
    identity = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    before = {str(path.resolve()): identity(path) for path in files}
    executable_sha = identity(args.bench)
    results = []
    trace = [{'ph': 'M', 'name': 'thread_name', 'pid': os.getpid(), 'tid': 1,
              'args': {'name': 'VU1 replay subprocesses'}}]
    trace_start = time.perf_counter_ns()
    for mode, compiled, worker in (('interpreter', '0', False),
                                    ('compiled', '1', False), ('worker', '1', True)):
        env = {k: v for k, v in os.environ.items() if not k.startswith('PS2X_')}
        env['PS2X_VU1_COMPILED'] = compiled
        command = [str(args.bench.resolve()), str(args.snapshots.resolve()),
                   '--limit', str(args.limit), '--repeat', '3', '--gif-hash']
        if worker:
            command.append('--worker')
        started = time.perf_counter_ns()
        process = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        finished = time.perf_counter_ns()
        trace.append({'ph': 'X', 'name': f'VU1 replay: {mode}', 'cat': 'diagnostic_subprocess',
                      'pid': os.getpid(), 'tid': 1, 'ts': (started - trace_start) / 1000,
                      'dur': (finished - started) / 1000,
                      'args': {'scope': 'Includes process startup, setup, replay and GIF hashing; not game frame timing'}})
        with (args.out / f'{mode}.log').open('x', encoding='utf-8') as log:
            log.write(process.stdout + process.stderr)
        if process.returncode:
            raise RuntimeError(f'{mode} failed: {process.returncode}')
        result = parse_result(process.stdout)
        if result['snapshots'] != len(files):
            raise ValueError('Not all requested snapshots replayed')
        if mode == 'interpreter' and result['compiled']:
            raise ValueError('Reference unexpectedly used compiled code')
        if worker and 'execution_thread=worker game_mtvu_enabled=no' not in process.stdout:
            raise ValueError('Worker replay did not confirm its execution thread')
        results.append(dict(result, mode=mode))
    stable = (files == sorted(args.snapshots.glob('vu1snap_*.bin'))[:args.limit] and
              executable_sha == identity(args.bench) and
              before == {str(path.resolve()): identity(path) for path in files})
    accepted = stable and equivalent(results)
    report = {'scope': __doc__, 'bench_sha256': executable_sha, 'inputs': before,
              'stable': stable, 'equivalent': accepted, 'modes': results}
    with (args.out / 'comparison.json').open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    with (args.out / 'subprocess-trace.json').open('x', encoding='utf-8') as output:
        json.dump({'traceEvents': trace}, output)
    print(json.dumps({'equivalent': accepted, 'snapshots': len(files), 'modes': results}))
    if not accepted:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
