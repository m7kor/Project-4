"""Extract a captured fence, replay both renderers, or audit its delivery stages.

Inspired by the pinned BT3 reference-comparison and Urban GS recording designs.
This validates a fence and its observed delivery, not whole-game compatibility.
"""
from pathlib import Path
import argparse
from collections import defaultdict
import hashlib
import json
import os
import re
import struct
import subprocess

PACKET = struct.pack('<6Q', 0x1000000000008002, 0xe, 0, 0x3f, 0, 0x61)
STAGES = ('dma-copy', 'memory-submit', 'gs-entry', 'gs-dispatch', 'gpu-entry')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(log):
    stages = defaultdict(list)
    issues = []
    for number, line in enumerate(log.read_text(errors='replace').splitlines(), 1):
        if '[GIF fence pipeline]' not in line:
            continue
        match = re.search(r'stage=([\w-]+) index=(\d+) bytes=(\d+)', line)
        if not match or match[1] not in STAGES or int(match[3]) != 48:
            issues.append(f'Invalid pipeline record at line {number}')
            continue
        stages[match[1]].append(int(match[2]))
    for stage in STAGES:
        indices = stages[stage]
        if not indices:
            issues.append(f'Missing required stage: {stage}')
        elif indices != list(range(indices[0], indices[0] + len(indices))):
            issues.append(f'Duplicate, out-of-order or missing indices: {stage}')
    counts = {s: len(stages[s]) for s in STAGES}
    if len(set(counts.values())) > 1:
        issues.append('Observed exact-packet counts differ across delivery stages')
    return {'schema': 1, 'scope': 'observed exact TEXFLUSH/FINISH packet delivery only',
            'log': str(log.resolve()), 'log_sha256': sha(log), 'counts': counts,
            'ranges': {s: [stages[s][0], stages[s][-1]] if stages[s] else None for s in STAGES},
            'issues': issues, 'passed': not issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    extract = commands.add_parser('extract', help='Extract original packet from a caller-supplied EE RAM snapshot')
    extract.add_argument('--ram', type=Path, required=True)
    extract.add_argument('--address', type=lambda x: int(x, 0), default=0x432740)
    extract.add_argument('--packet', type=Path, required=True)
    extract.add_argument('--replay', type=Path, help='Built ps2x_gif_fence_replay executable')
    check = commands.add_parser('audit', help='Require every observed delivery stage; missing evidence fails')
    check.add_argument('--log', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Existing reports are preserved; choose a new output path')
    if args.command == 'audit':
        result = audit(args.log)
    else:
        if args.packet.exists() or args.ram.stat().st_size != 32 * 1024 * 1024 or not 0 <= args.address <= 32 * 1024 * 1024 - 48:
            parser.error('Use a new packet path and a complete 32 MiB EE RAM snapshot with a valid address')
        with args.ram.open('rb') as source:
            source.seek(args.address)
            packet = source.read(48)
        if packet != PACKET:
            parser.error('Snapshot bytes are not the expected original TEXFLUSH/FINISH fence')
        with args.packet.open('xb') as destination:
            destination.write(packet)
        result = {'schema': 1, 'scope': 'captured fence contents; standalone renderer replay if requested',
                  'ram': str(args.ram.resolve()), 'ram_sha256': sha(args.ram), 'address': args.address,
                  'packet': str(args.packet.resolve()), 'packet_sha256': sha(args.packet), 'passed': True}
        if args.replay:
            env = {k: v for k, v in os.environ.items() if not k.startswith('PS2X_')}
            replay = subprocess.run([str(args.replay.resolve()), str(args.packet.resolve())],
                                    env=env, capture_output=True, text=True, timeout=60)
            rows = [json.loads(line) for line in replay.stdout.splitlines() if line.startswith('{')]
            result.update(replay_exe=str(args.replay.resolve()), replay_sha256=sha(args.replay),
                          replay_exit=replay.returncode, replay_result=rows[-1] if rows else None,
                          replay_stderr=replay.stderr[-4000:])
            result['passed'] = (replay.returncode == 0 and bool(rows) and rows[-1].get('cpu_finish') is True
                                and rows[-1].get('gpu_finish_callbacks') == 1)
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
