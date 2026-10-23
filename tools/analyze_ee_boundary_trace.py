"""Summarize observed EE word changes; this is not a guest store watchpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROW = re.compile(r'^\[EE boundary (transfer|leave)\] (.*)$')
FIELD = re.compile(r'(\w+)=0x([0-9a-fA-F]+)')


def summarize(path: Path, selected: list[int]) -> dict:
    previous = None
    observations = []
    count = 0
    malformed = 0
    exhausted = False
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for number, raw in enumerate(source, 1):
            digest.update(raw)
            line = raw.decode('utf-8', errors='replace').strip()
            exhausted |= '[EE boundary] Row limit reached;' in line
            match = ROW.match(line)
            if not match:
                continue
            fields = {key: int(value, 16) for key, value in FIELD.findall(match[2])}
            keys = [f'word_{address:x}' for address in selected]
            if any(key not in fields for key in keys) or 'source' not in fields:
                malformed += 1
                continue
            count += 1
            values = [fields[key] for key in keys]
            if values != previous:
                observations.append({'line': number, 'phase': match[1],
                                     'fields': {key: f'0x{value:x}' for key, value in fields.items()
                                                if key != 'old'},
                                     'selected_previous': previous})
            previous = values
    return {'schema': 1, 'log': str(path.resolve()), 'log_sha256': digest.hexdigest(),
            'scope': 'observations at guest transfers and nested call exits; PCs are not exact store PCs',
            'selected_words': [hex(address) for address in selected],
            'observed_rows': count, 'malformed_rows': malformed,
            'row_limit_reached': exhausted, 'selected_changes': observations,
            'game_compatibility': 'unverified'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--word', type=lambda value: int(value, 0), action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.suffix.lower() != '.json' or args.out.resolve() == args.log.resolve():
        parser.error('output must be a separate .json report')
    if any(address < 0 or address > 0x2000000 - 4 or address & 3 for address in args.word):
        parser.error('words must be aligned physical EE RAM addresses')
    report = summarize(args.log, args.word)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Observed {report['observed_rows']} rows; selected changes: {len(report['selected_changes'])}")
    if not report['observed_rows'] or report['malformed_rows']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
