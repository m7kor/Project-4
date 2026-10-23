"""Verify opt-in VU1 blocks against preserved binary and current per-pair replay.

Compare status, registers, cycles, data and emitted GIF bytes on real snapshots.
Trace proves the compiled block path executed; these timings are not a benchmark.
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
    parser.add_argument('--baseline', type=Path, default=root / 'artifacts/tool-audit/20261013/vu1-detached-baseline/ps2x_vu1_bench.exe')
    parser.add_argument('--candidate', type=Path, default=root / 'core/out/build/ps2xTest/ps2x_vu1_bench.exe')
    parser.add_argument('--snapshots', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new output path')
    baseline, candidate = args.baseline.resolve(), args.candidate.resolve()
    binaries = {'preserved': baseline, 'pairs': candidate, 'blocks': candidate}
    hashes = {name: digest(path) for name, path in binaries.items()}
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PS2X_')}
    env['PATH'] = str(root / 'dependencies/runtime-libraries/ffmpeg/bin') + os.pathsep + env.get('PATH', '')
    report = {'scope': __doc__, 'binary_sha256': hashes, 'sources': [],
              'game_worker_enabled': False, 'natural_speed_proven': False, 'passed': True}
    count = 0
    for source in args.snapshots:
        source = source.resolve()
        files = sorted(source.glob('vu1snap_*.bin'))[:400]
        if len(files) != 400:
            raise ValueError('Need 400 selected snapshots per source')
        identity = [(p.name, digest(p)) for p in files]
        rows = []
        for budget, resumes in ((65536, 0), (1, 64), (2, 32), (4, 16), (32, 4), (256, 4), (4096, 4)):
            results = {}
            for name, binary in binaries.items():
                command = [str(binary), str(source), '--limit', '400', '--repeat', '3',
                           '--budget', str(budget), '--resumes', str(resumes), '--gif-hash']
                switches = {'PS2X_VU1_BLOCKS': '1' if name == 'blocks' else '0', 'PS2X_VU1_TRACE_BLOCKS': '1'}
                process = subprocess.run(command, cwd=root, env={**env, **switches},
                                         capture_output=True, text=True, timeout=180)
                if process.returncode:
                    raise RuntimeError(process.stderr or process.stdout)
                result = parse_result(process.stdout)
                gif = re.search(r'gif_packets=(\d+) gif_result=([0-9a-f]{16})', process.stdout)
                trace = re.search(r'compiled_block_entries=(\d+) compiled_block_steps=(\d+)', process.stdout)
                if not gif or not result['status_hashed'] or result['compiled'] != 400:
                    raise ValueError('Missing GIF, status or compiled-table coverage')
                result.update(gif_packets=int(gif[1]), gif_hash=gif[2],
                              block_entries=int(trace[1]) if trace else 0,
                              block_steps=int(trace[2]) if trace else 0)
                if name != 'preserved' and not trace:
                    raise ValueError('Current binary lacks block trace')
                if name != 'blocks' and result['block_entries']:
                    raise ValueError('Blocks ran without opt-in')
                if name == 'blocks' and budget == 65536 and not (
                        result['block_steps'] > result['block_entries'] > 0):
                    raise ValueError('Full replay did not execute combined block steps')
                results[name] = result
            observable = ('snapshots', 'cycles', 'hash', 'compiled', 'status_hashed', 'gif_packets', 'gif_hash')
            if any(results[name][key] != results['preserved'][key]
                   for name in ('pairs', 'blocks') for key in observable):
                raise ValueError(f'Block replay changed results: {source.name}/{budget}/{resumes}')
            rows.append({'budget': budget, 'resumes': resumes, 'results': results})
            count += 400
            print(f'{source.name}: budget={budget} resumes={resumes}: 400 matching across three paths', flush=True)
        if identity != [(p.name, digest(p)) for p in files]:
            raise ValueError('Snapshots changed during replay')
        report['sources'].append({'directory': str(source), 'snapshots': identity, 'comparisons': rows})
    if hashes != {name: digest(path) for name, path in binaries.items()}:
        raise ValueError('Binary changed during replay')
    report['snapshot_cases'] = count
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({'passed': True, 'snapshot_cases': count, 'paths': 3, 'game_speed_proven': False}))


if __name__ == '__main__':
    main()
