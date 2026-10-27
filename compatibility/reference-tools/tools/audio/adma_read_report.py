"""Inspect actual IOP -> SPU2 input copies (PS2X_ADMA_READ_RAW, ADMR v1).

Unlike PS2X_ADMA_RAW, these payloads are read when PCSX2's DMA code copies
them. Mixed-frame offsets date copies, not the later playback of that bank.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

HEADER = struct.Struct('<IIIIQQIIII')


def read_records(path):
    with Path(path).open('rb') as stream:
        while header := stream.read(HEADER.size):
            if len(header) != HEADER.size:
                raise ValueError('truncated ADMR header')
            magic, version, size, core, cycle, frame, dest, source, progress, left = HEADER.unpack(header)
            if magic != 0x524D4441 or version != 1 or core > 1 or not 0 < size <= 2 * 1024 * 1024 or size % 2:
                raise ValueError('invalid ADMR header')
            base = 0x2000 + core * 0x400
            if not base <= dest < base + 0x400:
                raise ValueError('invalid SPU2 input destination')
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError('truncated ADMR payload')
            x = np.frombuffer(payload, '<i2').astype(np.float64)
            nonzero = np.flatnonzero(x)
            steps = np.abs(np.diff(x))
            peak_offset = int(np.argmax(steps)) + 1 if len(steps) else 0
            yield {'core': core, 'cycle': cycle, 'mixed_frame': frame, 'copy_seconds': frame / 48000,
                   'spu2_halfword': dest, 'iop_byte': source, 'input_progress': progress, 'input_left': left,
                   'bytes': size, 'channel': 'right' if dest - base >= 0x200 else 'left',
                   'bank': (dest - base) & 0x100, 'rms': float(np.sqrt(np.mean(x * x))),
                   'zero_samples': int(np.count_nonzero(x == 0)), 'samples': len(x),
                   'leading_zero_samples': int(nonzero[0]) if len(nonzero) else len(x),
                   'trailing_zero_samples': len(x) - int(nonzero[-1]) - 1 if len(nonzero) else len(x),
                   'first_sample': int(x[0]), 'last_sample': int(x[-1]),
                   'max_internal_step': float(steps[peak_offset - 1]) if peak_offset else 0,
                   'max_internal_step_offset': peak_offset,
                   'sha256': hashlib.sha256(payload).hexdigest()}


def summarize(path):
    records = list(read_records(path))
    if not records:
        raise ValueError('empty ADMR trace')
    groups = {}
    for core in (0, 1):
        for channel in ('left', 'right'):
            rows = [r for r in records if r['core'] == core and r['channel'] == channel]
            if not rows:
                continue
            sizes = Counter(r['bytes'] for r in rows)
            audible = [r for r in rows if r['rms'] > 300]
            boundaries = [abs(b['first_sample'] - a['last_sample']) for a, b in zip(rows, rows[1:])]
            groups[f'{core}_{channel}'] = {
                'copies': len(rows), 'byte_sizes': dict(sizes),
                'all_zero_copies': sum(r['zero_samples'] == r['samples'] for r in rows),
                'zero_sample_percent': sum(r['zero_samples'] for r in rows) * 100 / sum(r['samples'] for r in rows),
                'leading_zero_histogram': dict(Counter(r['leading_zero_samples'] for r in rows)),
                'trailing_zero_histogram': dict(Counter(r['trailing_zero_samples'] for r in rows)),
                'audible_copies': len(audible),
                'audible_internal_peak_offsets': dict(Counter(r['max_internal_step_offset'] for r in audible)),
                'max_copy_order_boundary_step': max(boundaries, default=0),
                'largest_internal_steps': sorted(
                    ({k: r[k] for k in ('copy_seconds', 'iop_byte', 'max_internal_step', 'max_internal_step_offset')}
                     for r in audible), key=lambda r: r['max_internal_step'], reverse=True)[:20],
                'first_copy_seconds': rows[0]['copy_seconds'], 'last_copy_seconds': rows[-1]['copy_seconds']}
    return {'schema': 1, 'path': str(Path(path).resolve()), 'groups': groups, 'records': records,
            'limits': 'Copy time is not playback time. Source silence may be intentional. '
                      'Boundary steps use copy order, not playback order. Internal steps are present in copied bytes. '
                      'Steps and silence alone are not proof of audible faults. '
                      'Trace does not observe subsequent IOP writes or reconstruct SPU2 bank consumption.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = summarize(args.trace)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report['groups'], indent=2))


if __name__ == '__main__':
    main()
