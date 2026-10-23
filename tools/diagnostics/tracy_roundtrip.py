"""Verify Tracy import/export of VU1 subprocess traces, including timing units."""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import subprocess


def verify_trace(trace, exported):
    events = [event for event in trace['traceEvents'] if event.get('ph') == 'X']
    if not events:
        raise ValueError('No measured zones')
    by_name = {}
    for event in events:
        name = event['name']
        if name in by_name:
            raise ValueError('This replay verifier requires unique zone names')
        for key in ('ts', 'dur'):
            value = event[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Invalid measured time')
        if event['ts'] < 0 or event['dur'] <= 0:
            raise ValueError('Measured zones require positive duration')
        by_name[name] = event
    rows = list(csv.DictReader(io.StringIO(exported)))
    if len(rows) != len(events) or {row['name'] for row in rows} != set(by_name):
        raise ValueError('Missing, extra or duplicate exported zones')
    origin = min(event['ts'] for event in events)
    max_error = 0
    for row in rows:
        event = by_name[row['name']]
        for field, expected in (('exec_time_ns', event['dur'] * 1000),
                                ('ns_since_start', (event['ts'] - origin) * 1000)):
            error = abs(int(row[field]) - expected)
            max_error = max(max_error, error)
            if error > 100:
                raise ValueError(f'Tracy timing mismatch: {row["name"]}/{field}')
    return {'zones': len(events), 'max_error_ns': max_error, 'duration_and_start_roundtrip': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--importer', type=Path, required=True)
    parser.add_argument('--exporter', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='Fresh directory')
    args = parser.parse_args()
    trace = json.loads(args.trace.read_text(encoding='utf-8'))
    args.out.mkdir(parents=True, exist_ok=False)
    capture = args.out.resolve() / 'replay.tracy'
    report = {'scope': 'Measured replay subprocess times; not game frame timing', 'accepted': False}
    try:
        imported = subprocess.run([str(args.importer.resolve()), str(args.trace.resolve()), str(capture)],
                                  capture_output=True, text=True, timeout=60)
        with (args.out / 'import.log').open('x', encoding='utf-8') as output:
            output.write(imported.stdout + imported.stderr)
        if imported.returncode or not capture.is_file() or capture.stat().st_size == 0:
            raise ValueError('Tracy import failed or produced no capture')
        exported = subprocess.run([str(args.exporter.resolve()), '-u', str(capture)],
                                  capture_output=True, text=True, timeout=60)
        with (args.out / 'export.log').open('x', encoding='utf-8') as output:
            output.write(exported.stderr)
        if exported.returncode:
            raise ValueError('Tracy export failed')
        with (args.out / 'zones.csv').open('x', encoding='utf-8') as output:
            output.write(exported.stdout)
        report.update(verify_trace(trace, exported.stdout), accepted=True)
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        report['error'] = str(error)
    with (args.out / 'report.json').open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps(report))
    if not report['accepted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
