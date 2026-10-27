"""Correlate replay/live input with native pad replies, without claiming game response."""
import argparse
import json
from pathlib import Path
import re

SOURCE = re.compile(r'\[pad trace\] stage=(?:replay|live) ms=\d+ focused=-?\d+ host=(\d+) '
                    r'buttons=(\d+) lx=(\d+) ly=(\d+) rx=(\d+) ry=(\d+) host_ms=(\d+) ee_tick=(\d+)')
WIRE = re.compile(r'\[pad wire\] host_ms=(\d+) command=66 mode=(\d+) bytes=(\d+) '
                  r'buttons=(-?\d+) lx=(-?\d+) ly=(-?\d+) rx=(-?\d+) ry=(-?\d+)')


def report(text, max_delay_ms=1000):
    if max_delay_ms <= 0:
        raise ValueError('A positive correlation window is required')
    events = []
    wire_count = 0
    current = None
    for line in text.splitlines():
        source = SOURCE.search(line)
        if source:
            port, buttons, lx, ly, rx, ry, host_ms, tick = map(int, source.groups())
            if buttons > 65535 or any(x > 255 for x in (lx, ly, rx, ry)):
                raise ValueError('Replay input out of range')
            current = {'ee_tick': tick, 'port': port, 'host_ms': host_ms,
                       'source': 'live' if 'stage=live ' in source.group() else 'replay',
                       'packet': [buttons, lx, ly, rx, ry], 'status': 'no_matching_reply'}
            events.append(current)
            continue
        wire = WIRE.search(line)
        if not wire:
            continue
        host_ms, mode, size, *packet = map(int, wire.groups())
        wire_count += 1
        if current is None or current['port'] != 0:
            continue
        delay = host_ms - current['host_ms']
        if not 0 <= delay <= max_delay_ms or current['status'] == 'matching_native_reply':
            continue
        if size < 9:
            current['status'] = 'short_poll'
        elif mode not in (0x73, 0x79):
            current['status'] = 'non_analog_mode'
        elif packet == current['packet']:
            current.update(status='matching_native_reply', reply_host_ms=host_ms,
                           delay_ms=delay, mode=mode, bytes=size)
    matches = [e for e in events if e['status'] == 'matching_native_reply']
    return {'scope': 'Replay/live-to-native-reply correlation only; EE consumption and gameplay response are unproven',
            'max_delay_ms': max_delay_ms, 'source_events': len(events), 'wire_changes': wire_count,
            'matching_reply_count': len(matches),
            'active_axis_matches': sum(e['packet'][1:] != [128] * 4 for e in matches),
            'events': events}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = report(args.log.read_text(encoding='utf-8', errors='replace'))
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'events'}))
