"""Audit the complete existing IOP RPC entry trace for legacy libsd playback candidates.

All IopSubsystem fallback requests pass IopRpcBridge first. Legacy playback
requires SID 0x80000701 and fn 0x8010 or 0x81xx with at least 20 sent bytes.
Presence is only a candidate: native handling, valid samples and audio readiness
are not determined here. Absence needs a complete numbered trace.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

PATTERN = re.compile(r'\[IOP RPC\] n=(\d+) sid=0x([0-9a-f]+) fn=0x([0-9a-f]+) mode=0x([0-9a-f]+) send=0x([0-9a-f]+) recv=0x([0-9a-f]+)')


def analyze(text):
    rows, malformed = [], 0
    for line in text.splitlines():
        if '[IOP RPC]' not in line:
            continue
        found = PATTERN.search(line)
        if not found:
            malformed += 1
            continue
        values = [int(found[1])] + [int(value, 16) for value in found.groups()[1:]]
        rows.append(dict(zip(('sequence', 'sid', 'function', 'mode', 'send_bytes', 'receive_bytes'), values)))
    complete = bool(rows) and not malformed and [row['sequence'] for row in rows] == list(range(1, len(rows) + 1))
    counts = Counter((row['sid'], row['function']) for row in rows)
    libsd = [row for row in rows if row['sid'] == 0x80000701]
    candidates = [row for row in libsd if (row['function'] == 0x8010 or row['function'] & 0xFF00 == 0x8100)
                  and row['send_bytes'] >= 20]
    return {'scope': __doc__, 'requests': len(rows), 'numbered_trace_complete': complete,
            'malformed_trace_lines': malformed, 'libsd_requests': len(libsd), 'playback_candidates': candidates,
            'legacy_rpc_playback_excluded_in_trace': complete and not candidates,
            'sid_function_counts': [{'sid': hex(sid), 'function': hex(function), 'count': count}
                                    for (sid, function), count in sorted(counts.items())],
            'limits': ['Only the traced run; does not certify later campaign scenes.',
                       'Does not audit device effects or audio from other applications.',
                       'Direct backend play callers, if added later, require separate instrumentation.']}


def selftest():
    def line(n, sid='80000400', function='1', sent='14'):
        return f'[IOP RPC] n={n} sid=0x{sid} fn=0x{function} mode=0x0 send=0x{sent} recv=0x4'
    assert analyze(line(1) + '\n' + line(2))['legacy_rpc_playback_excluded_in_trace']
    assert len(analyze(line(1, '80000701', '8010'))['playback_candidates']) == 1
    assert len(analyze(line(1, '80000701', '81ff'))['playback_candidates']) == 1
    assert analyze(line(1, '80000701', '8010', '10'))['legacy_rpc_playback_excluded_in_trace']
    assert not analyze(line(1) + '\n' + line(3))['numbered_trace_complete']
    assert not analyze('[IOP RPC] truncated')['legacy_rpc_playback_excluded_in_trace']
    assert not analyze('')['legacy_rpc_playback_excluded_in_trace']
    return {'passed': True, 'cases': ['no-libsd', 'set-voice', '81xx', 'short-payload', 'sequence-gap', 'malformed', 'empty']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path, nargs='?')
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.selftest:
        report = selftest()
    else:
        if args.log is None:
            parser.error('Supply stderr trace or --selftest')
        payload = args.log.read_bytes()
        report = analyze(payload.decode('utf-8', errors='replace'))
        report.update(log=str(args.log.resolve()), log_sha256=hashlib.sha256(payload).hexdigest())
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key not in ('scope', 'sid_function_counts', 'playback_candidates', 'limits')}))


if __name__ == '__main__':
    main()
