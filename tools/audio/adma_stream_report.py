"""Analyze the IOP->SPU2 DMA capture written with PS2X_ADMA_RAW.

Records are [u32 core][u32 bytes][u64 IOP cycle][payload]. AutoDMA (ADMA)
streams arrive as 0x400-byte blocks: 0x200 bytes left then 0x200 bytes right,
256 samples per channel. For each core this reports:

  * timing: cycles between consecutive blocks against 256 samples x 768 IOP
    cycles = 196608 (late blocks make the SPU2 play stale input)
  * data: mean |sample jump| at block boundaries versus inside blocks (a clean
    stream has no excess at the boundaries)

and writes <capture>-coreN.wav with the stream exactly as the sound driver
produced it, before the SPU2 mixes it.

    python -I tools/audio/adma_stream_report.py artifacts/.../run4-adma.raw
"""
import argparse
import struct
import wave
from pathlib import Path

import numpy as np

BLOCK_CYCLES = 256 * 768


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    data = args.capture.read_bytes()
    records = {0: [], 1: []}
    offset = 0
    while offset + 16 <= len(data):
        core, size = struct.unpack_from('<II', data, offset)
        cycle = struct.unpack_from('<Q', data, offset + 8)[0]
        payload = data[offset + 16:offset + 16 + size]
        offset += 16 + size
        if len(payload) < size:
            break
        records.setdefault(core, []).append((cycle, size, payload))
    for core, recs in records.items():
        if not recs:
            continue
        sizes = {}
        for _, size, _ in recs:
            sizes[size] = sizes.get(size, 0) + 1
        print(f'core {core}: {len(recs)} DMA transfers, sizes {dict(sorted(sizes.items(), key=lambda kv: -kv[1])[:4])}')
        size = max(sizes, key=sizes.get)  # the stream's block size
        half = size // 2
        per = size // 4  # samples per channel per block
        expected = per * 768
        blocks = [(c, p) for c, s, p in recs if s == size]
        if len(blocks) < 8:
            print('  too few blocks')
            continue
        cycles = np.array([c for c, _ in blocks], dtype=np.int64)
        gaps = np.diff(cycles)
        late = np.count_nonzero(gaps > expected * 1.05)
        early = np.count_nonzero(gaps < expected * 0.95)
        print(f'  block {size:#x} bytes = {per} samples/channel; interval median {np.median(gaps):.0f} cycles '
              f'(expected {expected}), p5 {np.percentile(gaps, 5):.0f} p95 {np.percentile(gaps, 95):.0f}, '
              f'late {late} ({100 * late / len(gaps):.1f}%), early {early} ({100 * early / len(gaps):.1f}%)')
        left = np.concatenate([np.frombuffer(p[:half], '<i2') for _, p in blocks]).astype(np.int32)
        right = np.concatenate([np.frombuffer(p[half:size], '<i2') for _, p in blocks]).astype(np.int32)
        jumps = np.abs(np.diff(left))
        boundary = jumps[per - 1::per]
        inside = np.delete(jumps, np.arange(per - 1, len(jumps), per))
        loud = np.abs(left).mean()
        print(f'  stream level {loud:.0f}; mean |jump| at block boundaries {boundary.mean():.0f} vs inside {inside.mean():.0f} '
              f'(ratio {boundary.mean() / max(inside.mean(), 1e-9):.2f})')
        silent = sum(1 for _, p in blocks if not any(p))
        print(f'  all-zero blocks: {silent} of {len(blocks)}')
        out = args.capture.with_name(args.capture.stem + f'-core{core}.wav')
        with wave.open(str(out), 'wb') as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(np.stack([left, right], 1).astype('<i2').tobytes())
        print(f'  wrote {out}')


if __name__ == '__main__':
    main()
