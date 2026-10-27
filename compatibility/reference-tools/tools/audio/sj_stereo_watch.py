"""Locate stereo SJ cursor divergence in an EE boundary watch of two SJCS objects.

Use PS2X_WATCH_RANGE=0x30a020:128 for the verified RE4 layout. Report only
right-channel read-cursor updates made by GetChunk, after the left reservation
can have occurred; intermediate left-only updates are not classified. A
divergence is an observation, not proof of a scheduler or guest-code fault.
"""
import argparse
from collections import deque
import json
from pathlib import Path
import re


WATCH = re.compile(r'^\[watch\] v=(\d+) source=0x([0-9a-f]+) target=0x([0-9a-f]+).*words=([0-9a-f,]+)')


def inspect(lines):
    previous = None
    context = deque(maxlen=8)
    rows = ignored = reservations = 0
    first = None
    divergent = 0
    for line in lines:
        match = WATCH.match(line)
        if not match:
            continue
        words = [int(value, 16) for value in match[4].split(',') if value]
        if len(words) != 32 or words[8] != words[24] or not words[8]:
            ignored += 1
            previous = None
            continue
        rows += 1
        context.append(line.rstrip())
        # +0x14 is the lane-zero read cursor; initial full lane zero is the
        # decoder's writable reservoir, despite the generic SJ "data" name.
        if previous is not None and words[21] != previous[21] and int(match[2], 16) == 0x189a04:
            reservations += 1
            if words[5] != words[21]:
                divergent += 1
                if first is None:
                    first = {'vsync': int(match[1]), 'source': '0x' + match[2],
                             'target': '0x' + match[3], 'left_cursor': words[5],
                             'right_cursor': words[21],
                             'difference_mod_capacity_bytes': (words[21] - words[5]) % words[8],
                             'words': [hex(word) for word in words], 'context': list(context)}
        previous = words
    return {'schema': 1, 'valid_rows': rows, 'ignored_watch_rows': ignored,
            'right_reservations': reservations, 'divergent_right_reservations': divergent,
            'first_divergence': first, 'scope': __doc__.strip()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stderr', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output already exists')
    with args.stderr.open(errors='replace') as source:
        result = inspect(source)
    if not result['valid_rows']:
        parser.error('no complete two-object watch records')
    result['input'] = str(args.stderr.resolve())
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'scope'}, indent=2))
