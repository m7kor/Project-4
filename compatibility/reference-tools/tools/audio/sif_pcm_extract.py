"""Reconstruct delivered mono SJ PCM chunks from SIFP v1 observations.

Uses SJ descriptors' actual byte counts, not padded DMA lengths. Stream order
is descriptor order, not a reconstruction of subsequent IOP consumption.
"""
import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import struct
import wave

HEADER = struct.Struct('<8I')


def extract(path, ids):
    memory = bytearray(2 * 1024 * 1024)
    observed = bytearray(len(memory))
    streams = {id_: bytearray() for id_ in ids}
    counts = Counter()
    chunks = []
    records = 0
    previous = 0
    pending = defaultdict(deque)
    transport = Counter()
    with Path(path).open('rb') as source:
        while header := source.read(HEADER.size):
            if len(header) != HEADER.size:
                raise ValueError('truncated SIFP header')
            magic, version, sequence, ee_source, dest, size, flags, reserved = HEADER.unpack(header)
            if magic != 0x50464953 or version != 1 or sequence <= previous or not size or dest + size > len(memory) or flags > 3:
                raise ValueError('invalid SIFP header')
            previous = sequence
            data = source.read(size)
            if len(data) != size:
                raise ValueError('truncated SIFP payload')
            descriptor = flags & 1
            key = ee_source, dest, size
            records += 1
            if flags & 2:
                pending[key].append(data)
                continue
            if pending[key]:
                expected = pending[key].popleft()
                transport['paired_transfers'] += 1
                transport['exact_transfers'] += data == expected
                transport['mismatched_bytes'] += sum(a != b for a, b in zip(data, expected))
            else:
                transport['after_without_before'] += 1
            memory[dest:dest + size] = data
            observed[dest:dest + size] = b'\1' * size
            if not descriptor:
                continue
            if size != 0x880 or ee_source != 0x30ee00:
                raise ValueError('invalid SJ descriptor record')
            count = struct.unpack_from('<I', data)[0]
            if count > (size - 16) // 16:
                raise ValueError('SJ descriptor count exceeds packet')
            for index in range(count):
                kind, id_, address, length = struct.unpack_from('<4I', data, 16 + index * 16)
                if kind & 0xffff != 0x100 or id_ not in streams:
                    continue
                if not length or length % 2 or address + length > len(memory):
                    raise ValueError('invalid SJ PCM range')
                if not all(observed[address:address + length]):
                    raise ValueError('SJ descriptor references uncaptured PCM bytes')
                chunks.append({'sequence': sequence, 'id': id_, 'address': address, 'bytes': length,
                               'stream_frame': len(streams[id_]) // 2})
                streams[id_] += memory[address:address + length]
                counts[id_] += 1
    if not records or any(not data for data in streams.values()):
        raise ValueError('empty capture or missing selected stream')
    return streams, {'schema': 1, 'path': str(Path(path).resolve()), 'records': records,
                     'transport': dict(transport), 'unpaired_before': sum(map(len, pending.values())),
                     'streams': {hex(id_): {'chunks': counts[id_], 'frames': len(data) // 2} for id_, data in streams.items()},
                     'chunks': chunks, 'limits': __doc__.strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--id', action='append', required=True, type=lambda x: int(x, 0), dest='ids')
    parser.add_argument('--sample-rate', type=int, default=48000)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.sample_rate <= 192000 or len(set(args.ids)) != len(args.ids):
        parser.error('invalid sample rate or duplicate stream IDs')
    try:
        streams, report = extract(args.capture, args.ids)
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report['sample_rate_assumed'] = args.sample_rate
    for id_, data in streams.items():
        path = args.out.with_name(args.out.stem + f'-{id_:x}.wav')
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(args.sample_rate); output.writeframes(data)
        report['streams'][hex(id_)]['wav'] = str(path.resolve())
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['streams'], indent=2))


if __name__ == '__main__':
    main()
