"""Validate EE-side DIRECT captures and match assembled bytes to GPU inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from .gif_boundary_inspect import read_capture

HEADER = struct.Struct('<16Q')
MAGIC = 0x3143524944464956


def read(path):
    raw = path.read_bytes()
    if len(raw) < HEADER.size:
        raise ValueError('Truncated DIRECT source header')
    h = HEADER.unpack_from(raw)
    opcode = (h[9] >> 24) & 127
    declared = (h[9] & 65535 or 65536) * 16
    if h[0] != MAGIC or h[1] != 1 or h[2] >= 32 or h[10] not in (0, 1):
        raise ValueError('Invalid source capture identity')
    if h[3] > 32 * 1024 * 1024 or h[3] % 4 or h[5] > h[3] or h[4] != declared:
        raise ValueError('Source length/position differs from complete DIRECT command')
    if opcode not in (0x50, 0x51) or bool(h[10]) != (opcode == 0x51):
        raise ValueError('Source metadata does not describe DIRECT/DIRECTHL')
    if len(raw) != HEADER.size + h[3] + h[4]:
        raise ValueError('Truncated or oversized source capture payload')
    return h, raw[HEADER.size:HEADER.size + h[3]], raw[HEADER.size + h[3]:]


def inspect(directory, count=16, gpu_directory=None):
    captures = sorted((read(path), path) for path in directory.glob('*.viftrace'))
    if not 1 <= count <= 32 or [c[0][0][2] for c in captures] != list(range(count)):
        raise ValueError('DIRECT capture window is incomplete or duplicated')
    gpu = []
    if gpu_directory is not None:
        gpu = sorted((read_capture(path)[:2] for path in gpu_directory.glob('*.giftrace')), key=lambda item: item[0][2])
    records = []
    for (h, source, direct), path in captures:
        matches = []
        for i, (g, payload) in enumerate(gpu):
            joined, transfers = b'', []
            for next_h, next_payload in gpu[i:]:
                if next_h[3] != g[3]:
                    continue
                joined += next_payload
                transfers.append(next_h[2])
                if len(joined) >= len(direct):
                    if joined == direct:
                        matches.append({'path': g[3], 'transfers': transfers})
                    break
        records.append({'index': h[2], 'input_bytes': h[3], 'direct_bytes': h[4], 'input_position': h[5],
                        'ee_vsync': h[6], 'total_vif_input_bytes': h[7], 'pending_image_before': h[8],
                        'vif_code': hex(h[9]), 'direct_hl': bool(h[10]), 'chcr': hex(h[11]),
                        'madr': hex(h[12]), 'qwc': h[13], 'tadr': hex(h[14]), 'dma_starts': h[15],
                        'input_sha256': hashlib.sha256(source).hexdigest(),
                        'direct_sha256': hashlib.sha256(direct).hexdigest(),
                        'input_head_hex': source[:128].hex(), 'direct_head_hex': direct[:128].hex(),
                        'gpu_matches': matches, 'file': str(path.resolve())})
    return {'schema': 1, 'captures': len(records), 'source_validated': True, 'records': records,
            'scope': 'Completing VIF input chunk and full DIRECT before IMAGE splitting; DMA registers are observed at submission, not necessarily the original kick. Actor identity and pixel validity are unproven.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--count', type=int, default=16)
    parser.add_argument('--gpu-directory', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.directory, args.count, args.gpu_directory)
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, indent=2))


if __name__ == '__main__':
    main()
