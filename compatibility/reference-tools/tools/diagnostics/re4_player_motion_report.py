"""Summarize raw RE4 player samples without claiming campaign or speed proof."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct


def summarize(batch):
    if not batch.get('completed') or batch.get('error'):
        raise ValueError('A complete, error-free batch is required')
    samples = batch.get('observations', [])
    if len(samples) < 2:
        raise ValueError('At least two observations are required')
    rows = []
    initial_pointer = samples[0].get('player_pointer')
    previous_angle = accumulated = None
    for sample in samples:
        if (not sample.get('player_pointer_stable') or not initial_pointer
                or sample.get('player_pointer') != initial_pointer
                or sample.get('player_pointer_after') != initial_pointer):
            raise ValueError('Player identity changed during the batch')
        raw = bytes.fromhex(sample.get('player_bytes_hex') or '')
        if len(raw) < 0xd8:
            raise ValueError('Player payload is missing or truncated')
        matrix = struct.unpack_from('<16f', raw, 0x10)
        position = struct.unpack_from('<3f', raw, 0xc0)
        yaw = struct.unpack_from('<f', raw, 0xd4)[0]
        when = sample['monotonic']
        if not all(math.isfinite(v) for v in (*matrix, *position, yaw, when)):
            raise ValueError('Non-finite field')
        if rows and when <= rows[-1]['monotonic']:
            raise ValueError('Sample times must strictly increase')
        step = 0.0 if previous_angle is None else (yaw - previous_angle + math.pi) % (2 * math.pi) - math.pi
        accumulated = yaw if accumulated is None else accumulated + step
        previous_angle = yaw
        rows.append({'monotonic': when, 'yaw_degrees': math.degrees(yaw),
                     'unwrapped_degrees': math.degrees(accumulated), 'step_degrees': math.degrees(step),
                     'position': position,
                     'matrix_translation_error': max(abs(position[i] - matrix[12 + i]) for i in range(3)),
                     'matrix_trig_error': max(abs(matrix[0] - math.cos(yaw)), abs(matrix[2] + math.sin(yaw)),
                                             abs(matrix[8] - math.sin(yaw)), abs(matrix[10] - math.cos(yaw)))})
    delta = [rows[-1]['position'][i] - rows[0]['position'][i] for i in range(3)]
    return {'scope': 'Model field inference from raw samples; no door entry, collision correctness, speed or input latency proof',
            'unwrap_assumption': 'Consecutive samples must differ by less than 180 degrees; missed full rotations cannot be excluded from samples alone',
            'samples': len(rows), 'duration_seconds': rows[-1]['monotonic'] - rows[0]['monotonic'],
            'initial_yaw_degrees': rows[0]['yaw_degrees'], 'final_yaw_degrees': rows[-1]['yaw_degrees'],
            'unwrapped_delta_degrees': rows[-1]['unwrapped_degrees'] - rows[0]['unwrapped_degrees'],
            'max_observed_step_degrees': max(abs(row['step_degrees']) for row in rows),
            'position_delta': delta, 'net_displacement_guest_units': math.sqrt(sum(v * v for v in delta)),
            'max_matrix_translation_error': max(row['matrix_translation_error'] for row in rows),
            'max_matrix_trig_error': max(row['matrix_trig_error'] for row in rows),
            'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raw = args.batch.read_bytes()
    result = summarize(json.loads(raw))
    result['batch_sha256'] = hashlib.sha256(raw).hexdigest()
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
