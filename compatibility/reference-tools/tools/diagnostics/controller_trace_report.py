"""Distinguish controller detection, physical input and guest consumption."""
import argparse
import json
import re
from pathlib import Path

PATTERN = re.compile(r'\[pad trace\] stage=(host|guest) ms=(\d+) focused=(-?\d+) host=(-?\d+) buttons=(\d+) lx=(\d+) ly=(\d+) rx=(\d+) ry=(\d+)')


def report(text):
    events = []
    for match in PATTERN.finditer(text):
        stage, *numbers = match.groups()
        ms, focused, host, buttons, lx, ly, rx, ry = map(int, numbers)
        if not (0 <= buttons <= 65535 and all(0 <= v <= 255 for v in (lx, ly, rx, ry))):
            raise ValueError('Malformed controller packet')
        events.append(dict(stage=stage, ms=ms, focused=focused, host=host,
                           packet=[buttons, lx, ly, rx, ry]))
    hosts = [e for e in events if e['stage'] == 'host']
    guests = [e for e in events if e['stage'] == 'guest']
    def actuated(event):
        return event['packet'] != [65535, 128, 128, 128, 128]
    physical = [e for e in hosts if e['focused'] == 1 and e['host'] >= 0 and actuated(e)]
    matched = []
    for guest in guests:
        if not actuated(guest):
            continue
        prior = [e for e in physical if e['ms'] <= guest['ms'] and e['packet'] == guest['packet']]
        if prior:
            matched.append({'host_ms': prior[-1]['ms'], 'guest_ms': guest['ms'], 'packet': guest['packet']})
    return {'scope': 'Observed controller transport only; gameplay response needs separate verification',
            'backend': re.findall(r'\[controller\] input_backend=(\S+)', text),
            'host_events': len(hosts), 'guest_events': len(guests),
            'controller_detected': any(e['host'] >= 0 for e in hosts),
            'focus_loss_observed': any(e['focused'] == 0 for e in hosts),
            'physical_actuated_events': len(physical), 'guest_actuated_events': sum(actuated(e) for e in guests),
            'matching_actuated_packets': matched,
            'physical_to_guest_observed': bool(matched)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = report(args.log.read_text(errors='replace'))
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))
