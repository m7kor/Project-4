"""Rank live VU1 command costs using complete, self-reconciling profile windows."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re


def summarize(path: Path, allow_incomplete_tail: bool = False) -> dict:
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Profile exceeds the 128 MiB analysis limit')
    payload = path.read_bytes()
    lines = payload.splitlines(keepends=True)
    if not lines:
        raise ValueError('Empty VU1 profile')

    def integer(row, key, minimum=0, maximum=None):
        value = row.get(key)
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f'Invalid profile integer: {key}')
        return value

    metadata = None
    window = None
    pending = []
    totals = defaultdict(int)
    groups = {}
    first_ee = last_ee = None
    completed = 0
    tail_discarded = False
    for index, raw in enumerate(lines):
        if len(raw) > 4096:
            raise ValueError('Oversized VU1 profile record')
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            if allow_incomplete_tail and metadata and index == len(lines) - 1 and not raw.endswith(b'\n'):
                tail_discarded = True
                break
            raise ValueError('Malformed VU1 profile record') from None
        if not isinstance(row, dict):
            raise ValueError('Profile records must be objects')
        kind = row.get('kind')
        if index == 0:
            if kind != 'meta' or type(row.get('schema')) is not int or row['schema'] != 1 or row.get('clock') != 'steady_clock_ns':
                raise ValueError('Missing supported VU1 profile metadata')
            integer(row, 'from_ee')
            integer(row, 'interval_ee', 1)
            metadata = row
            continue
        if kind == 'window':
            if window is not None:
                raise ValueError('Missing window end marker')
            if integer(row, 'index') != completed:
                raise ValueError('Nonsequential VU1 profile windows')
            a = integer(row, 'first_ee', metadata['from_ee'])
            b = integer(row, 'last_ee', a)
            if b - a >= metadata['interval_ee']:
                raise ValueError('Window exceeds its declared field interval')
            integer(row, 'groups', 1, 128)
            integer(row, 'calls', 1)
            integer(row, 'cycles')
            integer(row, 'nanoseconds')
            window, pending = row, []
        elif kind == 'group':
            if window is None or integer(row, 'window') != window['index']:
                raise ValueError('Group outside its declared window')
            if not isinstance(row.get('code_fnv1a64'), str) or not re.fullmatch(r'[0-9a-f]{16}', row['code_fnv1a64']):
                raise ValueError('Invalid microprogram identity')
            if integer(row, 'start_pc', 0, 16383) % 8 or type(row.get('resume')) is not bool:
                raise ValueError('Invalid VU1 command identity')
            calls = integer(row, 'calls', 1)
            integer(row, 'cycles')
            ns = integer(row, 'nanoseconds')
            integer(row, 'max_nanoseconds', 0, ns)
            integer(row, 'compiled_calls', 0, calls)
            key = (row['code_fnv1a64'], row['start_pc'], row['resume'])
            if any((p['code_fnv1a64'], p['start_pc'], p['resume']) == key for p in pending):
                raise ValueError('Duplicate group within a window')
            pending.append(row)
            if len(pending) > window['groups']:
                raise ValueError('Too many groups in a window')
        elif kind == 'end':
            if window is None or integer(row, 'index') != window['index']:
                raise ValueError('Unmatched window end marker')
            if len(pending) != window['groups'] or any(
                sum(p[key] for p in pending) != window[key]
                for key in ('calls', 'cycles', 'nanoseconds')
            ):
                raise ValueError('Window totals do not reconcile')
            for group in pending:
                key = (group['code_fnv1a64'], group['start_pc'], group['resume'])
                aggregate = groups.setdefault(key, dict(code_fnv1a64=key[0], start_pc=key[1],
                                                       resume=key[2], calls=0, cycles=0,
                                                       nanoseconds=0, compiled_calls=0, max_nanoseconds=0))
                for name in ('calls', 'cycles', 'nanoseconds', 'compiled_calls'):
                    aggregate[name] += group[name]
                    totals[name] += group[name]
                aggregate['max_nanoseconds'] = max(aggregate['max_nanoseconds'], group['max_nanoseconds'])
            first_ee = window['first_ee'] if first_ee is None else min(first_ee, window['first_ee'])
            last_ee = window['last_ee'] if last_ee is None else max(last_ee, window['last_ee'])
            completed += 1
            window, pending = None, []
        else:
            raise ValueError('Unknown VU1 profile record kind')
    if window is not None:
        if not allow_incomplete_tail:
            raise ValueError('Incomplete trailing VU1 profile window')
        tail_discarded = True
    if not completed or not totals['nanoseconds']:
        raise ValueError('No complete timed VU1 windows')
    ranked = sorted(groups.values(), key=lambda group: group['nanoseconds'], reverse=True)
    for group in ranked:
        group['start_pc_hex'] = f"0x{group['start_pc']:04x}"
        group['time_percent'] = 100 * group['nanoseconds'] / totals['nanoseconds']
        group['ns_per_cycle'] = group['nanoseconds'] / group['cycles'] if group['cycles'] else None
    return {'schema': 1, 'scope': 'Live VU1 execution census; completed windows only, not game speed or campaign coverage',
            'profile': str(path.resolve()), 'profile_sha256': hashlib.sha256(payload).hexdigest(),
            'metadata': metadata, 'complete_windows': completed, 'first_ee': first_ee, 'last_ee': last_ee,
            'incomplete_tail_discarded': tail_discarded, 'totals': dict(totals), 'groups': ranked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--allow-incomplete-tail', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = summarize(args.profile, args.allow_incomplete_tail)
        with args.out.open('x', encoding='utf-8') as output:
            json.dump(report, output, indent=2)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps({k: report[k] for k in ('complete_windows', 'first_ee', 'last_ee', 'totals')}))
    for group in report['groups'][:12]:
        print(f"{group['time_percent']:6.2f}% code={group['code_fnv1a64']} pc={group['start_pc_hex']} "
              f"resume={group['resume']} calls={group['calls']} compiled={group['compiled_calls']}")


if __name__ == '__main__':
    main()
