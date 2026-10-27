"""Compare MCPW v1 IOP writes with ADMR v1 copies from the same run.

Both clocks are service clocks. Events sharing a clock have no defined order
between files; mismatches can also indicate writes outside the observed APIs.
This report detects differently aged data, not whether a game intended it.
Forced termination can omit the buffered write tail; the producer caps at
16 million records. Do not infer stale data beyond the observed write period.
"""
import argparse
import json
from pathlib import Path
import struct

import numpy as np

WRITE_HEADER = struct.Struct('<4I')
WRITE = struct.Struct('<QIII')
READ = struct.Struct('<IIIIQQIIII')


def writes(path, allow_incomplete_tail=False):
    with Path(path).open('rb') as stream:
        header = stream.read(WRITE_HEADER.size)
        if len(header) != WRITE_HEADER.size:
            raise ValueError('truncated MCPW header')
        magic, version, start, length = WRITE_HEADER.unpack(header)
        if magic != 0x5750434d or version != 1 or not length or start + length > 2 * 1024 * 1024:
            raise ValueError('invalid MCPW header')
        yield start, length
        previous = 0
        while raw := stream.read(WRITE.size):
            if len(raw) != WRITE.size:
                if allow_incomplete_tail:
                    return
                raise ValueError('truncated MCPW write')
            cycle, address, size, value = WRITE.unpack(raw)
            if cycle < previous or not 1 <= size <= 4 or not start <= address or address + size > start + length:
                raise ValueError('invalid MCPW write')
            previous = cycle
            yield cycle, address, size, value


def compare(write_path, read_path, allow_incomplete_tail=False):
    producer = writes(write_path, allow_incomplete_tail)
    start, length = next(producer)
    memory = bytearray(length)
    ages = np.zeros(length, dtype=np.uint64)
    pending = next(producer, None)
    rows = []
    write_count = 0
    previous = 0
    with Path(read_path).open('rb') as stream:
        while raw := stream.read(READ.size):
            if len(raw) != READ.size:
                raise ValueError('truncated ADMR header')
            magic, version, size, core, cycle, frame, dest, source, progress, left = READ.unpack(raw)
            if magic != 0x524d4441 or version != 1 or not 0 < size <= 2 * 1024 * 1024 or cycle < previous:
                raise ValueError('invalid ADMR header')
            previous = cycle
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError('truncated ADMR payload')
            while pending and pending[0] <= cycle:
                stamp, address, count, value = pending
                offset = address - start
                memory[offset:offset + count] = value.to_bytes(4, 'little')[:count]
                ages[offset:offset + count] = stamp
                write_count += 1
                pending = next(producer, None)
            if source < start or source + size > start + length:
                continue
            offset = source - start
            stamps = ages[offset:offset + size]
            observed = np.frombuffer(payload, np.uint8)
            expected = np.frombuffer(memory, np.uint8, count=size, offset=offset)
            changed = np.flatnonzero(observed != expected)
            row = {'cycle': cycle, 'copy_seconds': frame / 48000, 'source': source, 'core': core,
                   'spu2_halfword': dest, 'bytes': size, 'mismatched_bytes': len(changed),
                   'first_mismatch_byte': int(changed[0]) if len(changed) else None,
                   'unobserved_bytes': int(np.count_nonzero(stamps == 0)),
                   'same_clock_bytes': int(np.count_nonzero(stamps == cycle)),
                   'oldest_write_age_cycles': int(cycle - int(np.min(stamps))),
                   'newest_write_age_cycles': int(cycle - int(np.max(stamps))),
                   'write_span_cycles': int(int(np.max(stamps)) - int(np.min(stamps)))}
            if size == 512:
                row['first_96_mean_age_cycles'] = float(cycle - np.mean(stamps[:192]))
                row['last_160_mean_age_cycles'] = float(cycle - np.mean(stamps[192:]))
            rows.append(row)
    # Validate the tail too, so a malformed producer file is not silently accepted.
    for _ in producer:
        pass
    if not rows:
        raise ValueError('no reads overlap the producer range')
    valid = [r for r in rows if not r['unobserved_bytes'] and not r['mismatched_bytes']]
    return {'schema': 1, 'write_trace': str(Path(write_path).resolve()), 'read_trace': str(Path(read_path).resolve()),
            'range_start': start, 'range_bytes': length, 'writes_applied': write_count,
            'reads': len(rows), 'exact_reconstructions': sum(r['mismatched_bytes'] == 0 for r in rows),
            'fully_observed_exact_reads': len(valid),
            'incomplete_write_tail_bytes': (Path(write_path).stat().st_size - WRITE_HEADER.size) % WRITE.size,
            'write_stream_exhausted_at_last_read': pending is None,
            'largest_write_spans': sorted(valid, key=lambda r: r['write_span_cycles'], reverse=True)[:20],
            'records': rows, 'limits': __doc__.strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('writes', type=Path)
    parser.add_argument('reads', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--allow-incomplete-tail', action='store_true', help='Ignore only the final partial write after forced termination')
    args = parser.parse_args()
    try:
        result = compare(args.writes, args.reads, args.allow_incomplete_tail)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('records', 'largest_write_spans')}, indent=2))


if __name__ == '__main__':
    main()
