"""Summarize bounded IPU register observations from a closed native capture."""
import argparse
import hashlib
import json
from pathlib import Path
import re

RECORD = re.compile(rb'\[IPU MMIO\] op=(write|read-stored|read) index=([0-9]+) address=0x([0-9a-f]+) value=0x([0-9a-f]+)')


def audit(capture: Path) -> dict:
    report_path = capture / 'report.json'
    payload = report_path.read_bytes()
    if len(payload) > 1024 * 1024:
        raise ValueError('capture report exceeds 1 MiB')
    capture_report = json.loads(payload)
    if 'process_returncode' not in capture_report and 'exit_code' not in capture_report:
        raise ValueError('capture has no terminal process result')
    log = capture / 'stderr.txt'
    before = log.stat()
    digest = hashlib.sha256()
    records, caps, malformed, long_lines = [], [], 0, 0
    armed = False
    line_number = 0
    with log.open('rb') as stream:
        while True:
            line = stream.readline(65537)
            if not line:
                break
            digest.update(line)
            line_number += 1
            if len(line) > 65536 and not line.endswith(b'\n'):
                long_lines += 1
                while line and not line.endswith(b'\n'):
                    line = stream.readline(65537)
                    digest.update(line)
                continue
            if b'[EE trace:armed]' in line:
                armed = True
            if b'[IPU MMIO capped]' in line:
                if len(caps) < 4:
                    caps.append({'line': line_number, 'message': line.decode('utf-8', 'replace').strip()})
            if b'[IPU MMIO]' not in line:
                continue
            match = RECORD.search(line)
            if not match:
                malformed += 1
                continue
            if len(records) >= 1280:
                raise ValueError('IPU trace exceeds expected bounded record count')
            op, index, address, value = match.groups()
            records.append({'line': line_number, 'op': op.decode(), 'index': int(index),
                            'address': int(address, 16), 'value': int(value, 16),
                            'after_call_arm': armed})
    after = log.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('capture log changed during audit')

    def summarize(items):
        writes = [x for x in items if x['op'] == 'write']
        commands = [x for x in writes if x['address'] == 0x10002000]
        starts = [x for x in writes if x['address'] in (0x1000b000, 0x1000b400) and x['value'] & 0x100]
        return {'records': len(items), 'writes': len(writes),
                'stored_reads': len(items) - len(writes),
                'command_write_values': [x['value'] for x in commands],
                'dma_start_requests': starts,
                'fifo_word_writes': sum(0x10007000 <= x['address'] < 0x10007020 for x in writes)}

    return {'scope': 'MMIO requests and backing-register observations only; no proof of DMA completion, decode, or gameplay. Absence is limited to instrumented paths and recorded interval.',
            'capture': str(capture.resolve()), 'report_sha256': hashlib.sha256(payload).hexdigest(),
            'log_sha256': digest.hexdigest(), 'runner_sha256': capture_report.get('runner_sha256'),
            'trace_enabled': capture_report.get('trace_configuration', {}).get('ipu_mmio_enabled'),
            'call_arm_seen': armed, 'caps': caps, 'malformed': malformed, 'long_lines_skipped': long_lines,
            'all': summarize(records), 'after_call_arm': summarize([x for x in records if x['after_call_arm']]),
            'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.capture)
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f'{error}\n')
    print(json.dumps({key: result[key] for key in ('all', 'after_call_arm', 'call_arm_seen', 'caps')}, indent=2))


if __name__ == '__main__':
    main()
