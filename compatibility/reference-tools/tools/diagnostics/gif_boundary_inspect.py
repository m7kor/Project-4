"""Inspect bounded GPU GIF captures; framing proof, not GS rendering or model correctness."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

MAGIC = 0x3143525453473250
HEADER = struct.Struct('<20Q')


def tag_fields(low, high):
    return {'nloop': low & 0x7FFF, 'eop': (low >> 15) & 1,
            'flg': (low >> 58) & 3, 'nreg': ((low >> 60) & 15) or 16,
            'pre': (low >> 46) & 1, 'prim': (low >> 47) & 0x7FF,
            'registers': [(high >> (4 * i)) & 15 for i in range(((low >> 60) & 15) or 16)]}


def state(values):
    loop, reg, low, high = values
    return {'loop': loop, 'reg': reg, 'tag_lo': hex(low), 'tag_hi': hex(high), **tag_fields(low, high)}


def replay(payload, initial):
    """Framing only: advance PACKED, padded REGLIST and IMAGE cursor independently."""
    loop, reg, low, high = initial
    pos, tags, segments = 0, [], []
    while pos < len(payload):
        fields = tag_fields(low, high)
        nloop, nreg, flg = fields['nloop'], fields['nreg'], fields['flg']
        if loop > nloop or reg >= nreg:
            raise ValueError('Invalid initial GIF cursor')
        if loop == nloop:
            low, high = struct.unpack_from('<2Q', payload, pos)
            loop = reg = 0
            tags.append({'offset': pos, 'tag_lo': hex(low), 'tag_hi': hex(high), **tag_fields(low, high)})
            pos += 16
            continue
        available = (len(payload) - pos) // 16
        start = pos
        if flg == 0:
            consumed = min(available, (nloop - loop) * nreg - reg)
            total = reg + consumed
            loop += total // nreg
            reg = total % nreg
            pos += consumed * 16
        elif flg == 1:
            consumed = min(available * 2, (nloop - loop) * nreg - reg)
            total = reg + consumed
            loop += total // nreg
            reg = total % nreg
            pos += ((consumed + 1) // 2) * 16
        else:  # FLG3 is the IMAGE alias used by the captured GS implementation.
            consumed = min(available, nloop - loop)
            loop += consumed
            pos += consumed * 16
        if pos == start:
            raise ValueError('GIF framing made no progress')
        segments.append({'offset': start, 'bytes': pos - start, 'flg': flg})
    return (loop, reg, low, high), tags, segments


def read_capture(path):
    raw = path.read_bytes()
    if len(raw) < HEADER.size:
        raise ValueError('Truncated capture header')
    h = HEADER.unpack_from(raw)
    if h[0] != MAGIC or h[1] != 1 or h[2] < 1 or h[3] not in (1, 2, 3) or h[7] not in (0, 1):
        raise ValueError('Invalid capture signature, identity or reset flag')
    if h[4] > 32 * 1024 * 1024 or h[4] % 16 or len(raw) != HEADER.size + h[4]:
        raise ValueError('Capture payload length mismatch')
    return h, raw[HEADER.size:], hashlib.sha256(raw).hexdigest()


def inspect(directory, first=None, count=None):
    records, seen, previous, issues = [], set(), {}, []
    captures = []
    for path in directory.glob('*.giftrace'):
        header, payload, digest = read_capture(path)
        captures.append((header[2], path, header, payload, digest))
    for transfer, path, h, payload, digest in sorted(captures):
        if transfer in seen:
            raise ValueError('Duplicate global transfer number')
        seen.add(transfer)
        before, effective, after = tuple(h[8:12]), tuple(h[12:16]), tuple(h[16:20])
        expected_entry = ((before[2] & 0x7FFF), 0, before[2], before[3]) if h[7] else before
        if effective != expected_entry:
            issues.append(f'Transfer {transfer}: effective state does not match reset policy')
        if h[3] in previous and previous[h[3]] != before:
            issues.append(f'Transfer {transfer}: same-path cursor changed between captured calls')
        predicted, tags, segments = replay(payload, effective)
        if predicted != after:
            issues.append(f'Transfer {transfer}: independent framing differs from GPU exit cursor')
        row = {'transfer': transfer, 'path': h[3], 'bytes': h[4], 'gs_vsync': h[5],
               'finishes_before': h[6], 'resync': bool(h[7]), 'capture_sha256': digest,
               'payload_sha256': hashlib.sha256(payload).hexdigest(), 'file': str(path.resolve()),
               'before': state(before), 'effective': state(effective), 'after': state(after),
               'framing_matches_exit': predicted == after, 'tags': tags, 'payload_segments': segments,
               'head_hex': payload[:128].hex()}
        if h[7]:
            preserved, preserved_tags, _ = replay(payload, before)
            row.update(without_reset_after=state(preserved), without_reset_tags=preserved_tags,
                       reset_changes_framing=preserved != after or preserved_tags != tags)
        records.append(row)
        previous[h[3]] = after
    if not records:
        raise ValueError('No capture files')
    if (first is None) != (count is None):
        raise ValueError('Supply both expected interval endpoints')
    if first is not None:
        if not 1 <= count <= 128 or first < 1 or seen != set(range(first, first + count)):
            raise ValueError('Capture interval is incomplete or contains unexpected transfers')
    return {'schema': 1, 'capture_directory': str(directory.resolve()), 'records': records,
            'captures': len(records), 'resync_transfers': [r['transfer'] for r in records if r['resync']],
            'issues': issues, 'framing_verified': not issues,
            'scope': 'Complete bytes and parser cursor at GPU entry/reset/exit; upstream producer, VRAM, vertices and rendering are not captured.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--from-transfer', type=int)
    parser.add_argument('--count', type=int)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.directory, args.from_transfer, args.count)
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, indent=2))
    return 0 if report['framing_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
