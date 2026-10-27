"""Compare expanded per-pair VU1 tables before/after adding captured images.

Constant numbering may change. Existing decoded pairs and analysis fields must
remain identical at every PC. Runtime semantics are separately checked by replay.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def load(path):
    text = path.read_text(encoding='utf-8')
    constants = dict(re.findall(r'static constexpr P (k\d+) = ([^\n]+);', text))
    tables = {}
    for identity, body in re.findall(r'CompiledPairFn t_([0-9a-f]{16})\[2048\] = \{(.*?)\n    \};', text, re.S):
        keys = re.findall(r'&step<(k\d+)>', body)
        if len(keys) != 2048 or any(key not in constants for key in keys):
            raise ValueError(f'Incomplete per-pair table: {identity}')
        tables[identity] = [constants[key] for key in keys]
    if not tables:
        raise ValueError('No default per-pair tables found')
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    before, after = load(args.before), load(args.after)
    changed = [key for key in before if after.get(key) != before[key]]
    result = {'scope': __doc__, 'before_sha256': hashlib.sha256(args.before.read_bytes()).hexdigest(),
              'after_sha256': hashlib.sha256(args.after.read_bytes()).hexdigest(),
              'existing_tables': len(before), 'existing_pairs': len(before) * 2048,
              'changed_existing_tables': changed, 'added_tables': sorted(set(after) - set(before)),
              'passed': not changed}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
