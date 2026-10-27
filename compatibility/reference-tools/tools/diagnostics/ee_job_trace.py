"""Decode observed RE4 job notification calls, without treating entry as completion."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import struct

FIELDS = re.compile(r'\b(target|source|pc|v0|a0)=0x([0-9a-fA-F]+)')
PACKET = re.compile(r'\bmem_451680_at_0_resolved_([0-9a-fA-F]+)=([0-9a-fA-F]+)')


def decode_packet(raw: bytes) -> dict:
    if len(raw) < 24:
        raise ValueError('job header must contain at least 24 bytes')
    return {
        'word_0': hex(struct.unpack_from('<I', raw, 0)[0]),
        'flags_at_4': raw[4],
        'kind_at_5': raw[5],
        'word_8': hex(struct.unpack_from('<I', raw, 8)[0]),
        'reply_semaphore_at_12': struct.unpack_from('<I', raw, 12)[0],
        'halfword_20_before_notification': struct.unpack_from('<H', raw, 20)[0],
        'header_hex': raw[:24].hex(),
    }


def summarize(path: Path) -> dict:
    digest = hashlib.sha256()
    observations = []
    malformed = 0
    shared_entries = 0
    with path.open('rb') as source:
        for number, raw in enumerate(source, 1):
            digest.update(raw)
            line = raw.decode('utf-8', errors='replace')
            if '[EE call enter]' not in line:
                continue
            shared_entries += 1
            fields = {key: int(value, 16) for key, value in FIELDS.findall(line)}
            if fields.get('target') != 0x256010:
                continue
            packet = PACKET.search(line)
            try:
                if not packet or 'a0' not in fields or 'source' not in fields:
                    raise ValueError('missing packet or call arguments')
                header = decode_packet(bytes.fromhex(packet[2]))
            except ValueError:
                malformed += 1
                continue
            observations.append({
                'line': number,
                'source_pc': hex(fields['source']),
                'request_address': hex(int(packet[1], 16)),
                'requested_notification_value': fields['a0'],
                **header,
            })
    return {
        'schema': 1, 'log': str(path.resolve()), 'sha256': digest.hexdigest(),
        'scope': 'Call entry at 0x256010, before notification and its WaitSema; not proof of return, resource correctness, or gameplay.',
        'observed_entries': len(observations), 'malformed_entries': malformed,
        'shared_trace_cap': 256,
        'shared_observed_entries': shared_entries,
        'entries_at_shared_cap': shared_entries >= 256,
        'sources': dict(collections.Counter(x['source_pc'] for x in observations)),
        'job_kinds': dict(collections.Counter(str(x['kind_at_5']) for x in observations)),
        'observations': observations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.suffix.lower() != '.json' or args.out.resolve() == args.log.resolve():
        parser.error('output must be a separate JSON file')
    report = summarize(args.log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Observed {report['observed_entries']} entries; malformed={report['malformed_entries']}; at cap={report['entries_at_shared_cap']}")
    if not report['observed_entries'] or report['malformed_entries']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
