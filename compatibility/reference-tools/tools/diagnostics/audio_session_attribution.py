"""Audit sampled Windows session peaks; capture/loopback sessions may also appear."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROW = re.compile(r'sample=(\d+) unix_ms=(\d+) elapsed=([\d.]+) session=(\d+) pid=(\d+) state=(\d+) level=([-\d.]+) mute=(\d+) peak=([-\d.]+) positive=(\d+) path=(.*)')
SUMMARY = re.compile(r'summary samples=(\d+) target_positive_samples=(\d+) other_positive_samples=(\d+) complete=1')


def analyze(text):
    header = re.search(r'^endpoint=(.+) target_pid=(\d+) interval_ms=100 scope=sampled-session-peaks$', text, re.M)
    endings = list(SUMMARY.finditer(text))
    samples = {}
    malformed = 0
    sources = Counter()
    for line in text.splitlines():
        if not line.startswith('sample='):
            continue
        match = ROW.fullmatch(line)
        if not match:
            malformed += 1
            continue
        n, unix_ms, elapsed, session, pid, state, level, mute, peak, positive, path = match.groups()
        n, unix_ms, pid, state, mute, positive = map(int, (n, unix_ms, pid, state, mute, positive))
        expected = int(state == 1 and mute == 0 and float(level) > 0 and float(peak) > .00001)
        # Printed floats can round at the threshold; reject ambiguity rather
        # than infer a clean recording from an inconsistent observation.
        if expected != positive:
            malformed += 1
        group = samples.setdefault(n, {'unix_ms': unix_ms, 'elapsed': float(elapsed), 'positive_pids': set()})
        if group['unix_ms'] != unix_ms or group['elapsed'] != float(elapsed):
            malformed += 1
        if positive:
            group['positive_pids'].add(pid)
            sources[(pid, path)] += 1
    target = int(header[2]) if header else None
    target_count = sum(target in row['positive_pids'] for row in samples.values()) if target else 0
    other_count = sum(bool(row['positive_pids'] - {target}) for row in samples.values())
    sequence = sorted(samples)
    chronological = all(samples[b]['unix_ms'] >= samples[a]['unix_ms'] and
                        samples[b]['elapsed'] > samples[a]['elapsed'] for a, b in zip(sequence, sequence[1:]))
    complete = bool(header and len(endings) == 1 and samples and not malformed and chronological)
    if complete:
        end = endings[0]
        complete = (sequence == list(range(int(end[1]))) and
                    target_count == int(end[2]) and other_count == int(end[3]))
    return {'scope': __doc__, 'endpoint_id': header[1] if header else None, 'target_pid': target,
            'complete_sample_log': complete, 'malformed_rows': malformed, 'sample_count': len(samples),
            'target_positive_samples': target_count, 'other_positive_samples': other_count,
            'sessions_with_positive_peaks': [{'pid': pid, 'path': path, 'rows': count}
                                           for (pid, path), count in sorted(sources.items())],
            'other_active_session_peak_observed': bool(other_count),
            'independent_output_source_attribution_proven': False,
            'limits': ['Sampled peaks do not isolate PCM or prove silence between observations.',
                       'An active session can capture loopback audio instead of emitting sound; peaks do not establish its stream direction.',
                       'Correlated meters must not be counted as independent playback sources.',
                       'No sample rows for an empty session inventory are treated as incomplete coverage.']}


def selftest():
    header = 'endpoint=test target_pid=9 interval_ms=100 scope=sampled-session-peaks\n'
    def row(n, pid=9, positive=1):
        return f'sample={n} unix_ms={1000+n*100} elapsed={n*.1:.6f} session=0 pid={pid} state=1 level=1.000000 mute=0 peak={.5 if positive else 0:.6f} positive={positive} path=test\n'
    footer = 'summary samples=2 target_positive_samples=2 other_positive_samples=0 complete=1\n'
    good = header + row(0) + row(1) + footer
    assert analyze(good)['complete_sample_log']
    assert not analyze(good.replace(footer, ''))['complete_sample_log']
    assert not analyze(good.replace(row(1), row(2)))['complete_sample_log']
    assert not analyze(good.replace('positive=1', 'positive=0', 1))['complete_sample_log']
    assert not analyze(good.replace('sample=1 ', 'sample=bad '))['complete_sample_log']
    other = header + row(0) + row(1, 7) + footer.replace('target_positive_samples=2 other_positive_samples=0', 'target_positive_samples=1 other_positive_samples=1')
    assert analyze(other)['complete_sample_log'] and analyze(other)['other_active_session_peak_observed']
    assert not analyze(other)['independent_output_source_attribution_proven']
    assert not analyze(header + footer)['complete_sample_log']
    return {'passed': True, 'cases': ['complete', 'truncated', 'gap', 'inconsistent-peak', 'malformed', 'other-source', 'empty-inventory']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path, nargs='?')
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.selftest:
        result = selftest()
    else:
        if args.log is None:
            parser.error('Supply a log or --selftest')
        result = analyze(args.log.read_text(encoding='utf-8-sig'))
        result.update(log=str(args.log.resolve()), log_sha256=hashlib.sha256(args.log.read_bytes()).hexdigest())
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
